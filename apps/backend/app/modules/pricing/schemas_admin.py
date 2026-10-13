"""Схемы Admin API ценообразования.

Правила типов цен проверяются здесь, а не только CHECK-ограничениями
базы: PostgreSQL знает про отдельную ступень, но ничего не знает про
`pricing_type` товара и не может сказать, что у FIXED ступень должна
быть ровно одна.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from app.modules.pricing.enums import PricingType

# Точность совпадает с колонками БД: NUMERIC(14,3) для количества
# и NUMERIC(14,2) для денег. Ограничение стоит здесь, чтобы лишние
# знаки отвергались явно, а не округлялись базой молча.
QtyField = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]
MaxQtyField = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]
PriceField = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]

MAX_TIERS = 20


class PriceTierInput(BaseModel):
    min_qty: QtyField
    # null означает открытый диапазон «и выше» — верхняя ступень 100+
    max_qty: MaxQtyField | None = None
    price: PriceField

    @model_validator(mode="after")
    def _check_range(self) -> PriceTierInput:
        if self.max_qty is not None and self.max_qty < self.min_qty:
            raise ValueError(f"Верхняя граница {self.max_qty} меньше нижней {self.min_qty}")
        return self


class PricingUpdate(BaseModel):
    """Полная замена публичного ценообразования товара."""

    pricing_type: PricingType
    tiers: list[PriceTierInput] = Field(default_factory=list, max_length=MAX_TIERS)

    @model_validator(mode="after")
    def _check_pricing_type(self) -> PricingUpdate:
        if self.pricing_type is PricingType.ON_REQUEST:
            if self.tiers:
                raise ValueError("Для типа ON_REQUEST ступени не задаются")
            return self

        if not self.tiers:
            raise ValueError(f"Для типа {self.pricing_type.value} нужна хотя бы одна ступень")

        if self.pricing_type is PricingType.FIXED:
            if len(self.tiers) != 1:
                raise ValueError("Для типа FIXED должна быть ровно одна ступень")
            tier = self.tiers[0]
            if tier.min_qty != Decimal(1) or tier.max_qty is not None:
                raise ValueError(
                    "Для типа FIXED ступень должна покрывать любое количество: "
                    "min_qty=1, max_qty=null"
                )

        self._check_ranges()
        return self

    def _check_ranges(self) -> None:
        """Диапазоны не должны пересекаться.

        Границы включающие, как в генерируемой колонке `qty_range`
        (`numrange(min_qty, max_qty, '[]')`), поэтому 1–9 и 10–49 —
        соседние, а 1–10 и 10–20 пересекаются по количеству 10.

        Непрерывность НЕ требуется: 1–9 и 20–49 допустимы. Модель этого
        не запрещает, и придумывать правило ради красивой таблицы не
        стоит — заказ на 15 штук просто попадёт в «цену по запросу».
        """
        open_ended = [tier for tier in self.tiers if tier.max_qty is None]
        if len(open_ended) > 1:
            raise ValueError("Открытая верхняя ступень может быть только одна")

        ordered = sorted(self.tiers, key=lambda tier: tier.min_qty)
        for previous, current in pairwise(ordered):
            if previous.max_qty is None or previous.max_qty >= current.min_qty:
                raise ValueError(
                    f"Диапазоны пересекаются: ступень от {previous.min_qty} "
                    f"и ступень от {current.min_qty}"
                )


class PriceTierRead(BaseModel):
    id: int
    min_qty: Decimal
    max_qty: Decimal | None
    price: Decimal


class PriceListRead(BaseModel):
    """Публичный прайс-лист.

    Дилерские и партнёрские прайсы через это API недоступны: админка
    на старте работает только с прайсом по умолчанию.
    """

    id: int
    code: str
    name: str
    currency: str


class PricingRead(BaseModel):
    product_id: int
    sku: str
    pricing_type: PricingType
    # Валюта берётся из прайс-листа и через товар не меняется.
    currency: str
    price_list_code: str
    tiers: list[PriceTierRead] = Field(default_factory=list)
    min_price: Decimal | None = None
    max_price: Decimal | None = None
