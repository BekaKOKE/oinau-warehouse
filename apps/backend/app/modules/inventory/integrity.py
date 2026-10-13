"""Соответствие ограничений складских таблиц доменным ошибкам.

Имена взяты из фактической схемы (проверено запросом к pg_constraint).
Используется общий механизм из app/core/integrity.py.
"""

from __future__ import annotations

from app.core.exceptions import AppError
from app.modules.inventory.exceptions import (
    DuplicateStockEntryError,
    WarehouseCodeExistsError,
    WarehouseExternalIdExistsError,
)

INVENTORY_CONSTRAINT_ERRORS: dict[str, type[AppError]] = {
    "uq_warehouses_code": WarehouseCodeExistsError,
    "uq_warehouses_external_id": WarehouseExternalIdExistsError,
    # Составной первичный ключ (product_id, warehouse_id): нарушается,
    # если два параллельных запроса вставляют остаток по одной паре.
    "pk_stocks": DuplicateStockEntryError,
}
