"""Admin API складов и остатков.

Чтение — `catalog.read`, изменение — `stock.write`. Оба права уже
существуют в матрице ролей; новых не вводится.

MANAGER не имеет `stock.write`, поэтому менять остатки не может.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import SessionDep, require_permissions
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams
from app.modules.inventory.enums import PublicAvailability, StockSource
from app.modules.inventory.repository_admin import StockListFilters, StockListSort
from app.modules.inventory.schemas_admin import (
    AvailabilityOverrideUpdate,
    AvailabilityRead,
    ProductStockListItem,
    ProductStockRead,
    StockUpdate,
    WarehouseCreate,
    WarehouseRead,
    WarehouseUpdate,
)
from app.modules.inventory.service_admin import AdminStockService, AdminWarehouseService
from app.modules.users.models import User
from app.modules.users.permissions import CATALOG_READ, STOCK_WRITE

StockReader = Annotated[User, Depends(require_permissions(CATALOG_READ))]
StockWriter = Annotated[User, Depends(require_permissions(STOCK_WRITE))]

IdPath = Annotated[int, Path(ge=1)]

warehouses_router = APIRouter(prefix="/warehouses", tags=["admin:inventory"])
product_stock_router = APIRouter(prefix="/products", tags=["admin:inventory"])
stock_router = APIRouter(prefix="/stock", tags=["admin:inventory"])


# ---------------------------------------------------------------- склады
@warehouses_router.get("", response_model=Page[WarehouseRead], summary="Список складов")
async def list_warehouses(
    session: SessionDep,
    _: StockReader,
    is_active: bool | None = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[WarehouseRead]:
    return await AdminWarehouseService(session).list_warehouses(
        params=PageParams(page=page, page_size=page_size), is_active=is_active
    )


@warehouses_router.post(
    "",
    response_model=WarehouseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать склад",
)
async def create_warehouse(
    payload: WarehouseCreate,
    session: SessionDep,
    actor: StockWriter,
) -> WarehouseRead:
    return await AdminWarehouseService(session).create_warehouse(payload, actor)


@warehouses_router.patch("/{warehouse_id}", response_model=WarehouseRead, summary="Изменить склад")
async def update_warehouse(
    warehouse_id: IdPath,
    payload: WarehouseUpdate,
    session: SessionDep,
    actor: StockWriter,
) -> WarehouseRead:
    """Код склада неизменяем: на него завязано сопоставление с 1С.
    Склад не удаляется — отключается через `is_active`."""
    return await AdminWarehouseService(session).update_warehouse(warehouse_id, payload, actor)


# --------------------------------------------------------------- остатки
@stock_router.get("", response_model=Page[ProductStockListItem], summary="Остатки по товарам")
async def list_stock(
    session: SessionDep,
    _: StockReader,
    search: Annotated[
        str | None, Query(max_length=100, description="Артикул, название, внешний код")
    ] = None,
    availability: Annotated[
        PublicAvailability | None, Query(description="Публичный статус наличия")
    ] = None,
    warehouse_id: Annotated[
        int | None, Query(ge=1, description="Есть строка остатка на складе")
    ] = None,
    sync_source: Annotated[
        StockSource | None, Query(description="Есть строка остатка из источника")
    ] = None,
    is_active: bool | None = None,
    sort: StockListSort = StockListSort.SKU,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[ProductStockListItem]:
    """Точные остатки по складам для страницы «Склад» админки.

    Только чтение. Удалённые товары не показываются. Итоги и публичный
    статус считаются так же, как в GET /products/{id}/stock.
    """
    filters = StockListFilters(
        search=search,
        availability=availability.value if availability else None,
        warehouse_id=warehouse_id,
        sync_source=sync_source.value if sync_source else None,
        is_active=is_active,
    )
    return await AdminStockService(session).list_stock(
        filters=filters, sort=sort, params=PageParams(page=page, page_size=page_size)
    )


@product_stock_router.get(
    "/{product_id}/stock", response_model=ProductStockRead, summary="Остатки товара"
)
async def get_product_stock(
    product_id: IdPath,
    session: SessionDep,
    _: StockReader,
) -> ProductStockRead:
    """Точные количества по каждому складу — в отличие от витрины,
    которая видит только статус."""
    return await AdminStockService(session).get_product_stock(product_id)


@product_stock_router.put(
    "/{product_id}/stock", response_model=ProductStockRead, summary="Задать остатки"
)
async def set_product_stock(
    product_id: IdPath,
    payload: StockUpdate,
    session: SessionDep,
    actor: StockWriter,
) -> ProductStockRead:
    """Ручная правка остатков — временный механизм до интеграции с 1С.

    Устанавливает значения по перечисленным складам; склады, которых нет
    в теле запроса, не затрагиваются.
    """
    return await AdminStockService(session).set_stock(product_id, payload, actor)


@product_stock_router.get(
    "/{product_id}/availability",
    response_model=AvailabilityRead,
    summary="Публичный статус наличия",
)
async def get_availability(
    product_id: IdPath,
    session: SessionDep,
    _: StockReader,
) -> AvailabilityRead:
    return await AdminStockService(session).get_availability(product_id)


@product_stock_router.patch(
    "/{product_id}/availability",
    response_model=AvailabilityRead,
    summary="Переопределить показ наличия",
)
async def set_availability_override(
    product_id: IdPath,
    payload: AvailabilityOverrideUpdate,
    session: SessionDep,
    actor: StockWriter,
) -> AvailabilityRead:
    """Меняет только то, что видит посетитель. Остатки не трогаются.

    `stock_display_override: null` снимает переопределение, и статус
    снова вычисляется из остатков.
    """
    return await AdminStockService(session).set_availability_override(product_id, payload, actor)
