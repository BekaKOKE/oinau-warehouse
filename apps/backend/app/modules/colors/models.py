"""Цвета товаров.

Две таблицы:

* `colors` — общий справочник: название и образец цвета для витрины.
  Один справочник на весь каталог, чтобы «чёрный» у каната и у
  сиденья был одним и тем же цветом, а не двумя строками с разным
  написанием.
* `product_colors` — в каких цветах продаётся товар: остаток и надбавка
  к цене по каждому цвету.

Остаток цвета — ручная разбивка общего остатка товара, а не замена
`stocks`. Общий остаток по складам по-прежнему считается из `stocks`
и правится там же (вручную или из 1С): на нём держатся фильтр «в
наличии», сводка каталога и обмен с 1С. Админка показывает сумму по
цветам рядом с общим остатком и предупреждает о расхождении.

Цена цвета — надбавка к ступеням товара, а не своя таблица ступеней:
скидки за объём у всех цветов одни и те же, отличается только
наценка на цветное исполнение.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntPkMixin, TimestampMixin
from app.db.types import LEN_SHORT_NAME, LEN_SLUG, money_type, qty_type

# #RRGGBB — образец цвета на витрине.
HEX_PATTERN = r"^#[0-9a-f]{6}$"


class Color(Base, IntPkMixin, TimestampMixin):
    """Цвет из справочника."""

    __tablename__ = "colors"

    # Латиница: уходит в заявку и в URL витрины, не меняется при
    # переименовании.
    code: Mapped[str] = mapped_column(String(LEN_SLUG), nullable=False)
    name: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    hex: Mapped[str] = mapped_column(String(7), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)

    __table_args__ = (
        CheckConstraint(f"hex ~ '{HEX_PATTERN}'", name="hex_format"),
        CheckConstraint("length(name) > 0", name="name_not_blank"),
        Index("uq_colors_code", "code", unique=True),
    )


class ProductColor(Base, IntPkMixin, TimestampMixin):
    """Цвет, в котором продаётся товар."""

    __tablename__ = "product_colors"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    # RESTRICT: цвет, который продаётся, из справочника не удаляется —
    # его отключают.
    color_id: Mapped[int] = mapped_column(
        ForeignKey("colors.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(qty_type(), server_default="0", nullable=False)
    # Надбавка к каждой ступени цены товара. Базовая цена товара — цена
    # самого дешёвого исполнения, поэтому надбавка не бывает отрицательной.
    price_delta: Mapped[Decimal] = mapped_column(money_type(), server_default="0", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    color: Mapped[Color] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("price_delta >= 0", name="price_delta_non_negative"),
        Index("uq_product_colors_product_id_color_id", "product_id", "color_id", unique=True),
        Index("ix_product_colors_color_id", "color_id"),
    )
