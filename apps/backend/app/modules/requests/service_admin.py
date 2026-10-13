"""Бизнес-правила Admin API заявок.

Движка workflow нет: менеджер переводит заявку в любой статус. Каждое
реальное изменение оставляет запись в request_status_history (читается
в карточке) и в журнале аудита (прослеживаемость). Чтение не
журналируется.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, PageParams
from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.customers.notifications import CustomerNotificationService
from app.modules.geo.models import Region
from app.modules.notifications.events import NotificationEvents
from app.modules.notifications.models import NotificationOutbox
from app.modules.notifications.queue import (
    NotificationQueue,
    NullNotificationQueue,
    wake_worker,
)
from app.modules.pricing.enums import PricingType
from app.modules.requests.audit import REQUEST_ENTITY, RequestAuditAction
from app.modules.requests.enums import RequestKind, RequestSource, RequestStatus
from app.modules.requests.exceptions import (
    RequestAttachmentNotFoundError,
    RequestNotFoundError,
)
from app.modules.requests.models import RequestAttachment, RequestComment, RequestStatusHistory
from app.modules.requests.repository_admin import (
    AdminRequestRepository,
    RequestAdminFilters,
    RequestAdminSort,
)
from app.modules.requests.schemas_admin import (
    RegionRef,
    RequestAttachmentRead,
    RequestCommentCreate,
    RequestCommentRead,
    RequestDetail,
    RequestItemRead,
    RequestListItem,
    RequestStatusHistoryRead,
    RequestStatusUpdate,
    UserRef,
)
from app.modules.users.models import User


class AdminRequestService(BaseService):
    def __init__(self, session: AsyncSession, delivery: NotificationQueue | None = None) -> None:
        super().__init__(session)
        self.repository = AdminRequestRepository(session)
        self.audit = AuditService(session)
        # Уведомление в кабинете (запись в БД) и письмо (outbox) — разные
        # вещи: первое клиент видит всегда, второе уходит только на
        # подтверждённый адрес.
        self.notifications = CustomerNotificationService(session)
        self.events = NotificationEvents(session)
        self.delivery = delivery or NullNotificationQueue()

    # -------------------------------------------------------------- чтение
    async def list_requests(
        self, *, filters: RequestAdminFilters, sort: RequestAdminSort, params: PageParams
    ) -> Page[RequestListItem]:
        rows, total = await self.repository.list_requests(filters=filters, sort=sort, params=params)
        items = [
            RequestListItem(
                id=row.request.id,
                number=row.request.number,
                kind=RequestKind(row.request.kind),
                source=RequestSource(row.request.source),
                status=RequestStatus(row.request.status),
                customer_name=row.request.customer_name,
                phone=row.request.phone,
                email=row.request.email,
                company=row.request.company,
                region=self._region(row.region),
                items_count=row.items_count,
                total_estimate=row.request.total_estimate,
                currency=row.request.currency,
                created_at=row.request.created_at,
                updated_at=row.request.updated_at,
            )
            for row in rows
        ]
        return Page.create(items, total, params)

    async def get_request(self, request_id: int) -> RequestDetail:
        found = await self.repository.get_detail(request_id)
        if found is None:
            raise RequestNotFoundError
        request, region = found

        comments = self._sorted_comments(request.comments)
        history = self._sorted_history(request.status_history)
        authors = await self.repository.get_users(self._author_ids([*comments, *history]))

        return RequestDetail(
            id=request.id,
            uuid=request.uuid,
            number=request.number,
            kind=RequestKind(request.kind),
            status=RequestStatus(request.status),
            source=RequestSource(request.source),
            customer_name=request.customer_name,
            phone=request.phone,
            email=request.email,
            company=request.company,
            bin=request.bin,
            region=self._region(region),
            comment=request.comment,
            page_url=request.page_url,
            currency=request.currency,
            total_estimate=request.total_estimate,
            attachments=[
                RequestAttachmentRead(
                    id=attachment.id,
                    filename=attachment.filename,
                    content_type=attachment.content_type,
                    size_bytes=attachment.size_bytes,
                    created_at=attachment.created_at,
                )
                for attachment in sorted(request.attachments, key=lambda item: item.id)
            ],
            items=[
                RequestItemRead(
                    id=item.id,
                    product_id=item.product_id,
                    sku=item.sku_snapshot,
                    name=item.name_snapshot,
                    unit=item.unit_snapshot,
                    pricing_type=PricingType(item.pricing_type_snapshot),
                    quantity=item.quantity,
                    unit_price=item.unit_price_snapshot,
                    line_total=item.line_total_snapshot,
                    color=item.color_code_snapshot,
                    color_name=item.color_name_snapshot,
                )
                for item in sorted(request.items, key=lambda item: (item.sort_order, item.id))
            ],
            comments=[self._comment_to_read(item, authors) for item in comments],
            status_history=[self._history_to_read(item, authors) for item in history],
            created_at=request.created_at,
            updated_at=request.updated_at,
        )

    async def get_attachment(self, request_id: int, attachment_id: int) -> RequestAttachment:
        attachment = await self.repository.get_attachment(request_id, attachment_id)
        if attachment is None:
            raise RequestAttachmentNotFoundError
        return attachment

    async def list_comments(self, request_id: int) -> list[RequestCommentRead]:
        await self._require_exists(request_id)
        comments = await self.repository.list_comments(request_id)
        authors = await self.repository.get_users(self._author_ids(comments))
        return [self._comment_to_read(item, authors) for item in comments]

    async def list_history(self, request_id: int) -> list[RequestStatusHistoryRead]:
        await self._require_exists(request_id)
        history = await self.repository.list_history(request_id)
        authors = await self.repository.get_users(self._author_ids(history))
        return [self._history_to_read(item, authors) for item in history]

    # -------------------------------------------------------------- запись
    async def update_status(
        self, request_id: int, payload: RequestStatusUpdate, actor: User
    ) -> RequestDetail:
        """Меняет статус и фиксирует переход.

        Повторная установка текущего статуса ничего не меняет: ни
        записи в истории, ни события аудита. Так повтор запроса после
        сетевой ошибки не плодит фиктивные переходы «NEW → NEW».
        """
        request = await self.repository.get_for_update(request_id)
        if request is None:
            raise RequestNotFoundError

        old_status = request.status
        new_status = payload.status.value
        outbox: list[NotificationOutbox] = []

        if new_status != old_status:
            request.status = new_status
            self.session.add(
                RequestStatusHistory(
                    request_id=request.id,
                    from_status=old_status,
                    to_status=new_status,
                    user_id=actor.id,
                    comment=payload.comment,
                )
            )
            await self.session.flush()
            self.audit.record(
                action=RequestAuditAction.STATUS_UPDATED,
                entity_type=REQUEST_ENTITY,
                entity_id=request.id,
                user_id=actor.id,
                changes={"status": {"old": old_status, "new": new_status}},
            )
            # Заявка из кабинета: клиент узнаёт о смене статуса в той же
            # транзакции — откат смены статуса откатит и уведомление.
            if request.customer_id is not None:
                self.notifications.request_status_changed(
                    customer_id=request.customer_id,
                    number=request.number,
                    status=payload.status,
                )
                outbox.extend(
                    await self._email_customer(
                        request.customer_id,
                        lambda email, name: self.events.request_status_changed(
                            request=request,
                            email=email,
                            status=new_status,
                            customer_name=name,
                        ),
                    )
                )

        outbox_ids = await self.events.outbox.identify(outbox)
        await self.commit()
        await wake_worker(self.delivery, outbox_ids)
        return await self.get_request(request.id)

    async def add_comment(
        self, request_id: int, payload: RequestCommentCreate, actor: User
    ) -> RequestCommentRead:
        link = await self.repository.get_customer_link(request_id)
        if link is None:
            raise RequestNotFoundError
        customer_id, number = link

        comment = RequestComment(
            request_id=request_id,
            user_id=actor.id,
            body=payload.body,
            is_internal=not payload.visible_to_customer,
        )
        self.session.add(comment)
        await self.session.flush()

        # Текст комментария в журнал не попадает: менеджеры пишут туда
        # телефоны, суммы и договорённости с клиентом.
        self.audit.record(
            action=RequestAuditAction.COMMENT_CREATED,
            entity_type=REQUEST_ENTITY,
            entity_id=request_id,
            user_id=actor.id,
            changes={"comment_id": comment.id},
        )
        outbox: list[NotificationOutbox] = []
        # ВНУТРЕННИЙ комментарий клиенту не уходит никуда: ни в кабинет,
        # ни на почту. Менеджеры пишут туда суммы и договорённости.
        if customer_id is not None and not comment.is_internal:
            self.notifications.request_comment_added(customer_id=customer_id, number=number)
            request = await self.repository.get_for_update(request_id)
            if request is not None:
                outbox.extend(
                    await self._email_customer(
                        customer_id,
                        lambda email, name: self.events.request_comment_added(
                            request=request,
                            email=email,
                            comment_id=comment.id,
                            customer_name=name,
                        ),
                    )
                )

        outbox_ids = await self.events.outbox.identify(outbox)
        await self.commit()
        await wake_worker(self.delivery, outbox_ids)
        return self._comment_to_read(comment, {actor.id: actor})

    async def _email_customer(
        self,
        customer_id: int,
        build: Callable[[str, str], list[NotificationOutbox]],
    ) -> list[NotificationOutbox]:
        """Ставит письмо, только если адрес клиента подтверждён."""
        contact = await self.repository.get_verified_customer(customer_id)
        if contact is None:
            return []
        email, name = contact
        return build(email, name)

    # ---------------------------------------------------------- внутреннее
    async def _require_exists(self, request_id: int) -> None:
        if not await self.repository.exists(request_id):
            raise RequestNotFoundError

    def _region(self, region: Region | None) -> RegionRef | None:
        if region is None:
            return None
        return RegionRef(id=region.id, code=region.code, name=region.name)

    def _sorted_comments(self, comments: Iterable[RequestComment]) -> list[RequestComment]:
        return sorted(comments, key=lambda item: (item.created_at, item.id))

    def _sorted_history(
        self, history: Iterable[RequestStatusHistory]
    ) -> list[RequestStatusHistory]:
        return sorted(history, key=lambda item: (item.created_at, item.id))

    def _author_ids(self, entries: Sequence[RequestComment | RequestStatusHistory]) -> list[int]:
        return [entry.user_id for entry in entries if entry.user_id is not None]

    def _user(self, user_id: int | None, authors: dict[int, User]) -> UserRef | None:
        user = authors.get(user_id) if user_id is not None else None
        if user is None:
            return None
        return UserRef(uuid=user.uuid, full_name=user.full_name)

    def _comment_to_read(
        self, comment: RequestComment, authors: dict[int, User]
    ) -> RequestCommentRead:
        return RequestCommentRead(
            id=comment.id,
            body=comment.body,
            is_internal=comment.is_internal,
            author=self._user(comment.user_id, authors),
            created_at=comment.created_at,
        )

    def _history_to_read(
        self, entry: RequestStatusHistory, authors: dict[int, User]
    ) -> RequestStatusHistoryRead:
        return RequestStatusHistoryRead(
            id=entry.id,
            from_status=RequestStatus(entry.from_status) if entry.from_status else None,
            to_status=RequestStatus(entry.to_status),
            comment=entry.comment,
            changed_by=self._user(entry.user_id, authors),
            created_at=entry.created_at,
        )
