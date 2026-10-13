"""Клиенты B2B-кабинета: учётные записи, сессии, избранное, проекты, уведомления.

Клиенты живут в отдельной таблице `customers`, а не в `users`. У сотрудника
и клиента разные политики паролей, блокировок, сроки сессий, жизненный цикл
и — главное — разный доступ. Общая таблица с флагом «это клиент» означала бы,
что одна забытая проверка в админке открывает её клиенту.
"""

from __future__ import annotations

import uuid as uuid_pkg
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntPkMixin, PublicUuidMixin, SoftDeleteMixin, TimestampMixin
from app.db.types import (
    LEN_CODE,
    LEN_EMAIL,
    LEN_HASH,
    LEN_NAME,
    LEN_PHONE,
    LEN_SHORT_NAME,
    LEN_STATUS,
    enum_check,
    qty_type,
)
from app.modules.customers.enums import CustomerTokenPurpose, NotificationType, ProjectStatus


class Customer(Base, IntPkMixin, PublicUuidMixin, TimestampMixin, SoftDeleteMixin):
    """Клиент B2B-кабинета.

    `email_verified_at IS NULL` — аккаунт зарегистрирован, но не активирован:
    войти нельзя, пока клиент не подтвердит, что владеет адресом.
    """

    __tablename__ = "customers"

    # CITEXT: регистронезависимая уникальность на уровне БД (как у users).
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(LEN_HASH), nullable=False)

    contact_name: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(LEN_SHORT_NAME), default=None)
    phone: Mapped[str] = mapped_column(String(LEN_PHONE), nullable=False)
    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="SET NULL"), default=None
    )

    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    failed_login_count: Mapped[int] = mapped_column(
        SmallInteger, server_default="0", nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    __table_args__ = (
        CheckConstraint("length(contact_name) > 0", name="contact_name_not_blank"),
        CheckConstraint("length(phone) >= 5", name="phone_min_length"),
        # Частичный уникальный индекс: удалённый аккаунт не блокирует
        # повторную регистрацию того же адреса.
        Index(
            "uq_customers_email",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_customers_region_id", "region_id"),
    )


class CustomerRefreshToken(Base, IntPkMixin):
    """Refresh-токен клиента. Отдельная таблица от `refresh_tokens` админки.

    Та же схема защиты: хранится только SHA-256, `family_id` связывает
    цепочку ротации, повторное предъявление отозванного токена отзывает
    всю цепочку.
    """

    __tablename__ = "customer_refresh_tokens"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(LEN_HASH), nullable=False)
    family_id: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    user_agent: Mapped[str | None] = mapped_column(String(LEN_EMAIL), default=None)
    ip_hash: Mapped[str | None] = mapped_column(String(64), default=None)

    __table_args__ = (
        Index("uq_customer_refresh_tokens_token_hash", "token_hash", unique=True),
        Index("ix_customer_refresh_tokens_customer_id", "customer_id"),
        Index("ix_customer_refresh_tokens_family_id", "family_id"),
    )


class CustomerActionToken(Base, IntPkMixin):
    """Одноразовый токен: подтверждение email или сброс пароля.

    Хранится только хеш. `used_at` ставится при использовании и при выпуске
    нового токена того же назначения: в любой момент действует не больше
    одной ссылки, старое письмо перестаёт работать.
    """

    __tablename__ = "customer_action_tokens"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(LEN_STATUS), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(LEN_HASH), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    ip_hash: Mapped[str | None] = mapped_column(String(64), default=None)

    __table_args__ = (
        enum_check("purpose", CustomerTokenPurpose, "purpose"),
        Index("uq_customer_action_tokens_token_hash", "token_hash", unique=True),
        Index("ix_customer_action_tokens_customer_purpose", "customer_id", "purpose"),
    )


class CustomerFavorite(Base, IntPkMixin):
    """Товар в избранном клиента.

    Строка не удаляется при снятии товара с публикации: товар вернётся
    в избранное, когда его снова опубликуют. Невидимые товары просто
    не попадают в выдачу. Жёсткое удаление товара удаляет и строку.
    """

    __tablename__ = "customer_favorites"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        Index("uq_customer_favorites_customer_product", "customer_id", "product_id", unique=True),
        Index("ix_customer_favorites_customer_created", "customer_id", text("created_at DESC")),
    )


class CustomerProject(Base, IntPkMixin, PublicUuidMixin, TimestampMixin, SoftDeleteMixin):
    """Проект клиента: объект, под который подбираются комплектующие.

    Фундамент для расширения: название, описание, регион, статус,
    выбранные позиции и связанные заявки (`requests.project_id`).
    """

    __tablename__ = "customer_projects"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="SET NULL"), default=None
    )
    status: Mapped[str] = mapped_column(
        String(LEN_STATUS), server_default=ProjectStatus.PLANNING.value, nullable=False
    )

    items: Mapped[list[CustomerProjectItem]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        enum_check("status", ProjectStatus, "status"),
        CheckConstraint("length(name) > 0", name="name_not_blank"),
        Index(
            "ix_customer_projects_customer_created",
            "customer_id",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class CustomerProjectItem(Base, IntPkMixin, TimestampMixin):
    """Позиция проекта.

    Артикул и название копируются при добавлении: товар могут снять
    с публикации или удалить, а список проекта должен остаться читаемым.
    """

    __tablename__ = "customer_project_items"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("customer_projects.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), default=None
    )
    sku_snapshot: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    name_snapshot: Mapped[str] = mapped_column(String(LEN_NAME), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(qty_type(), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    project: Mapped[CustomerProject] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity IS NULL OR quantity > 0", name="quantity_positive"),
        Index("uq_customer_project_items_project_sku", "project_id", "sku_snapshot", unique=True),
    )


class CustomerNotification(Base, IntPkMixin, PublicUuidMixin):
    """Уведомление клиента в кабинете.

    Это запись in-app. Доставка во внешние каналы (email, Telegram)
    появится отдельным этапом и будет читать эти же строки — `payload`
    содержит ссылку на объект, по которой канал соберёт сообщение.
    """

    __tablename__ = "customer_notifications"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(LEN_STATUS), nullable=False)
    title: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        enum_check("type", NotificationType, "type"),
        Index("ix_customer_notifications_customer_created", "customer_id", text("created_at DESC")),
        Index(
            "ix_customer_notifications_unread",
            "customer_id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )
