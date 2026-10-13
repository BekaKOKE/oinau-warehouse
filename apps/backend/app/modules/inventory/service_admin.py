"""Бизнес-правила Admin API складов и остатков.

Три вещи, которые сознательно разделены и не смешиваются:

1. **Фактические остатки** (`stocks.quantity` / `reserved`) — числа со
   склада. Сейчас правятся вручную, в будущем придут из 1С.
2. **Ручное переопределение показа** (`products.stock_display_override`)
   — то, что видит посетитель, независимо от чисел. Меняется отдельным
   эндпоинтом и на остаток не влияет.
3. **Публичный статус** — вычисляется существующим resolver'ом и нигде
   не хранится.

Смешение первого и второго — классическая причина, по которой «в наличии»
на витрине перестаёт соответствовать складу.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.integrity import guard_unique
from app.core.pagination import Page, PageParams
from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.catalog.models import Product, ProductCategory
from app.modules.catalog.mutability import ensure_mutable
from app.modules.catalog.schemas_admin_products import ProductCategoryRead
from app.modules.inventory.availability import resolve_availability
from app.modules.inventory.enums import StockSource
from app.modules.inventory.exceptions import WarehouseInactiveError
from app.modules.inventory.integrity import INVENTORY_CONSTRAINT_ERRORS
from app.modules.inventory.models import Stock, Warehouse
from app.modules.inventory.repository_admin import (
    AdminStockRepository,
    AdminWarehouseRepository,
    StockListFilters,
    StockListSort,
)
from app.modules.inventory.schemas_admin import (
    AvailabilityOverrideUpdate,
    AvailabilityRead,
    ProductStockListItem,
    ProductStockRead,
    StockEntryRead,
    StockUpdate,
    WarehouseCreate,
    WarehouseRead,
    WarehouseUpdate,
)
from app.modules.users.models import User

# Количество в аудите всегда приводится к точности колонки NUMERIC(14,3).
# Иначе «до» приходит из базы как "10.000", а «после» — из тела запроса
# как "10", и одинаковые значения выглядят изменением.
QUANTITY_EXPONENT = Decimal("0.001")


def _qty(value: Decimal) -> str:
    return str(value.quantize(QUANTITY_EXPONENT))


def _category_ref(link: ProductCategory | None) -> ProductCategoryRead | None:
    if link is None:
        return None
    category = link.category
    by_locale = {item.locale: item for item in category.translations}
    translation = by_locale.get(settings.DEFAULT_LOCALE) or next(iter(by_locale.values()), None)
    return ProductCategoryRead(
        category_id=category.id,
        slug=category.slug,
        name=translation.name if translation else category.slug,
        is_primary=True,
        sort_order=link.sort_order,
        is_active=category.is_active,
    )


WAREHOUSE_ENTITY = "warehouse"
STOCK_ENTITY = "product_stock"
AVAILABILITY_ENTITY = "product_availability"


class InventoryAuditAction:
    WAREHOUSE_CREATED = "inventory.warehouse_created"
    WAREHOUSE_UPDATED = "inventory.warehouse_updated"
    STOCK_UPDATED = "inventory.stock_updated"
    OVERRIDE_UPDATED = "inventory.availability_override_updated"


class AdminWarehouseService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = AdminWarehouseRepository(session)
        self.audit = AuditService(session)

    async def list_warehouses(
        self, *, params: PageParams, is_active: bool | None = None
    ) -> Page[WarehouseRead]:
        rows, total = await self.repository.list_warehouses(params=params, is_active=is_active)
        return Page.create([self._to_read(item) for item in rows], total, params)

    @guard_unique(INVENTORY_CONSTRAINT_ERRORS)
    async def create_warehouse(self, payload: WarehouseCreate, actor: User) -> WarehouseRead:
        warehouse = Warehouse(
            code=payload.code,
            name=payload.name,
            region_id=payload.region_id,
            is_active=payload.is_active,
            external_id=payload.external_id,
        )
        self.session.add(warehouse)
        await self.session.flush()

        self.audit.record(
            action=InventoryAuditAction.WAREHOUSE_CREATED,
            entity_type=WAREHOUSE_ENTITY,
            entity_id=warehouse.id,
            user_id=actor.id,
            changes={"code": {"old": None, "new": warehouse.code}},
        )
        await self.commit()
        return self._to_read(await self._require(warehouse.id))

    @guard_unique(INVENTORY_CONSTRAINT_ERRORS)
    async def update_warehouse(
        self, warehouse_id: int, payload: WarehouseUpdate, actor: User
    ) -> WarehouseRead:
        warehouse = await self._require(warehouse_id)
        fields = payload.model_dump(exclude_unset=True)
        changes: dict[str, Any] = {}

        for field in ("name", "region_id", "is_active", "external_id"):
            if field in fields and fields[field] != getattr(warehouse, field):
                changes[field] = {"old": getattr(warehouse, field), "new": fields[field]}
                setattr(warehouse, field, fields[field])

        await self.session.flush()
        if changes:
            self.audit.record(
                action=InventoryAuditAction.WAREHOUSE_UPDATED,
                entity_type=WAREHOUSE_ENTITY,
                entity_id=warehouse.id,
                user_id=actor.id,
                changes=changes,
            )
        await self.commit()
        return self._to_read(await self._require(warehouse.id))

    async def _require(self, warehouse_id: int) -> Warehouse:
        warehouse = await self.repository.get_by_id(warehouse_id)
        if warehouse is None:
            raise NotFoundError("Склад не найден")
        return warehouse

    def _to_read(self, warehouse: Warehouse) -> WarehouseRead:
        region = warehouse.region
        return WarehouseRead(
            id=warehouse.id,
            code=warehouse.code,
            name=warehouse.name,
            region_id=warehouse.region_id,
            region_code=region.code if region else None,
            region_name=region.name if region else None,
            is_active=warehouse.is_active,
            external_id=warehouse.external_id,
            sync_source=warehouse.sync_source,
        )


class AdminStockService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = AdminStockRepository(session)
        self.audit = AuditService(session)

    # -------------------------------------------------------------- чтение
    async def get_product_stock(self, product_id: int) -> ProductStockRead:
        product = await self._require_product(product_id)
        rows = await self.repository.list_product_stock(product.id)
        return self._to_read(product, rows)

    async def list_stock(
        self, *, filters: StockListFilters, sort: StockListSort, params: PageParams
    ) -> Page[ProductStockListItem]:
        """Остатки страницы товаров.

        Число запросов не зависит от размера страницы: товары, все склады
        и строки остатков страницы — по одному запросу. Раскладка строк
        по складам и итоги считаются тем же `_to_read`, что и карточка
        остатков одного товара, поэтому список и карточка не расходятся.
        Только чтение: источником истины по остаткам остаётся ручная
        правка, а после интеграции — 1С.
        """
        rows, total = await self.repository.list_stock_products(
            filters=filters, sort=sort, params=params
        )
        warehouses = await self.repository.list_all_warehouses()
        product_ids = [row.product.id for row in rows]
        entries = await self.repository.list_stock_entries(product_ids)
        primary = await self.repository.list_primary_categories(product_ids)
        by_key = {(entry.product_id, entry.warehouse_id): entry for entry in entries}

        items: list[ProductStockListItem] = []
        for row in rows:
            product = row.product
            product_rows = [
                (warehouse, by_key.get((product.id, warehouse.id))) for warehouse in warehouses
            ]
            # Как в карточке товара: активный склад виден и с нулём,
            # отключённый — только если на нём ещё что-то числится.
            product_rows = [
                (warehouse, stock)
                for warehouse, stock in product_rows
                if warehouse.is_active or stock is not None
            ]
            stock = self._to_read(product, product_rows)
            items.append(
                ProductStockListItem(
                    **stock.model_dump(),
                    name=row.name,
                    status=product.status,
                    is_active=product.is_active,
                    pricing_type=product.pricing_type,
                    external_id=product.external_id,
                    primary_category=_category_ref(primary.get(product.id)),
                    stock_updated_at=row.stock_updated_at,
                )
            )
        return Page.create(items, total, params)

    async def get_availability(self, product_id: int) -> AvailabilityRead:
        stock = await self.get_product_stock(product_id)
        return AvailabilityRead(
            product_id=stock.product_id,
            sku=stock.sku,
            stock_display_override=stock.stock_display_override,
            public_availability=stock.public_availability,
            total_available=stock.total_available,
        )

    # -------------------------------------------------------------- запись
    @guard_unique(INVENTORY_CONSTRAINT_ERRORS)
    async def set_stock(
        self, product_id: int, payload: StockUpdate, actor: User
    ) -> ProductStockRead:
        """Устанавливает остатки по перечисленным складам.

        Семантика — upsert по указанным складам, а НЕ замена всего
        набора: склады, отсутствующие в теле запроса, не трогаются.
        Полная замена была бы опасна — частичный запрос молча обнулил бы
        остатки на других складах, а с приходом 1С обновления как раз
        и станут приходить по одному складу за раз.

        Операция идемпотентна: повторная отправка того же тела даёт тот
        же результат.
        """
        product = ensure_mutable(await self._require_product(product_id))

        # Сериализует конкурентные правки остатков этого товара
        # и закрывает гонку вставки по паре (product_id, warehouse_id).
        await self.repository.lock_product(product.id)

        warehouses = await self.repository.get_warehouses_by_ids(
            [item.warehouse_id for item in payload.items]
        )
        changes: dict[str, Any] = {}

        for item in payload.items:
            warehouse = warehouses.get(item.warehouse_id)
            if warehouse is None:
                raise NotFoundError(f"Склад {item.warehouse_id} не найден")
            if not warehouse.is_active:
                # Иначе товар «лежал» бы на складе, который не участвует
                # в расчёте наличия, и остаток был бы невидим.
                raise WarehouseInactiveError(details={"warehouse_id": warehouse.id})

            entry = await self.repository.get_entry(product.id, warehouse.id)
            if entry is None:
                entry = Stock(
                    product_id=product.id,
                    warehouse_id=warehouse.id,
                    quantity=item.quantity,
                    reserved=item.reserved,
                    sync_source=StockSource.MANUAL.value,
                )
                self.session.add(entry)
                changes[warehouse.code] = {
                    "old": None,
                    "new": {"quantity": _qty(item.quantity), "reserved": _qty(item.reserved)},
                }
            else:
                changes[warehouse.code] = {
                    "old": {"quantity": _qty(entry.quantity), "reserved": _qty(entry.reserved)},
                    "new": {"quantity": _qty(item.quantity), "reserved": _qty(item.reserved)},
                }
                entry.quantity = item.quantity
                entry.reserved = item.reserved
                # Ручная правка перебивает источник: иначе строка,
                # однажды пришедшая из 1С, навсегда осталась бы помечена
                # как «из 1С», хотя её поправили руками.
                entry.sync_source = StockSource.MANUAL.value
                entry.updated_at = datetime.now(UTC)

        await self.session.flush()
        self.audit.record(
            action=InventoryAuditAction.STOCK_UPDATED,
            entity_type=STOCK_ENTITY,
            entity_id=product.id,
            user_id=actor.id,
            changes=changes,
        )
        await self.commit()
        return await self.get_product_stock(product.id)

    async def set_availability_override(
        self, product_id: int, payload: AvailabilityOverrideUpdate, actor: User
    ) -> AvailabilityRead:
        """Меняет только показ наличия. Фактические остатки не трогаются.

        `null` снимает переопределение, после чего статус снова
        вычисляется из остатков.
        """
        product = ensure_mutable(await self._require_product(product_id))

        new_value = (
            payload.stock_display_override.value
            if payload.stock_display_override is not None
            else None
        )
        old_value = product.stock_display_override

        if new_value != old_value:
            product.stock_display_override = new_value
            await self.session.flush()
            self.audit.record(
                action=InventoryAuditAction.OVERRIDE_UPDATED,
                entity_type=AVAILABILITY_ENTITY,
                entity_id=product.id,
                user_id=actor.id,
                changes={"stock_display_override": {"old": old_value, "new": new_value}},
            )
        await self.commit()
        return await self.get_availability(product.id)

    # ---------------------------------------------------------- внутреннее
    async def _require_product(self, product_id: int) -> Product:
        product = await self.repository.get_product(product_id)
        if product is None:
            raise NotFoundError("Товар не найден")
        return product

    def _to_read(
        self, product: Product, rows: list[tuple[Warehouse, Stock | None]] | Any
    ) -> ProductStockRead:
        entries: list[StockEntryRead] = []
        total_quantity = Decimal(0)
        total_reserved = Decimal(0)

        for warehouse, stock in rows:
            quantity = stock.quantity if stock else Decimal(0)
            reserved = stock.reserved if stock else Decimal(0)
            entries.append(
                StockEntryRead(
                    warehouse_id=warehouse.id,
                    warehouse_code=warehouse.code,
                    warehouse_name=warehouse.name,
                    warehouse_is_active=warehouse.is_active,
                    quantity=quantity,
                    reserved=reserved,
                    available=quantity - reserved,
                    sync_source=stock.sync_source if stock else None,
                    synced_at=stock.synced_at if stock else None,
                    external_id=stock.external_id if stock else None,
                    updated_at=stock.updated_at if stock else None,
                )
            )
            # Отключённый склад в итоги не входит — ровно так же его
            # игнорирует публичный расчёт наличия.
            if warehouse.is_active:
                total_quantity += quantity
                total_reserved += reserved

        total_available = total_quantity - total_reserved
        return ProductStockRead(
            product_id=product.id,
            sku=product.sku,
            unit=product.unit,
            entries=entries,
            total_quantity=total_quantity,
            total_reserved=total_reserved,
            total_available=total_available,
            # Тот же resolver, что использует витрина: дублировать
            # правило нельзя, иначе админка начнёт показывать не то,
            # что видит покупатель.
            public_availability=resolve_availability(
                pricing_type=product.pricing_type,
                stock_display_override=product.stock_display_override,
                available_quantity=total_available,
            ),
            stock_display_override=product.stock_display_override,
        )
