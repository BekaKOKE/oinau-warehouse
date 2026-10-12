"""Фабрики складских документов для тестов."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.models import Warehouse
from app.modules.requests.models import Request, RequestItem
from app.modules.warehouse.models import (
    WarehouseDocument,
    WarehouseDocumentLine,
    WarehousePackage,
)
from tests.factories import make_product, make_request, make_request_item, unique


async def make_warehouse(session: AsyncSession, **kwargs: object) -> Warehouse:
    kwargs.setdefault("code", unique("wh"))
    kwargs.setdefault("name", "Основной склад")
    warehouse = Warehouse(**kwargs)  # type: ignore[arg-type]
    session.add(warehouse)
    await session.flush()
    return warehouse


async def make_document(
    session: AsyncSession,
    *,
    request: Request | None = None,
    warehouse: Warehouse | None = None,
    **kwargs: object,
) -> WarehouseDocument:
    """Сводный документ. Без статуса — его проставит БД (CREATED)."""
    if request is None:
        request = await make_request(session)
    if warehouse is None:
        warehouse = await make_warehouse(session)
    kwargs.setdefault("number", unique("WH"))
    kwargs.setdefault("package_count", 1)
    kwargs.setdefault("stock_checked_at", datetime.now(UTC))
    document = WarehouseDocument(
        request_id=request.id,
        warehouse_id=warehouse.id,
        **kwargs,  # type: ignore[arg-type]
    )
    session.add(document)
    await session.flush()
    return document


async def make_line(
    session: AsyncSession,
    document: WarehouseDocument,
    *,
    request_item: RequestItem | None = None,
    **kwargs: object,
) -> WarehouseDocumentLine:
    """Строка документа. Без позиции заявки создаёт новую с новым товаром."""
    if request_item is None:
        request = await session.get(Request, document.request_id)
        assert request is not None
        product = await make_product(session)
        request_item = await make_request_item(session, request, product)
    kwargs.setdefault("sku_snapshot", request_item.sku_snapshot)
    kwargs.setdefault("name_snapshot", request_item.name_snapshot)
    kwargs.setdefault("unit_snapshot", request_item.unit_snapshot)
    kwargs.setdefault("quantity", request_item.quantity)
    kwargs.setdefault("available_at_check", Decimal("500.000"))
    kwargs.setdefault("sort_order", 0)
    line = WarehouseDocumentLine(
        document_id=document.id,
        request_item_id=request_item.id,
        product_id=request_item.product_id,
        **kwargs,  # type: ignore[arg-type]
    )
    session.add(line)
    await session.flush()
    return line


async def make_package(
    session: AsyncSession,
    document: WarehouseDocument,
    line: WarehouseDocumentLine,
    **kwargs: object,
) -> WarehousePackage:
    kwargs.setdefault("seq", 1)
    kwargs.setdefault("quantity", Decimal("10.000"))
    package = WarehousePackage(
        document_id=document.id,
        line_id=line.id,
        **kwargs,  # type: ignore[arg-type]
    )
    session.add(package)
    await session.flush()
    return package
