"""Ошибки складского домена."""

from __future__ import annotations

from app.core.exceptions import ConflictError


class WarehouseCodeExistsError(ConflictError):
    code = "warehouse_code_exists"
    message = "Склад с таким кодом уже существует"


class WarehouseExternalIdExistsError(ConflictError):
    code = "external_id_exists"
    message = "Склад с таким внешним идентификатором уже существует"


class WarehouseInactiveError(ConflictError):
    code = "warehouse_inactive"
    message = "Нельзя задать остаток на отключённом складе"


class DuplicateStockEntryError(ConflictError):
    code = "duplicate_stock_entry"
    message = "Склад указан в запросе несколько раз"
