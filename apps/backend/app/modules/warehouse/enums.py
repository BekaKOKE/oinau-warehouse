"""Перечисления складской упаковки (_docs/warehouse-design.md §1.7)."""

from __future__ import annotations

from enum import StrEnum


class WarehouseDocumentStatus(StrEnum):
    """Что произошло с документом на складе.

    Хранится в warehouse_documents.status. То, что о документе знает 1С,
    сюда не входит: это отдельные метки времени на документе, из которых
    вычисляется OneCState. Два независимых вопроса — два независимых
    поля, как status и exported_at у заявки.
    """

    CREATED = "CREATED"
    PACKED = "PACKED"
    CANCELLED = "CANCELLED"


class OneCState(StrEnum):
    """Что о документе знает 1С.

    Вычисляется из статуса и меток exported_at, write_off_confirmed_at
    и cancel_exported_at. В БД не хранится: хранимое поле разошлось бы
    с метками при первом же повторном запросе 1С.
    """

    NOT_SENT = "NOT_SENT"
    WAITING_FOR_1C = "WAITING_FOR_1C"
    READ_BY_1C = "READ_BY_1C"
    WRITE_OFF_CONFIRMED = "WRITE_OFF_CONFIRMED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCEL_READ = "CANCEL_READ"


class PackageCheckStatus(StrEnum):
    """Что видит человек, отсканировавший QR-код упаковки."""

    VALID = "VALID"
    CANCELLED = "CANCELLED"
