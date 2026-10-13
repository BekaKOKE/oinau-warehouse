"""Заявки клиента в кабинете: создание, история, детали.

Создание переиспользует `RequestSubmissionService` целиком — расчёт цен,
снапшоты позиций, идемпотентность и аудит те же, что у анонимной формы.
Кабинет добавляет только привязку к клиенту и, при желании, к проекту.

Клиент видит лишь свои заявки: владение проверяется в SQL, чужой номер
неотличим от несуществующего (404).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, PageParams
from app.core.service import BaseService
from app.modules.customers.enums import CustomerRequestStatus
from app.modules.customers.exceptions import CustomerRequestNotFoundError, ProjectNotFoundError
from app.modules.customers.models import Customer, CustomerProject
from app.modules.customers.repository_account import CustomerAccountRepository
from app.modules.customers.schemas_account import (
    CustomerRequestCommentRead,
    CustomerRequestCreate,
    CustomerRequestDetail,
    CustomerRequestItemRead,
    CustomerRequestListItem,
    CustomerRequestStatusRead,
    ProjectRef,
    RegionRef,
)
from app.modules.notifications.queue import NotificationQueue, NullNotificationQueue
from app.modules.pricing.enums import PricingType
from app.modules.requests.enums import RequestSource, RequestStatus
from app.modules.requests.schemas_public import PublicRequestCreate, PublicRequestCreated
from app.modules.requests.service import RequestSubmissionService
from app.modules.users.service import RequestContext


def customer_status(status: str) -> CustomerRequestStatus:
    """Внутренний статус → статус для клиента. SPAM показывается как отмена."""
    if status == RequestStatus.SPAM.value:
        return CustomerRequestStatus.CANCELLED
    return CustomerRequestStatus(status)


def project_ref(project: CustomerProject | None) -> ProjectRef | None:
    return ProjectRef(uuid=project.uuid, name=project.name) if project is not None else None


class CustomerRequestService(BaseService):
    def __init__(
        self, session: AsyncSession, notifications: NotificationQueue | None = None
    ) -> None:
        super().__init__(session)
        self.repository = CustomerAccountRepository(session)
        # Заявку из кабинета создаёт тот же сервис, что и публичную
        # форму, поэтому и уведомления у них одни и те же.
        self.notifications = notifications or NullNotificationQueue()

    async def submit(
        self,
        customer: Customer,
        payload: CustomerRequestCreate,
        context: RequestContext,
        idempotency_key: str | None,
    ) -> PublicRequestCreated:
        project_id: int | None = None
        if payload.project_uuid is not None:
            project = await self.repository.get_project(customer.id, payload.project_uuid)
            if project is None:
                # Чужой проект неотличим от несуществующего.
                raise ProjectNotFoundError
            project_id = project.id

        base = PublicRequestCreate.model_validate(
            payload.model_dump(exclude={"project_uuid"}, mode="python")
        )
        return await RequestSubmissionService(self.session, self.notifications).submit(
            base,
            context,
            idempotency_key,
            customer_id=customer.id,
            project_id=project_id,
        )

    async def list_requests(
        self, customer: Customer, params: PageParams
    ) -> Page[CustomerRequestListItem]:
        rows, total = await self.repository.list_requests(customer.id, params)
        items = [
            CustomerRequestListItem(
                number=row.request.number,
                status=customer_status(row.request.status),
                source=RequestSource(row.request.source),
                currency=row.request.currency,
                total_estimate=row.request.total_estimate,
                items_count=row.items_count,
                project=project_ref(row.project),
                created_at=row.request.created_at,
                updated_at=row.request.updated_at,
            )
            for row in rows
        ]
        return Page.create(items, total, params)

    async def get_request(self, customer: Customer, number: str) -> CustomerRequestDetail:
        found = await self.repository.get_request(customer.id, number)
        if found is None:
            raise CustomerRequestNotFoundError
        request, project, region = found

        items = sorted(request.items, key=lambda item: (item.sort_order, item.id))
        # Только комментарии, адресованные клиенту. Внутренние не выходят
        # из БД в ответ ни в каком виде, даже без текста.
        comments = sorted(
            (comment for comment in request.comments if not comment.is_internal),
            key=lambda comment: (comment.created_at, comment.id),
        )
        history = sorted(request.status_history, key=lambda entry: (entry.created_at, entry.id))

        return CustomerRequestDetail(
            number=request.number,
            status=customer_status(request.status),
            source=RequestSource(request.source),
            currency=request.currency,
            total_estimate=request.total_estimate,
            items_count=len(items),
            project=project_ref(project),
            created_at=request.created_at,
            updated_at=request.updated_at,
            customer_name=request.customer_name,
            phone=request.phone,
            email=request.email,
            company=request.company,
            region=RegionRef(id=region.id, code=region.code, name=region.name) if region else None,
            comment=request.comment,
            items=[
                CustomerRequestItemRead(
                    sku=item.sku_snapshot,
                    name=item.name_snapshot,
                    unit=item.unit_snapshot,
                    quantity=item.quantity,
                    pricing_type=PricingType(item.pricing_type_snapshot),
                    unit_price=item.unit_price_snapshot,
                    line_total=item.line_total_snapshot,
                    color=item.color_code_snapshot,
                    color_name=item.color_name_snapshot,
                )
                for item in items
            ],
            comments=[
                CustomerRequestCommentRead(body=comment.body, created_at=comment.created_at)
                for comment in comments
            ],
            status_history=[
                CustomerRequestStatusRead(
                    status=customer_status(entry.to_status), created_at=entry.created_at
                )
                for entry in history
            ],
        )
