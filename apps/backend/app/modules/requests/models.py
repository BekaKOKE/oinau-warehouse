"""Заявки, их позиции, комментарии и история статусов."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.db.base import (
    Base,
    IntPkMixin,
    PublicUuidMixin,
    SoftDeleteMixin,
    TimestampMixin,
)
from app.db.types import (
    LEN_CODE,
    LEN_EMAIL,
    LEN_NAME,
    LEN_PHONE,
    LEN_SHORT_NAME,
    LEN_SLUG,
    LEN_STATUS,
    LEN_UNIT,
    LEN_URL,
    enum_check,
    money_type,
    qty_type,
)
from app.modules.requests.enums import RequestKind, RequestSource, RequestStatus

if TYPE_CHECKING:
    from app.modules.users.models import User


class Request(Base, IntPkMixin, PublicUuidMixin, TimestampMixin, SoftDeleteMixin):
    """Заявка от клиента.

    Персональные данные (имя, телефон, email) хранятся в PostgreSQL
    на территории РК — этого требует закон о персональных данных.
    В объектное хранилище ПДн не попадают никогда.
    """

    __tablename__ = "requests"

    number: Mapped[str] = mapped_column(String(24), nullable=False)
    kind: Mapped[str] = mapped_column(String(LEN_STATUS), nullable=False)
    status: Mapped[str] = mapped_column(
        String(LEN_STATUS), server_default=RequestStatus.NEW.value, nullable=False
    )

    # ---------------------------------------------------------- контакты
    # Обязательны только имя и телефон — всё остальное опционально,
    # потому что каждое лишнее обязательное поле снижает конверсию формы.
    customer_name: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    phone: Mapped[str] = mapped_column(String(LEN_PHONE), nullable=False)
    email: Mapped[str | None] = mapped_column(String(LEN_EMAIL), default=None)
    company: Mapped[str | None] = mapped_column(String(LEN_SHORT_NAME), default=None)
    bin: Mapped[str | None] = mapped_column(String(12), default=None)

    # Город — свободный текст (клиент пишет что угодно), region_id —
    # нормализованная привязка, которую проставляет менеджер или
    # определение по IP. Алматы не зашит в схему.
    city: Mapped[str | None] = mapped_column(String(LEN_SHORT_NAME), default=None)
    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="SET NULL"), default=None
    )

    comment: Mapped[str | None] = mapped_column(Text, default=None)
    preferred_contact: Mapped[str | None] = mapped_column(String(LEN_UNIT), default=None)

    # ---------------------------------------------------------- служебное
    source: Mapped[str] = mapped_column(
        String(LEN_STATUS), server_default=RequestSource.CATALOG_CART.value, nullable=False
    )
    utm: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    page_url: Mapped[str | None] = mapped_column(String(LEN_URL), default=None)

    # Хеш IP, а не сам IP: для антиспама достаточно сравнения, а хранение
    # сырых адресов — лишние персональные данные.
    ip_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(LEN_EMAIL), default=None)

    # Приходит с фронта при открытии формы. Двойной клик, ретрай мобильной
    # сети и повторная отправка при таймауте не создадут дубль, из-за
    # которого менеджер позвонит клиенту дважды.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), default=None)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Расчёт на момент подачи. Пересчитывается на сервере, значения
    # с клиента игнорируются.
    total_estimate: Mapped[Decimal | None] = mapped_column(money_type(), default=None)
    currency: Mapped[str] = mapped_column(String(3), server_default="KZT", nullable=False)

    assigned_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    # Заявка из B2B-кабинета: клиент видит её в истории. Анонимная заявка
    # с сайта оставляет поле пустым. SET NULL — удаление аккаунта не должно
    # уничтожать коммерческий документ.
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), default=None
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_projects.id", ondelete="SET NULL"), default=None
    )

    # Для будущей выгрузки в 1С: идентификатор созданного там документа.
    external_id: Mapped[str | None] = mapped_column(String(LEN_CODE), default=None)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    items: Mapped[list[RequestItem]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    comments: Mapped[list[RequestComment]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    status_history: Mapped[list[RequestStatusHistory]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    attachments: Mapped[list[RequestAttachment]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    assigned_to: Mapped[User | None] = relationship()

    __table_args__ = (
        enum_check("kind", RequestKind, "kind"),
        enum_check("status", RequestStatus, "status"),
        CheckConstraint("length(customer_name) > 0", name="customer_name_not_blank"),
        CheckConstraint("length(phone) >= 5", name="phone_min_length"),
        CheckConstraint("bin IS NULL OR bin ~ '^[0-9]{12}$'", name="bin_format"),
        Index("uq_requests_number", "number", unique=True),
        Index(
            "uq_requests_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        # Главный экран админки: новые заявки сверху.
        Index("ix_requests_status_created", "status", text("created_at DESC")),
        Index("ix_requests_created_at", text("created_at DESC")),
        Index("ix_requests_kind_status", "kind", "status"),
        Index(
            "ix_requests_assigned_to_id",
            "assigned_to_id",
            postgresql_where=text("assigned_to_id IS NOT NULL"),
        ),
        Index("ix_requests_phone", "phone"),
        # История заявок в кабинете: «мои заявки, новые сверху».
        Index(
            "ix_requests_customer_created",
            "customer_id",
            text("created_at DESC"),
            postgresql_where=text("customer_id IS NOT NULL"),
        ),
        Index(
            "ix_requests_project_id",
            "project_id",
            postgresql_where=text("project_id IS NOT NULL"),
        ),
        # Выгрузка в 1С: "все новые заявки, ещё не переданные"
        Index(
            "ix_requests_pending_export", "created_at", postgresql_where=text("exported_at IS NULL")
        ),
    )


class RequestItem(Base, IntPkMixin):
    """Позиция заявки — снимок товара на момент отправки.

    СНАПШОТ ОБЯЗАТЕЛЕН. Заявка — коммерчески значимый документ. Через
    полгода товар переименуют, цену поднимут, позицию снимут с
    производства. Состав заявки должен показывать то, что видел клиент
    в момент отправки, иначе в споре с клиентом нечем оперировать.

    Что снимается:
      sku_snapshot        — артикул мог быть перевыставлен из 1С
      name_snapshot       — название меняется при перекатегоризации
      unit_snapshot       — смена единицы измерения меняет смысл количества
      unit_price_snapshot — главное: цена на момент обращения
      line_total_snapshot — хранится отдельно, а не считается как
                            qty * price: при ступенчатых ценах и будущих
                            скидках эта связь перестаёт быть линейной
      pricing_type_snapshot — товар мог быть "по запросу", и тогда
                            отсутствие цены — это факт, а не потеря данных

    Что НЕ снимается: описание, изображения, характеристики. Они не
    участвуют в коммерческих обязательствах, а их копирование раздуло бы
    таблицу без пользы. Для карточки берётся текущий товар по product_id.

    product_id — ссылка со SET NULL, а не источник данных. Товар может
    быть удалён; заявка обязана это пережить.
    """

    __tablename__ = "request_items"

    request_id: Mapped[int] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), default=None
    )

    sku_snapshot: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    name_snapshot: Mapped[str] = mapped_column(String(LEN_NAME), nullable=False)
    unit_snapshot: Mapped[str] = mapped_column(String(LEN_UNIT), nullable=False)
    pricing_type_snapshot: Mapped[str] = mapped_column(String(LEN_STATUS), nullable=False)
    # Цвет позиции — снапшот кода и названия из справочника цветов.
    # NULL: у товара нет цветов или цвет не выбран (менеджер уточнит).
    color_code_snapshot: Mapped[str | None] = mapped_column(String(LEN_SLUG), default=None)
    color_name_snapshot: Mapped[str | None] = mapped_column(String(LEN_SHORT_NAME), default=None)

    quantity: Mapped[Decimal] = mapped_column(qty_type(), nullable=False)
    unit_price_snapshot: Mapped[Decimal | None] = mapped_column(money_type(), default=None)
    line_total_snapshot: Mapped[Decimal | None] = mapped_column(money_type(), default=None)

    note: Mapped[str | None] = mapped_column(Text, default=None)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    request: Mapped[Request] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "unit_price_snapshot IS NULL OR unit_price_snapshot >= 0", name="price_non_negative"
        ),
        Index("ix_request_items_request_id", "request_id"),
        # Аналитика: какие товары чаще всего запрашивают
        Index(
            "ix_request_items_product_id",
            "product_id",
            postgresql_where=text("product_id IS NOT NULL"),
        ),
        Index("ix_request_items_sku", "sku_snapshot"),
    )


class RequestComment(Base, IntPkMixin, TimestampMixin):
    """Комментарий менеджера к заявке."""

    __tablename__ = "request_comments"

    request_id: Mapped[int] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Внутренние комментарии не показываются клиенту, если появится
    # публичная страница статуса заявки.
    is_internal: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)

    request: Mapped[Request] = relationship(back_populates="comments")

    __table_args__ = (
        CheckConstraint("length(body) > 0", name="body_not_blank"),
        Index("ix_request_comments_request_id", "request_id", "created_at"),
    )


class RequestAttachment(Base, IntPkMixin):
    """Файл, приложенный клиентом к заявке (спецификация, ТЗ, чертёж).

    Лежит в PostgreSQL, а не в объектном хранилище. Спецификация
    заказчика — документ, привязанный к контактам клиента, и в ней
    самой бывают ФИО и телефоны. ПДн хранятся только в БД на территории
    РК (docs/architecture.md, риск 5), а R2 — хранилище изображений
    товаров. Объём небольшой: файл до REQUEST_ATTACHMENT_MAX_SIZE_MB,
    не больше одного на заявку.

    `data` загружается отложенно: карточка и список заявок читают только
    метаданные, содержимое достаётся лишь при скачивании.
    """

    __tablename__ = "request_attachments"

    request_id: Mapped[int] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), nullable=False
    )
    # Имя, которое прислал клиент, — только для показа и скачивания.
    # В путь файловой системы оно не попадает.
    filename: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    # Тип определяет сервер по расширению и сигнатуре, а не берёт
    # из заголовка клиента.
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    request: Mapped[Request] = relationship(back_populates="attachments")

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("length(filename) > 0", name="filename_not_blank"),
        Index("ix_request_attachments_request_id", "request_id"),
    )


class RequestStatusHistory(Base, IntPkMixin):
    """История смены статусов заявки.

    Отдельно от общего audit_log, потому что читается постоянно —
    прямо в карточке заявки, вместе с ней. Держать это в разнородном
    журнале аудита означало бы фильтровать его при каждом открытии
    заявки.
    """

    __tablename__ = "request_status_history"

    request_id: Mapped[int] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(LEN_STATUS), default=None)
    to_status: Mapped[str] = mapped_column(String(LEN_STATUS), nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    request: Mapped[Request] = relationship(back_populates="status_history")

    __table_args__ = (Index("ix_request_status_history_request_id", "request_id", "created_at"),)
