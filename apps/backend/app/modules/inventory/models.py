"""Склады и остатки.

Модель: текущее состояние остатка по паре (товар, склад).

Регистр движений (stock_movements) сознательно НЕ создаётся. Движения
имеют смысл, когда система сама списывает и приходует товар. У нас
источником истины по остаткам будет 1С, а сайт — витриной, которая
получает готовое число. Ведение параллельного регистра означало бы
второй источник правды и неизбежные расхождения с учётной системой.

Если позже понадобится история изменений остатка, её даёт audit_log
без изменения этой схемы.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ExternalSyncMixin, IntPkMixin, TimestampMixin
from app.db.types import LEN_CODE, LEN_SHORT_NAME, qty_type

if TYPE_CHECKING:
    from app.modules.catalog.models import Product
    from app.modules.geo.models import Region


class Warehouse(Base, IntPkMixin, TimestampMixin, ExternalSyncMixin):
    """Склад.

    На старте один склад в Алматы. Структура "товар × склад" заложена
    сразу, чтобы появление второго города не потребовало миграции
    и пересчёта всех остатков.
    """

    __tablename__ = "warehouses"

    code: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    name: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), default=None
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)

    region: Mapped[Region | None] = relationship()

    __table_args__ = (
        Index("uq_warehouses_code", "code", unique=True),
        Index(
            "uq_warehouses_external_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )


class Stock(Base, ExternalSyncMixin):
    """Текущий остаток товара на складе.

    quantity — NUMERIC: канат меряется метрами, крепёж бывает в килограммах.

    reserved заложен, но на этапе 3 не используется: заявки ничего не
    резервируют. Поле понадобится вместе с 1С, когда появится
    резервирование под подтверждённую заявку.

    Публичный API отдаёт только статус, не число: точный остаток —
    коммерческая информация, по которой конкурент оценивает обороты.
    """

    __tablename__ = "stocks"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )

    quantity: Mapped[Decimal] = mapped_column(qty_type(), server_default="0", nullable=False)
    reserved: Mapped[Decimal] = mapped_column(qty_type(), server_default="0", nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    # Когда 1С в последний раз упомянула строку в выгрузке остатков —
    # даже если числа не изменились. synced_at при этом значения не
    # меняет: он по-прежнему отвечает на вопрос «когда данные изменились».
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    product: Mapped[Product] = relationship(back_populates="stocks")

    __table_args__ = (
        PrimaryKeyConstraint("product_id", "warehouse_id", name="pk_stocks"),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("reserved >= 0", name="reserved_non_negative"),
        Index("ix_stocks_warehouse_id", "warehouse_id"),
        # Для выборки "что есть в наличии" без сканирования всей таблицы
        Index("ix_stocks_available", "product_id", postgresql_where=text("quantity > 0")),
    )
