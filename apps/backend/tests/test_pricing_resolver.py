"""Тесты расчёта цены по количеству — без БД."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.modules.pricing.enums import PricingType
from app.modules.pricing.resolver import resolve_price


@dataclass(frozen=True)
class Tier:
    min_qty: Decimal
    max_qty: Decimal | None
    price: Decimal


TIERED = [
    # Порядок перемешан намеренно: функция не должна полагаться на него
    Tier(Decimal("50"), Decimal("99"), Decimal("2900.00")),
    Tier(Decimal("1"), Decimal("9"), Decimal("3500.00")),
    Tier(Decimal("100"), None, Decimal("2600.00")),
    Tier(Decimal("10"), Decimal("49"), Decimal("3200.00")),
]


@pytest.mark.parametrize(
    ("quantity", "price"),
    [
        ("1", "3500.00"),
        ("9", "3500.00"),  # включающая верхняя граница
        ("10", "3200.00"),  # включающая нижняя граница
        ("49", "3200.00"),
        ("50", "2900.00"),
        ("100", "2600.00"),
        ("100000", "2600.00"),  # открытая верхняя ступень
    ],
)
def test_tiered_price_depends_on_quantity(quantity: str, price: str) -> None:
    result = resolve_price(PricingType.TIERED, TIERED, Decimal(quantity))

    assert result.pricing_type is PricingType.TIERED
    assert result.unit_price == Decimal(price)
    assert result.line_total == Decimal(price) * Decimal(quantity)


@pytest.mark.parametrize("quantity", ["0.5", "9.5", "49.001"])
def test_quantity_outside_tiers_is_on_request(quantity: str) -> None:
    """Разрывы между ступенями допустимы — такое количество «по запросу»."""
    result = resolve_price(PricingType.TIERED, TIERED, Decimal(quantity))

    assert result.pricing_type is PricingType.ON_REQUEST
    assert result.unit_price is None
    assert result.line_total is None


def test_from_price_is_resolved_by_tier_and_keeps_its_type() -> None:
    """FROM — «от N ₸»: цена ступени есть, но тип сохраняется, чтобы
    получатель понимал, что это нижняя граница."""
    tiers = [Tier(Decimal("1"), None, Decimal("2600.00"))]
    result = resolve_price(PricingType.FROM, tiers, Decimal("3"))

    assert result.pricing_type is PricingType.FROM
    assert result.unit_price == Decimal("2600.00")
    assert result.line_total == Decimal("7800.00")


@pytest.mark.parametrize("quantity", ["0.25", "1", "1000"])
def test_fixed_price_does_not_depend_on_quantity(quantity: str) -> None:
    tiers = [Tier(Decimal("1"), None, Decimal("1200.00"))]
    result = resolve_price(PricingType.FIXED, tiers, Decimal(quantity))

    assert result.pricing_type is PricingType.FIXED
    assert result.unit_price == Decimal("1200.00")


def test_on_request_has_no_price_even_with_tiers() -> None:
    result = resolve_price(PricingType.ON_REQUEST, TIERED, Decimal("10"))
    assert result.pricing_type is PricingType.ON_REQUEST
    assert result.unit_price is None


@pytest.mark.parametrize("pricing_type", [PricingType.FIXED, PricingType.FROM, PricingType.TIERED])
def test_product_without_public_tiers_is_on_request(pricing_type: PricingType) -> None:
    """Как и на витрине: товар без строк в публичном прайсе — «по запросу»."""
    result = resolve_price(pricing_type, [], Decimal("1"))
    assert result.pricing_type is PricingType.ON_REQUEST
    assert result.unit_price is None


def test_line_total_is_rounded_to_money_scale() -> None:
    tiers = [Tier(Decimal("0.001"), None, Decimal("10.01"))]
    # 10.01 * 1.005 = 10.06005 -> 10.06; 10.01 * 0.125 = 1.25125 -> 1.25
    assert resolve_price("TIERED", tiers, Decimal("1.005")).line_total == Decimal("10.06")
    assert resolve_price("TIERED", tiers, Decimal("0.125")).line_total == Decimal("1.25")
    # Половина копейки округляется вверх: 0.05 * 0.5 = 0.025 -> 0.03
    half = [Tier(Decimal("0.001"), None, Decimal("0.05"))]
    assert resolve_price("FIXED", half, Decimal("0.5")).line_total == Decimal("0.03")
