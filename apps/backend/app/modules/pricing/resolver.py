"""Расчёт цены товара для конкретного количества.

Единая функция `resolve_price()`, на которую ссылаются модель ступеней
и docs/architecture.md (раздел 6.4). Расчёт живёт только на backend:
витрина и админка его не дублируют, иначе с появлением дилерских цен
фронт начал бы показывать не то, что зафиксирует заявка.

Функция чистая — ступени передаются уже загруженными. Так заявка из
двадцати позиций получает цены одним запросом к БД, а не двадцатью.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from app.db.types import MONEY_SCALE
from app.modules.pricing.enums import PricingType

MONEY_EXPONENT = Decimal(1).scaleb(-MONEY_SCALE)


class TierLike(Protocol):
    """Ступень цены: ORM-объект PriceTier или любой объект с теми же полями."""

    @property
    def min_qty(self) -> Decimal: ...

    @property
    def max_qty(self) -> Decimal | None: ...

    @property
    def price(self) -> Decimal: ...


@dataclass(frozen=True)
class ResolvedPrice:
    """Цена позиции.

    `pricing_type` — фактический тип, который видит клиент. Товар без
    строк в публичном прайсе или количество, не попавшее ни в одну
    ступень, дают ON_REQUEST, а не ноль: отсутствие цены — состояние,
    а не число. Инвариант: `unit_price is None` ⇔ ON_REQUEST.
    """

    pricing_type: PricingType
    unit_price: Decimal | None = None
    line_total: Decimal | None = None


def round_money(value: Decimal) -> Decimal:
    """Округление до точности денежной колонки NUMERIC(14,2)."""
    return value.quantize(MONEY_EXPONENT, rounding=ROUND_HALF_UP)


def resolve_price(
    pricing_type: str | PricingType,
    tiers: Sequence[TierLike],
    quantity: Decimal,
) -> ResolvedPrice:
    """Цена за единицу и сумма строки для заданного количества.

    `tiers` — ступени ТОЛЬКО публичного прайс-листа: выбор прайса —
    забота вызывающего кода, функция о прайс-листах не знает.

    Правила:
      * ON_REQUEST — цены нет;
      * нет ни одной ступени — цены нет, как и на витрине, где такой
        товар показывается «по запросу»;
      * FIXED — одна цена, от количества не зависит;
      * TIERED и FROM — ступень, в диапазон которой попадает количество
        (границы включающие, как в `qty_range`). Количество в разрыве
        между ступенями или ниже первой даёт «цену по запросу» —
        разрывы допустимы по правилам ценообразования.

    Для FROM цена ступени — нижняя граница («от N ₸»), поэтому тип
    сохраняется в результате: получатель должен понимать, что это
    не окончательная цена.
    """
    declared = PricingType(pricing_type)
    if declared is PricingType.ON_REQUEST or not tiers:
        return ResolvedPrice(pricing_type=PricingType.ON_REQUEST)

    if declared is PricingType.FIXED:
        unit_price: Decimal | None = min(tier.price for tier in tiers)
    else:
        unit_price = next(
            (
                tier.price
                for tier in sorted(tiers, key=lambda item: item.min_qty)
                if tier.min_qty <= quantity and (tier.max_qty is None or quantity <= tier.max_qty)
            ),
            None,
        )

    if unit_price is None:
        return ResolvedPrice(pricing_type=PricingType.ON_REQUEST)

    return ResolvedPrice(
        pricing_type=declared,
        unit_price=unit_price,
        line_total=round_money(unit_price * quantity),
    )
