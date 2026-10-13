"""SQL-форма правила наличия совпадает с resolve_availability.

Сводка каталога и список остатков админки считают статус в базе,
витрина и карточка остатков — в Python. Правило одно, и расхождение
между формами означало бы, что дашборд показывает не то, что сайт.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import product

import pytest
from sqlalchemy import Numeric, String, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.availability import availability_expression, resolve_availability
from app.modules.inventory.enums import StockDisplayOverride
from app.modules.pricing.enums import PricingType

OVERRIDES = [None, *(item.value for item in StockDisplayOverride)]
PRICING = [item.value for item in PricingType]
AVAILABLE = [None, Decimal("0"), Decimal("-1.000"), Decimal("0.001"), Decimal("152.500")]


@pytest.mark.parametrize(
    ("override", "pricing_type", "available"), list(product(OVERRIDES, PRICING, AVAILABLE))
)
async def test_sql_rule_matches_python_rule(
    db: AsyncSession, override: str | None, pricing_type: str, available: Decimal | None
) -> None:
    expression = availability_expression(
        pricing_type=literal(pricing_type, String()),
        stock_display_override=literal(override, String()),
        available_quantity=literal(available, Numeric(14, 3)),
    )
    from_sql = (await db.execute(select(expression))).scalar_one()

    expected = resolve_availability(
        pricing_type=pricing_type,
        stock_display_override=override,
        available_quantity=available,
    )
    assert from_sql == expected.value
