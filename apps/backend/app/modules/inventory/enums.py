"""Перечисления складского учёта."""

from __future__ import annotations

from enum import StrEnum


class StockDisplayOverride(StrEnum):
    """Ручное переопределение публичного статуса наличия."""

    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    ON_REQUEST = "ON_REQUEST"


class PublicAvailability(StrEnum):
    """Что видит посетитель сайта.

    Вычисляется на лету из stocks, в БД не хранится. Хранимое поле
    рассинхронизировалось бы с остатком при первом же обновлении из 1С.
    """

    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    ON_REQUEST = "ON_REQUEST"


class StockSource(StrEnum):
    """Кто последним записал остаток."""

    MANUAL = "manual"
    EXCEL = "excel"
    ONE_C = "1c"
