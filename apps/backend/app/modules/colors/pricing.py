"""Цена товара в конкретном цвете.

Надбавка цвета прибавляется к каждой ступени: скидки за объём у всех
цветов одни и те же. Расчёт остаётся в `resolve_price()` — сюда
передаются уже сдвинутые ступени.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.modules.pricing.resolver import TierLike


@dataclass(frozen=True)
class ShiftedTier:
    min_qty: Decimal
    max_qty: Decimal | None
    price: Decimal


def shift_tiers(tiers: Sequence[TierLike], delta: Decimal) -> list[TierLike]:
    if not delta:
        return list(tiers)
    return [
        ShiftedTier(min_qty=tier.min_qty, max_qty=tier.max_qty, price=tier.price + delta)
        for tier in tiers
    ]
