"""Выборки кабинета клиента.

Каждый запрос фильтрует по `customer_id` в самом SQL. Проверка владения
«после загрузки» не используется нигде: забытая проверка в сервисе
не должна превращаться в доступ к чужим данным.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, and_, func, select, update
from sqlalchemy.orm import aliased, selectinload

from app.core.config import settings
from app.core.pagination import PageParams
from app.modules.catalog.models import Product, ProductTranslation
from app.modules.catalog.visibility import public_visibility_clause
from app.modules.customers.models import (
    CustomerFavorite,
    CustomerNotification,
    CustomerProject,
    CustomerProjectItem,
)
from app.modules.geo.models import Region
from app.modules.requests.models import Request, RequestItem


@dataclass(frozen=True)
class VisibleProduct:
    product: Product
    name: str


@dataclass(frozen=True)
class FavoriteRow:
    favorite: CustomerFavorite
    product: Product
    name: str


@dataclass(frozen=True)
class RequestRow:
    request: Request
    items_count: int
    project: CustomerProject | None


@dataclass(frozen=True)
class ProjectRow:
    project: CustomerProject
    region: Region | None
    items_count: int
    requests_count: int


def _product_name_join() -> tuple[Any, Any]:
    translation = aliased(ProductTranslation)
    condition = and_(
        translation.product_id == Product.id,
        translation.locale == settings.DEFAULT_LOCALE,
    )
    return translation, condition


class CustomerAccountRepository:
    def __init__(self, session: Any) -> None:
        self.session = session

    # ------------------------------------------------------------ каталог
    async def get_visible_product(self, sku: str) -> VisibleProduct | None:
        """Товар по артикулу — только если он виден на витрине."""
        translation, condition = _product_name_join()
        query = (
            select(Product, translation.name)
            .outerjoin(translation, condition)
            .where(Product.sku == sku, public_visibility_clause())
        )
        row = (await self.session.execute(query)).first()
        if row is None:
            return None
        product, name = row
        return VisibleProduct(product=product, name=name or product.sku)

    async def get_region(self, region_id: int | None) -> Region | None:
        if region_id is None:
            return None
        return cast("Region | None", await self.session.get(Region, region_id))

    async def get_active_region(self, region_id: int) -> Region | None:
        query = select(Region).where(Region.id == region_id, Region.is_active.is_(True))
        return cast("Region | None", (await self.session.execute(query)).scalars().first())

    # ---------------------------------------------------------- избранное
    async def list_favorites(
        self, customer_id: int, params: PageParams
    ) -> tuple[list[FavoriteRow], int]:
        """Только видимые товары. Строки невидимых остаются в БД и вернутся
        в выдачу, когда товар снова опубликуют."""
        translation, condition = _product_name_join()
        base = (
            select(CustomerFavorite, Product, translation.name)
            .join(Product, Product.id == CustomerFavorite.product_id)
            .outerjoin(translation, condition)
            .where(CustomerFavorite.customer_id == customer_id, public_visibility_clause())
        )
        total = (
            await self.session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        rows = (
            await self.session.execute(
                base.order_by(CustomerFavorite.created_at.desc(), CustomerFavorite.id.desc())
                .limit(params.limit)
                .offset(params.offset)
            )
        ).all()
        return (
            [
                FavoriteRow(favorite=favorite, product=product, name=name or product.sku)
                for favorite, product, name in rows
            ],
            int(total),
        )

    async def get_favorite(self, customer_id: int, product_id: int) -> CustomerFavorite | None:
        query = select(CustomerFavorite).where(
            CustomerFavorite.customer_id == customer_id,
            CustomerFavorite.product_id == product_id,
        )
        return cast(
            "CustomerFavorite | None", (await self.session.execute(query)).scalars().first()
        )

    async def get_favorite_by_sku(self, customer_id: int, sku: str) -> CustomerFavorite | None:
        """Удаление по артикулу работает и для снятого с публикации товара:
        клиент должен иметь возможность очистить избранное."""
        query = (
            select(CustomerFavorite)
            .join(Product, Product.id == CustomerFavorite.product_id)
            .where(CustomerFavorite.customer_id == customer_id, Product.sku == sku)
        )
        return cast(
            "CustomerFavorite | None", (await self.session.execute(query)).scalars().first()
        )

    # ------------------------------------------------------------- заявки
    def _items_count(self) -> Any:
        return (
            select(func.count(RequestItem.id))
            .where(RequestItem.request_id == Request.id)
            .correlate(Request)
            .scalar_subquery()
        )

    def _live_project(self) -> Any:
        return and_(
            CustomerProject.id == Request.project_id,
            CustomerProject.deleted_at.is_(None),
        )

    async def list_requests(
        self, customer_id: int, params: PageParams
    ) -> tuple[list[RequestRow], int]:
        where = and_(Request.customer_id == customer_id, Request.deleted_at.is_(None))
        total = (
            await self.session.execute(select(func.count(Request.id)).where(where))
        ).scalar_one()
        query = (
            select(Request, self._items_count(), CustomerProject)
            .outerjoin(CustomerProject, self._live_project())
            .where(where)
            .order_by(Request.created_at.desc(), Request.id.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
        rows = (await self.session.execute(query)).all()
        return (
            [
                RequestRow(request=request, items_count=int(count), project=project)
                for request, count, project in rows
            ],
            int(total),
        )

    async def get_request(
        self, customer_id: int, number: str
    ) -> tuple[Request, CustomerProject | None, Region | None] | None:
        query = (
            select(Request, CustomerProject, Region)
            .outerjoin(CustomerProject, self._live_project())
            .outerjoin(Region, Region.id == Request.region_id)
            .where(
                Request.customer_id == customer_id,
                Request.number == number,
                Request.deleted_at.is_(None),
            )
            .options(
                selectinload(Request.items),
                selectinload(Request.comments),
                selectinload(Request.status_history),
            )
        )
        row = (await self.session.execute(query)).first()
        if row is None:
            return None
        request, project, region = row
        return request, project, region

    async def list_project_requests(self, project_id: int, customer_id: int) -> Sequence[Request]:
        query = (
            select(Request)
            .where(
                Request.project_id == project_id,
                Request.customer_id == customer_id,
                Request.deleted_at.is_(None),
            )
            .order_by(Request.created_at.desc(), Request.id.desc())
        )
        return cast("Sequence[Request]", (await self.session.execute(query)).scalars().all())

    # ------------------------------------------------------------ проекты
    def _project_counts(self) -> tuple[Any, Any]:
        items = (
            select(func.count(CustomerProjectItem.id))
            .where(CustomerProjectItem.project_id == CustomerProject.id)
            .correlate(CustomerProject)
            .scalar_subquery()
        )
        requests = (
            select(func.count(Request.id))
            .where(
                Request.project_id == CustomerProject.id,
                Request.customer_id == CustomerProject.customer_id,
                Request.deleted_at.is_(None),
            )
            .correlate(CustomerProject)
            .scalar_subquery()
        )
        return items, requests

    async def list_projects(
        self, customer_id: int, params: PageParams
    ) -> tuple[list[ProjectRow], int]:
        where = and_(
            CustomerProject.customer_id == customer_id, CustomerProject.deleted_at.is_(None)
        )
        total = (
            await self.session.execute(select(func.count(CustomerProject.id)).where(where))
        ).scalar_one()
        items, requests = self._project_counts()
        query = (
            select(CustomerProject, Region, items, requests)
            .outerjoin(Region, Region.id == CustomerProject.region_id)
            .where(where)
            .order_by(CustomerProject.created_at.desc(), CustomerProject.id.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
        rows = (await self.session.execute(query)).all()
        return (
            [
                ProjectRow(
                    project=project,
                    region=region,
                    items_count=int(items_count),
                    requests_count=int(requests_count),
                )
                for project, region, items_count, requests_count in rows
            ],
            int(total),
        )

    async def get_project(self, customer_id: int, project_uuid: Any) -> CustomerProject | None:
        query = (
            select(CustomerProject)
            .where(
                CustomerProject.customer_id == customer_id,
                CustomerProject.uuid == project_uuid,
                CustomerProject.deleted_at.is_(None),
            )
            .options(selectinload(CustomerProject.items))
            .execution_options(populate_existing=True)
        )
        return cast("CustomerProject | None", (await self.session.execute(query)).scalars().first())

    async def get_visible_products_by_ids(self, product_ids: Sequence[int]) -> dict[int, Product]:
        if not product_ids:
            return {}
        query = select(Product).where(Product.id.in_(product_ids), public_visibility_clause())
        return {product.id: product for product in (await self.session.execute(query)).scalars()}

    # -------------------------------------------------------- уведомления
    async def list_notifications(
        self, customer_id: int, params: PageParams, *, unread_only: bool
    ) -> tuple[Sequence[CustomerNotification], int]:
        conditions = [CustomerNotification.customer_id == customer_id]
        if unread_only:
            conditions.append(CustomerNotification.read_at.is_(None))
        total = (
            await self.session.execute(
                select(func.count(CustomerNotification.id)).where(*conditions)
            )
        ).scalar_one()
        query = (
            select(CustomerNotification)
            .where(*conditions)
            .order_by(CustomerNotification.created_at.desc(), CustomerNotification.id.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
        return (await self.session.execute(query)).scalars().all(), int(total)

    async def count_unread(self, customer_id: int) -> int:
        query = select(func.count(CustomerNotification.id)).where(
            CustomerNotification.customer_id == customer_id,
            CustomerNotification.read_at.is_(None),
        )
        return int((await self.session.execute(query)).scalar_one())

    async def get_notification(
        self, customer_id: int, notification_uuid: Any
    ) -> CustomerNotification | None:
        query = select(CustomerNotification).where(
            CustomerNotification.customer_id == customer_id,
            CustomerNotification.uuid == notification_uuid,
        )
        return cast(
            "CustomerNotification | None", (await self.session.execute(query)).scalars().first()
        )

    async def mark_all_read(self, customer_id: int) -> int:
        result = await self.session.execute(
            update(CustomerNotification)
            .where(
                CustomerNotification.customer_id == customer_id,
                CustomerNotification.read_at.is_(None),
            )
            .values(read_at=datetime.now(UTC))
        )
        return cast("CursorResult[Any]", result).rowcount
