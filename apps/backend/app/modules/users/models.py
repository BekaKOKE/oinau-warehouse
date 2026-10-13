"""Пользователи админ-панели и сессии обновления токенов."""

from __future__ import annotations

import uuid as uuid_pkg
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntPkMixin, PublicUuidMixin, SoftDeleteMixin, TimestampMixin
from app.db.types import (
    LEN_EMAIL,
    LEN_HASH,
    LEN_PHONE,
    LEN_SHORT_NAME,
    LEN_STATUS,
    enum_check,
)
from app.modules.users.enums import UserRole

if TYPE_CHECKING:
    pass


class User(Base, IntPkMixin, PublicUuidMixin, TimestampMixin, SoftDeleteMixin):
    """Сотрудник компании.

    Мягкое удаление обязательно: уволенный менеджер остаётся автором
    комментариев к заявкам и записей аудита. Жёсткий DELETE обнулил бы
    эти ссылки и уничтожил историю.
    """

    __tablename__ = "users"

    # CITEXT вместо VARCHAR: регистронезависимая уникальность на уровне БД.
    # Хранить lower(email) отдельной колонкой или полагаться на нормализацию
    # в приложении — путь к дублям вида Ivan@ и ivan@.
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(LEN_HASH), nullable=False)
    full_name: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(LEN_PHONE), default=None)

    role: Mapped[str] = mapped_column(String(LEN_STATUS), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    failed_login_count: Mapped[int] = mapped_column(
        SmallInteger, server_default="0", nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        enum_check("role", UserRole, "role"),
        # Частичный уникальный индекс: удалённый сотрудник не блокирует
        # повторное заведение того же email.
        Index(
            "uq_users_email",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_users_role_active", "role", "is_active"),
    )


class RefreshToken(Base, IntPkMixin):
    """Refresh-токен админки.

    Хранится ХЕШ токена, не сам токен: утечка дампа БД не должна давать
    возможность войти в админку.

    family_id объединяет токены одной цепочки ротации. Если пришёл уже
    использованный refresh — значит, токен украден, и отзывается вся
    семья, а не один экземпляр. Логика ротации — этап 4.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(LEN_HASH), nullable=False)
    family_id: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    user_agent: Mapped[str | None] = mapped_column(String(LEN_EMAIL), default=None)
    ip_hash: Mapped[str | None] = mapped_column(String(64), default=None)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    __table_args__ = (
        Index("uq_refresh_tokens_token_hash", "token_hash", unique=True),
        Index("ix_refresh_tokens_user_id", "user_id"),
        Index("ix_refresh_tokens_family_id", "family_id"),
    )
