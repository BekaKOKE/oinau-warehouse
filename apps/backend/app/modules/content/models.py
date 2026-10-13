"""Структурированный контент сайта.

Одна таблица, одна строка на раздел (главная, контакты, доставка, FAQ,
реквизиты, общие настройки). Данные раздела — JSONB, но НЕ произвольный:
форма каждого раздела задана Pydantic-схемой (schemas_admin.py) с
`extra="forbid"`, и в базу попадает только то, что прошло её проверку.

Почему JSONB, а не таблица на раздел:
  * разделы — одиночные документы, их всегда читают и пишут целиком;
  * локализация устроена так же, как `name_i18n` у характеристик:
    {"ru": "...", "kk": "..."} прямо в поле. Казахский добавляется без
    миграции — достаточно заполнить ключ `kk` и включить язык;
  * списки (FAQ, преимущества, способы доставки) упорядочены самим
    списком: отдельные таблицы с sort_order дали бы шесть таблиц
    и десятки эндпоинтов ради того же результата.

Чего здесь сознательно нет: версий и истории правок (кто и что поменял —
в audit_log), черновиков и публикации по расписанию, произвольного HTML,
CSS и скриптов.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntPkMixin, TimestampMixin
from app.db.types import LEN_CODE, enum_check
from app.modules.content.enums import ContentSectionKey


class ContentSection(Base, IntPkMixin, TimestampMixin):
    __tablename__ = "content_sections"

    key: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    __table_args__ = (
        enum_check("key", ContentSectionKey, "key"),
        Index("uq_content_sections_key", "key", unique=True),
    )
