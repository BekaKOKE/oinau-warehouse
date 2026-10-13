"""Запросы Admin API складов и остатков."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import aliased, joinedload

from app.core.config import settings
from app.core.pagination import PageParams
from app.core.repository import BaseRepository
from app.modules.catalog.models import (
    Category,
    Product,
    ProductCategory,
    ProductTranslation,
)
from app.modules.geo.models import Region
from app.modules.inventory.availability import availability_expression
from app.modules.inventory.models import Stock, Warehouse


class StockListSort(StrEnum):
    """Белый список сортировок списка остатков."""

    SKU = "sku"
    NAME = "name"
    AVAILABLE_ASC = "available_asc"
    AVAILABLE_DESC = "available_desc"
    UPDATED = "updated"


@dataclass(frozen=True)
class StockListFilters:
    search: str | None = None
    availability: str | None = None
    warehouse_id: int | None = None
    sync_source: str | None = None
    is_active: bool | None = None


@dataclass(frozen=True)
class StockListRow:
    product: Product
    name: str | None
    stock_updated_at: datetime | None


def stock_totals_subquery() -> Any:
    """Итоги остатков по товару одним подзапросом.

    Количество и резерв суммируются только по активным складам — ровно
    так их считает `AdminStockService._to_read` и публичный расчёт
    наличия. Время последнего изменения берётся по всем строкам:
    правка на отключённом складе — тоже правка.
    """
    active = Warehouse.is_active.is_(True)
    return (
        select(
            Stock.product_id.label("product_id"),
            func.sum(case((active, Stock.quantity), else_=0)).label("total_quantity"),
            func.sum(case((active, Stock.reserved), else_=0)).label("total_reserved"),
            func.max(Stock.updated_at).label("updated_at"),
        )
        .join(Warehouse, Warehouse.id == Stock.warehouse_id)
        .group_by(Stock.product_id)
        .subquery("stock_totals")
    )


def available_quantity(totals: Any) -> Any:
    """Свободный остаток из подзапроса итогов: товар без строк — ноль."""
    return func.coalesce(totals.c.total_quantity, 0) - func.coalesce(totals.c.total_reserved, 0)


class AdminWarehouseRepository(BaseRepository[Warehouse]):
    model = Warehouse

    def _query(self) -> Select[tuple[Warehouse]]:
        # populate_existing: сервис читает склад, меняет его, коммитит
        # и читает снова в той же сессии.
        return (
            select(Warehouse)
            .options(joinedload(Warehouse.region))
            .execution_options(populate_existing=True)
        )

    async def get_by_id(self, warehouse_id: int) -> Warehouse | None:
        query = self._query().where(Warehouse.id == warehouse_id)
        return (await self.session.execute(query)).scalars().first()

    async def get_by_code(self, code: str) -> Warehouse | None:
        query = self._query().where(Warehouse.code == code)
        return (await self.session.execute(query)).scalars().first()

    async def list_warehouses(
        self, *, params: PageParams, is_active: bool | None = None
    ) -> tuple[Sequence[Warehouse], int]:
        query = self._query()
        if is_active is not None:
            query = query.where(Warehouse.is_active.is_(is_active))

        total = (
            await self.session.execute(
                select(func.count()).select_from(query.with_only_columns(Warehouse.id).subquery())
            )
        ).scalar_one()

        rows = (
            await self.session.execute(
                query.order_by(Warehouse.code).limit(params.limit).offset(params.offset)
            )
        ).scalars()
        return rows.all(), total


class AdminStockRepository(BaseRepository[Stock]):
    model = Stock

    async def get_product(self, product_id: int) -> Product | None:
        """Лёгкая выборка товара.

        Репозиторий каталога тянет переводы, категории и характеристики —
        для работы с остатками всё это не нужно.
        """
        query = select(Product).where(Product.id == product_id)
        return (await self.session.execute(query)).scalars().first()

    async def lock_product(self, product_id: int) -> int | None:
        """Блокирует строку товара на время транзакции.

        Правка остатков — это upsert нескольких строк. Блокировка
        сериализует конкурентные изменения остатков одного товара
        и заодно закрывает гонку вставки по составному ключу
        (product_id, warehouse_id).
        """
        query = select(Product.id).where(Product.id == product_id).with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def list_product_stock(self, product_id: int) -> Sequence[tuple[Warehouse, Stock | None]]:
        """Склады и остатки товара одним запросом.

        LEFT JOIN от складов к остаткам: активный склад без строки
        остатка показывается с нулём, а не пропадает из ответа.
        Дополнительное условие OR оставляет в выдаче и отключённые
        склады, если на них ещё лежит товар — иначе остаток исчез бы
        из поля зрения администратора.
        """
        query = (
            select(Warehouse, Stock)
            .outerjoin(
                Stock,
                and_(Stock.warehouse_id == Warehouse.id, Stock.product_id == product_id),
            )
            .where(or_(Warehouse.is_active.is_(True), Stock.product_id.isnot(None)))
            .order_by(Warehouse.code)
        )
        return [(row[0], row[1]) for row in (await self.session.execute(query)).all()]

    async def get_entry(self, product_id: int, warehouse_id: int) -> Stock | None:
        query = select(Stock).where(
            Stock.product_id == product_id, Stock.warehouse_id == warehouse_id
        )
        return (await self.session.execute(query)).scalars().first()

    async def get_warehouses_by_ids(self, warehouse_ids: Sequence[int]) -> dict[int, Warehouse]:
        if not warehouse_ids:
            return {}
        query = select(Warehouse).where(Warehouse.id.in_(warehouse_ids))
        return {item.id: item for item in (await self.session.execute(query)).scalars().all()}

    # ------------------------------------------------------ список остатков
    async def list_stock_products(
        self, *, filters: StockListFilters, sort: StockListSort, params: PageParams
    ) -> tuple[list[StockListRow], int]:
        """Страница товаров для списка остатков.

        Фильтр по наличию и сортировка по свободному остатку считаются
        в базе через подзапрос итогов — иначе пришлось бы выгружать весь
        каталог, чтобы отдать 24 строки. Удалённые товары не показываются.
        """
        translation = aliased(ProductTranslation)
        totals = stock_totals_subquery()
        available = available_quantity(totals)

        query = (
            select(Product, translation.name, totals.c.updated_at)
            .outerjoin(
                translation,
                and_(
                    translation.product_id == Product.id,
                    translation.locale == settings.DEFAULT_LOCALE,
                ),
            )
            .outerjoin(totals, totals.c.product_id == Product.id)
            .where(Product.deleted_at.is_(None))
        )
        if filters.is_active is not None:
            query = query.where(Product.is_active.is_(filters.is_active))
        if filters.availability is not None:
            query = query.where(
                availability_expression(
                    pricing_type=Product.pricing_type,
                    stock_display_override=Product.stock_display_override,
                    available_quantity=available,
                )
                == filters.availability
            )
        if filters.warehouse_id is not None:
            query = query.where(
                Product.id.in_(
                    select(Stock.product_id).where(Stock.warehouse_id == filters.warehouse_id)
                )
            )
        if filters.sync_source is not None:
            query = query.where(
                Product.id.in_(
                    select(Stock.product_id).where(Stock.sync_source == filters.sync_source)
                )
            )
        if filters.search and filters.search.strip():
            pattern = f"%{filters.search.strip()}%"
            query = query.where(
                or_(
                    Product.sku.ilike(pattern),
                    Product.external_id.ilike(pattern),
                    translation.name.ilike(pattern),
                )
            )

        total = (
            await self.session.execute(
                select(func.count()).select_from(query.with_only_columns(Product.id).subquery())
            )
        ).scalar_one()

        order_options: dict[StockListSort, list[Any]] = {
            StockListSort.SKU: [Product.sku.asc()],
            StockListSort.NAME: [translation.name.asc().nullslast()],
            StockListSort.AVAILABLE_ASC: [available.asc()],
            StockListSort.AVAILABLE_DESC: [available.desc()],
            StockListSort.UPDATED: [totals.c.updated_at.desc().nullslast()],
        }
        rows = await self.session.execute(
            query.order_by(*order_options[sort], Product.id.asc())
            .limit(params.limit)
            .offset(params.offset)
        )
        return [
            StockListRow(product=row[0], name=row[1], stock_updated_at=row[2]) for row in rows.all()
        ], total

    async def list_all_warehouses(self) -> Sequence[Warehouse]:
        """Все склады: их единицы, и нужны они целиком для раскладки строк."""
        query = select(Warehouse).order_by(Warehouse.code)
        return (await self.session.execute(query)).scalars().all()

    async def list_primary_categories(
        self, product_ids: Sequence[int]
    ) -> dict[int, ProductCategory]:
        """Основные категории страницы товаров — одним запросом
        (переводы категорий подгружаются вторым, selectin)."""
        if not product_ids:
            return {}
        query = (
            select(ProductCategory)
            .where(
                ProductCategory.product_id.in_(product_ids),
                ProductCategory.is_primary.is_(True),
            )
            .options(joinedload(ProductCategory.category).selectinload(Category.translations))
        )
        links = (await self.session.execute(query)).scalars().unique().all()
        return {link.product_id: link for link in links}

    async def list_stock_entries(self, product_ids: Sequence[int]) -> Sequence[Stock]:
        """Строки остатков страницы товаров — одним запросом."""
        if not product_ids:
            return []
        query = select(Stock).where(Stock.product_id.in_(product_ids))
        return (await self.session.execute(query)).scalars().all()


__all__ = ["AdminStockRepository", "AdminWarehouseRepository", "Region"]
