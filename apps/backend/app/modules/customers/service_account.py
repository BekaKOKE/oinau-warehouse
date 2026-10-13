"""Кабинет клиента: профиль, избранное, проекты, уведомления.

Каждый метод получает текущего клиента из зависимости и работает только
с его данными: идентификатор клиента передаётся в каждый запрос
репозитория, а не проверяется после загрузки.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, PageParams
from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.customers.audit import CUSTOMER_ACTOR, CUSTOMER_ENTITY, CustomerAuditAction
from app.modules.customers.enums import NotificationType, ProjectStatus
from app.modules.customers.exceptions import (
    CustomerRegionNotFoundError,
    FavoriteNotFoundError,
    FavoriteProductUnavailableError,
    NotificationNotFoundError,
    ProjectItemExistsError,
    ProjectItemNotFoundError,
    ProjectNotFoundError,
)
from app.modules.customers.models import (
    Customer,
    CustomerFavorite,
    CustomerNotification,
    CustomerProject,
    CustomerProjectItem,
)
from app.modules.customers.repository_account import CustomerAccountRepository
from app.modules.customers.schemas_account import (
    CustomerProfileRead,
    CustomerProfileUpdate,
    FavoriteRead,
    NotificationRead,
    ProjectCreate,
    ProjectDetail,
    ProjectItemAdd,
    ProjectItemRead,
    ProjectListItem,
    ProjectRequestRef,
    ProjectUpdate,
    RegionRef,
    UnreadCount,
)
from app.modules.customers.service_requests import customer_status
from app.modules.geo.models import Region
from app.modules.users.service import RequestContext


def _region_ref(region: Region | None) -> RegionRef | None:
    return RegionRef(id=region.id, code=region.code, name=region.name) if region else None


class CustomerAccountService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = CustomerAccountRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------ профиль
    async def get_profile(self, customer: Customer) -> CustomerProfileRead:
        region = await self.repository.get_region(customer.region_id)
        return CustomerProfileRead(
            uuid=customer.uuid,
            email=customer.email,
            contact_name=customer.contact_name,
            company_name=customer.company_name,
            phone=customer.phone,
            region=_region_ref(region),
            email_verified_at=customer.email_verified_at,
            last_login_at=customer.last_login_at,
            created_at=customer.created_at,
        )

    async def update_profile(
        self, customer: Customer, payload: CustomerProfileUpdate, context: RequestContext
    ) -> CustomerProfileRead:
        fields = payload.model_fields_set
        changed: list[str] = []

        if (
            "contact_name" in fields
            and payload.contact_name is not None
            and payload.contact_name != customer.contact_name
        ):
            customer.contact_name = payload.contact_name
            changed.append("contact_name")
        if "company_name" in fields and payload.company_name != customer.company_name:
            customer.company_name = payload.company_name
            changed.append("company_name")
        if "phone" in fields and payload.phone is not None and payload.phone != customer.phone:
            customer.phone = payload.phone
            changed.append("phone")
        if (
            "region_id" in fields
            and payload.region_id is not None
            and payload.region_id != customer.region_id
        ):
            await self._require_region(payload.region_id)
            customer.region_id = payload.region_id
            changed.append("region_id")

        if changed:
            # Только имена полей: значения — персональные данные.
            self.audit.record(
                action=CustomerAuditAction.PROFILE_UPDATED,
                entity_type=CUSTOMER_ENTITY,
                entity_id=customer.id,
                actor=CUSTOMER_ACTOR,
                changes={"fields": changed},
                ip_hash=context.ip_hash,
                request_id=context.request_id,
            )
            await self.commit()
            await self.session.refresh(customer)
        return await self.get_profile(customer)

    # ---------------------------------------------------------- избранное
    async def list_favorites(self, customer: Customer, params: PageParams) -> Page[FavoriteRead]:
        rows, total = await self.repository.list_favorites(customer.id, params)
        items = [
            FavoriteRead(
                sku=row.product.sku,
                slug=row.product.slug,
                name=row.name,
                unit=row.product.unit,
                added_at=row.favorite.created_at,
            )
            for row in rows
        ]
        return Page.create(items, total, params)

    async def add_favorite(self, customer: Customer, sku: str) -> tuple[FavoriteRead, bool]:
        """Возвращает (позиция, создана ли сейчас). Повтор — не ошибка."""
        found = await self.repository.get_visible_product(sku)
        if found is None:
            raise FavoriteProductUnavailableError(details={"sku": sku})
        # Поля товара копируются до коммита: откат при гонке сбросил бы
        # загруженный объект, и повторное чтение потребовало бы запроса.
        product_id = found.product.id
        read = {
            "sku": found.product.sku,
            "slug": found.product.slug,
            "name": found.name,
            "unit": found.product.unit,
        }

        existing = await self.repository.get_favorite(customer.id, product_id)
        created = existing is None
        if existing is None:
            existing = CustomerFavorite(customer_id=customer.id, product_id=product_id)
            self.session.add(existing)
            try:
                await self.commit()
            except IntegrityError:
                # Параллельный запрос успел добавить тот же товар.
                await self.session.rollback()
                existing = await self.repository.get_favorite(customer.id, product_id)
                created = False
                if existing is None:
                    raise
            else:
                await self.session.refresh(existing)

        return FavoriteRead(**read, added_at=existing.created_at), created

    async def remove_favorite(self, customer: Customer, sku: str) -> None:
        favorite = await self.repository.get_favorite_by_sku(customer.id, sku)
        if favorite is None:
            raise FavoriteNotFoundError
        await self.session.delete(favorite)
        await self.commit()

    # ------------------------------------------------------------ проекты
    async def list_projects(self, customer: Customer, params: PageParams) -> Page[ProjectListItem]:
        rows, total = await self.repository.list_projects(customer.id, params)
        items = [
            ProjectListItem(
                uuid=row.project.uuid,
                name=row.project.name,
                status=ProjectStatus(row.project.status),
                region=_region_ref(row.region),
                items_count=row.items_count,
                requests_count=row.requests_count,
                created_at=row.project.created_at,
                updated_at=row.project.updated_at,
            )
            for row in rows
        ]
        return Page.create(items, total, params)

    async def create_project(self, customer: Customer, payload: ProjectCreate) -> ProjectDetail:
        if payload.region_id is not None:
            await self._require_region(payload.region_id)
        project = CustomerProject(
            # uuid задаётся здесь, а не default базы: он нужен сразу после
            # коммита, без дополнительного чтения строки.
            uuid=uuid.uuid4(),
            customer_id=customer.id,
            name=payload.name,
            description=payload.description,
            region_id=payload.region_id,
            status=payload.status.value,
        )
        self.session.add(project)
        await self.commit()
        return await self.get_project(customer, project.uuid)

    async def get_project(self, customer: Customer, project_uuid: uuid.UUID) -> ProjectDetail:
        project = await self._require_project(customer, project_uuid)
        region = await self.repository.get_region(project.region_id)
        requests = await self.repository.list_project_requests(project.id, customer.id)
        visible = await self.repository.get_visible_products_by_ids(
            [item.product_id for item in project.items if item.product_id is not None]
        )

        items = []
        for item in sorted(project.items, key=lambda entry: (entry.created_at, entry.id)):
            product = visible.get(item.product_id) if item.product_id is not None else None
            items.append(
                ProjectItemRead(
                    sku=item.sku_snapshot,
                    name=item.name_snapshot,
                    slug=product.slug if product is not None else None,
                    is_available=product is not None,
                    quantity=item.quantity,
                    note=item.note,
                    added_at=item.created_at,
                )
            )

        return ProjectDetail(
            uuid=project.uuid,
            name=project.name,
            status=ProjectStatus(project.status),
            region=_region_ref(region),
            items_count=len(items),
            requests_count=len(requests),
            created_at=project.created_at,
            updated_at=project.updated_at,
            description=project.description,
            items=items,
            requests=[
                ProjectRequestRef(
                    number=request.number,
                    status=customer_status(request.status),
                    currency=request.currency,
                    total_estimate=request.total_estimate,
                    created_at=request.created_at,
                )
                for request in requests
            ],
        )

    async def update_project(
        self, customer: Customer, project_uuid: uuid.UUID, payload: ProjectUpdate
    ) -> ProjectDetail:
        project = await self._require_project(customer, project_uuid)
        fields = payload.model_fields_set
        if "name" in fields and payload.name is not None:
            project.name = payload.name
        if "description" in fields:
            project.description = payload.description
        if "region_id" in fields:
            if payload.region_id is not None:
                await self._require_region(payload.region_id)
            project.region_id = payload.region_id
        if "status" in fields and payload.status is not None:
            project.status = payload.status.value
        await self.commit()
        return await self.get_project(customer, project_uuid)

    async def delete_project(self, customer: Customer, project_uuid: uuid.UUID) -> None:
        """Мягкое удаление: заявки проекта остаются в истории клиента."""
        project = await self._require_project(customer, project_uuid)
        project.deleted_at = datetime.now(UTC)
        await self.commit()

    async def add_project_item(
        self, customer: Customer, project_uuid: uuid.UUID, payload: ProjectItemAdd
    ) -> ProjectDetail:
        project = await self._require_project(customer, project_uuid)
        found = await self.repository.get_visible_product(payload.sku)
        if found is None:
            raise FavoriteProductUnavailableError(details={"sku": payload.sku})
        if any(item.sku_snapshot == found.product.sku for item in project.items):
            raise ProjectItemExistsError(details={"sku": found.product.sku})

        self.session.add(
            CustomerProjectItem(
                project_id=project.id,
                product_id=found.product.id,
                sku_snapshot=found.product.sku,
                name_snapshot=found.name,
                quantity=payload.quantity,
                note=payload.note,
            )
        )
        # Добавление позиции — изменение проекта: сдвигаем updated_at.
        project.updated_at = datetime.now(UTC)
        try:
            await self.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ProjectItemExistsError(details={"sku": found.product.sku}) from exc
        return await self.get_project(customer, project_uuid)

    async def remove_project_item(
        self, customer: Customer, project_uuid: uuid.UUID, sku: str
    ) -> None:
        project = await self._require_project(customer, project_uuid)
        item = next((entry for entry in project.items if entry.sku_snapshot == sku), None)
        if item is None:
            raise ProjectItemNotFoundError
        project.items.remove(item)
        project.updated_at = datetime.now(UTC)
        await self.commit()

    async def _require_project(
        self, customer: Customer, project_uuid: uuid.UUID
    ) -> CustomerProject:
        project = await self.repository.get_project(customer.id, project_uuid)
        if project is None:
            raise ProjectNotFoundError
        return project

    async def _require_region(self, region_id: int) -> None:
        if await self.repository.get_active_region(region_id) is None:
            raise CustomerRegionNotFoundError(details={"region_id": region_id})

    # -------------------------------------------------------- уведомления
    async def list_notifications(
        self, customer: Customer, params: PageParams, *, unread_only: bool
    ) -> Page[NotificationRead]:
        rows, total = await self.repository.list_notifications(
            customer.id, params, unread_only=unread_only
        )
        return Page.create([self._notification(row) for row in rows], total, params)

    async def unread_count(self, customer: Customer) -> UnreadCount:
        return UnreadCount(unread=await self.repository.count_unread(customer.id))

    async def mark_read(self, customer: Customer, notification_uuid: uuid.UUID) -> NotificationRead:
        notification = await self.repository.get_notification(customer.id, notification_uuid)
        if notification is None:
            raise NotificationNotFoundError
        if notification.read_at is None:
            notification.read_at = datetime.now(UTC)
            await self.commit()
        return self._notification(notification)

    async def mark_all_read(self, customer: Customer) -> UnreadCount:
        await self.repository.mark_all_read(customer.id)
        await self.commit()
        return UnreadCount(unread=0)

    def _notification(self, notification: CustomerNotification) -> NotificationRead:
        return NotificationRead(
            uuid=notification.uuid,
            type=NotificationType(notification.type),
            title=notification.title,
            message=notification.message,
            payload=notification.payload,
            is_read=notification.read_at is not None,
            read_at=notification.read_at,
            created_at=notification.created_at,
        )
