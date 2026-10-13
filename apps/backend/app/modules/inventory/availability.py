"""Публичный статус наличия.

Точный остаток наружу не отдаётся ни при каких условиях: по нему
конкурент оценивает обороты и объёмы закупок. Публичный API знает
только три состояния.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, case, func, literal

from app.modules.inventory.enums import PublicAvailability
from app.modules.pricing.enums import PricingType


def resolve_availability(
    *,
    pricing_type: str,
    stock_display_override: str | None,
    available_quantity: Decimal | None,
) -> PublicAvailability:
    """Вычисляет статус наличия. В БД он не хранится.

    Приоритет:
      1. Ручное переопределение из админки — менеджер знает то, чего
         не знает остаток (ожидается поставка, позиция снята с продажи).
      2. Товар «по запросу»: цену и сроки определяет менеджер, поэтому
         показывать «в наличии» рядом с отсутствующей ценой бессмысленно.
      3. Свободный остаток по активным складам.
    """
    if stock_display_override is not None:
        return PublicAvailability(stock_display_override)

    if pricing_type == PricingType.ON_REQUEST.value:
        return PublicAvailability.ON_REQUEST

    if available_quantity is not None and available_quantity > 0:
        return PublicAvailability.IN_STOCK

    return PublicAvailability.OUT_OF_STOCK


def availability_expression(
    *,
    pricing_type: Any,
    stock_display_override: Any,
    available_quantity: Any,
) -> ColumnElement[str]:
    """То же правило, что `resolve_availability`, в виде SQL-выражения.

    Нужно там, где по статусу надо фильтровать или считать в базе:
    сводка каталога и список остатков админки. Вычислять статус
    построчно в Python ради счётчика значило бы выгружать весь каталог.
    Порядок ветвей повторяет функцию выше; соответствие закреплено тестом.
    """
    return case(
        (stock_display_override.isnot(None), stock_display_override),
        (
            pricing_type == PricingType.ON_REQUEST.value,
            literal(PublicAvailability.ON_REQUEST.value),
        ),
        (
            func.coalesce(available_quantity, 0) > 0,
            literal(PublicAvailability.IN_STOCK.value),
        ),
        else_=literal(PublicAvailability.OUT_OF_STOCK.value),
    )
