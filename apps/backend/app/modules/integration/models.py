"""Ключи доступа внешних систем.

Ключ выдаётся системе, а не человеку: у него нет пароля, роли и
сессии. Поэтому это отдельная таблица, а не строка в `users` —
смешивать субъектов с разными правилами отзыва и разной моделью
прав значит однажды выдать 1С доступ в админку.

В базе хранится только SHA-256 ключа. Ключ показывается один раз
при выдаче; восстановить его нельзя — только перевыпустить.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntPkMixin, PublicUuidMixin, TimestampMixin
from app.db.types import LEN_SHORT_NAME

# Видимый префикс ключа. Нужен, чтобы отличать ключи в журнале и в
# админке, не зная самого ключа: «oic_3f9a…» достаточно для опознания.
KEY_PREFIX_LENGTH = 12


class ApiKey(Base, IntPkMixin, PublicUuidMixin, TimestampMixin):
    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(KEY_PREFIX_LENGTH), nullable=False)

    # Разрешённые операции: ["catalog:write", "inventory:write", ...].
    # Список, а не роль: у обмена с 1С и у будущего мобильного клиента
    # нет ничего общего, кроме способа аутентификации.
    scopes: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )

    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        Index("uq_api_keys_key_hash", "key_hash", unique=True),
        Index("ix_api_keys_active", "is_active"),
    )

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def to_public(self) -> dict[str, Any]:
        """Безопасное представление для журналов: без хеша и без ключа."""
        return {"name": self.name, "prefix": self.key_prefix}
