"""Схемы Admin API справочника цветов и цветов товара."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.inventory.enums import PublicAvailability

QuantityField = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]
MoneyField = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
HexField = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]

MAX_PRODUCT_COLORS = 50


def _lower(value: str | None) -> str | None:
    # В базе образец хранится строчными: «#FF0000» и «#ff0000» — один цвет.
    return value.lower() if isinstance(value, str) else value


# ---------------------------------------------------------------- справочник


class ColorCreate(BaseModel):
    code: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=255)
    hex: HexField
    sort_order: int = Field(default=0, ge=0, le=1_000_000)
    is_active: bool = True

    _hex = field_validator("hex")(_lower)


class ColorUpdate(BaseModel):
    """Код не меняется: он записан в отправленных заявках."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    hex: HexField | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1_000_000)
    is_active: bool | None = None

    _hex = field_validator("hex")(_lower)


class ColorRead(BaseModel):
    id: int
    code: str
    name: str
    hex: str
    sort_order: int
    is_active: bool
    # В скольких товарах используется: удалить можно только неиспользуемый.
    products_count: int = 0


# ------------------------------------------------------------- цвета товара


class ProductColorInput(BaseModel):
    color_id: int = Field(ge=1)
    quantity: QuantityField = Decimal("0")
    # Надбавка к каждой ступени цены товара.
    price_delta: MoneyField = Decimal("0")


class ProductColorsUpdate(BaseModel):
    """Полная замена набора цветов товара. Порядок списка — порядок на витрине."""

    items: list[ProductColorInput] = Field(max_length=MAX_PRODUCT_COLORS)

    @model_validator(mode="after")
    def _check_duplicates(self) -> ProductColorsUpdate:
        ids = [item.color_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Цвет указан несколько раз")
        return self


class ProductColorRead(BaseModel):
    color_id: int
    code: str
    name: str
    hex: str
    color_is_active: bool
    quantity: Decimal
    price_delta: Decimal
    # Что увидит посетитель у этого цвета.
    public_availability: PublicAvailability


class ProductColorsRead(BaseModel):
    product_id: int
    sku: str
    unit: str
    items: list[ProductColorRead] = Field(default_factory=list)
    # Сумма остатков по цветам и общий свободный остаток по активным
    # складам. Расхождение — повод проверить разбивку.
    colors_total: Decimal
    stock_total: Decimal
