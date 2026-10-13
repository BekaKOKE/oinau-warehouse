"""География.

Алматы — не константа в коде и не значение по умолчанию в схеме, а строка
в таблице regions. Добавление второго города должно быть операцией INSERT,
а не миграцией.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, ExternalSyncMixin, IntPkMixin, TimestampMixin
from app.db.types import LEN_CODE, LEN_SHORT_NAME


class Region(Base, IntPkMixin, TimestampMixin, ExternalSyncMixin):
    """Регион работы компании.

    На старте одна строка: code='almaty'. К региону привязываются склады
    и прайс-листы, поэтому добавление города автоматически даёт возможность
    задать для него свои цены и условия наличия.

    deleted_at не нужен: регионов единицы, они не удаляются, а отключаются
    через is_active. Мягкое удаление здесь было бы лишней сложностью.
    """

    __tablename__ = "regions"

    code: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    name: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    __table_args__ = (
        Index("uq_regions_code", "code", unique=True),
        Index(
            "uq_regions_external_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )
