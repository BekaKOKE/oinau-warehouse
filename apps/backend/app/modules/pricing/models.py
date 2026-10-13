"""Прайс-листы и ценовые ступени."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import NUMRANGE, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ExternalSyncMixin, IntPkMixin, TimestampMixin
from app.db.types import LEN_CODE, LEN_SHORT_NAME, LEN_STATUS, money_type, qty_type

if TYPE_CHECKING:
    from app.modules.catalog.models import Product


class PriceList(Base, IntPkMixin, TimestampMixin, ExternalSyncMixin):
    """Прайс-лист.

    На старте существует ровно одна строка: code='default'. В админке
    выбор прайс-листа не показывается — интерфейс работает с прайсом
    по умолчанию.

    Уровень абстракции заложен сейчас, потому что дилерские цены и цены
    для второго региона — вопрос времени, а ретрофит потребовал бы
    переписать все запросы цен и API витрины.
    """

    __tablename__ = "price_lists"

    code: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    name: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), server_default="KZT", nullable=False)

    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), default=None
    )
    customer_group: Mapped[str | None] = mapped_column(String(LEN_STATUS), default=None)

    is_default: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)

    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    tiers: Mapped[list[PriceTier]] = relationship(
        back_populates="price_list", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name="valid_period",
        ),
        Index("uq_price_lists_code", "code", unique=True),
        # Прайс-лист по умолчанию может быть только один: иначе
        # resolve_price() пришлось бы выбирать произвольный.
        Index(
            "uq_price_lists_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


class PriceTier(Base, IntPkMixin, TimestampMixin, ExternalSyncMixin):
    """Ценовая ступень: цена товара при заказе от min_qty до max_qty.

    Обычная цена — это одна ступень [1, NULL]. Отдельной таблицы или
    отдельной колонки для неё не нужно: единая модель избавляет
    resolve_price() от ветвлений.

    max_qty IS NULL означает "и выше" — верхняя ступень 100+.
    """

    __tablename__ = "price_tiers"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    price_list_id: Mapped[int] = mapped_column(
        ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False
    )

    min_qty: Mapped[Decimal] = mapped_column(qty_type(), server_default="1", nullable=False)
    max_qty: Mapped[Decimal | None] = mapped_column(qty_type(), default=None)
    price: Mapped[Decimal] = mapped_column(money_type(), nullable=False)

    # Генерируемая колонка нужна EXCLUDE-ограничению: оно умеет работать
    # с диапазонным типом, но не с парой отдельных колонок.
    # Границы включающие: [1,9] и [10,49] не пересекаются.
    qty_range: Mapped[object] = mapped_column(
        NUMRANGE,
        Computed("numrange(min_qty, max_qty, '[]')", persisted=True),
        nullable=True,
    )

    product: Mapped[Product] = relationship(back_populates="price_tiers")
    price_list: Mapped[PriceList] = relationship(back_populates="tiers")

    __table_args__ = (
        CheckConstraint("min_qty > 0", name="min_qty_positive"),
        CheckConstraint("max_qty IS NULL OR max_qty >= min_qty", name="qty_range_valid"),
        CheckConstraint("price >= 0", name="price_non_negative"),
        # Пересекающиеся диапазоны физически невозможны.
        # Ограничение оправдано: цены правят менеджеры, Excel-импорт и,
        # в перспективе, 1С. Любой из трёх источников может создать
        # ступени [1,50] и [40,100], после чего resolve_price() вернёт
        # произвольную из двух цен, а расхождение всплывёт в споре
        # с клиентом. Проверка в коде приложения не спасает при
        # конкурентных транзакциях. Требует btree_gist (уже подключён).
        ExcludeConstraint(
            ("product_id", "="),
            ("price_list_id", "="),
            ("qty_range", "&&"),
            name="no_overlapping_tiers",
            using="gist",
        ),
        Index("ix_price_tiers_lookup", "product_id", "price_list_id", "min_qty"),
        Index(
            "uq_price_tiers_external_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )
