"""Медиатека и привязка изображений к товарам.

В PostgreSQL хранятся ТОЛЬКО метаданные. Бинарные данные — в объектном
хранилище (Cloudflare R2 в проде, MinIO локально). BYTEA для изображений
не используется ни при каких условиях: он раздувает базу, ломает
резервное копирование и заставляет backend раздавать картинки.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntPkMixin, PublicUuidMixin, TimestampMixin
from app.db.types import LEN_CODE, LEN_SHORT_NAME, LEN_STATUS, enum_check
from app.modules.media.enums import ImageKind, MediaStatus

if TYPE_CHECKING:
    from app.modules.catalog.models import Product


class MediaFile(Base, IntPkMixin, PublicUuidMixin, TimestampMixin):
    """Физический файл в объектном хранилище.

    Хранится storage_key, а НЕ URL. URL собирается на backend как
    CDN_BASE_URL + storage_key, поэтому смена CDN-домена или переезд
    на другого S3-провайдера — правка переменной окружения, а не
    массовый UPDATE.

    variants — карта сгенерированных размеров:
        {"large": {"key": "...", "w": 1600, "h": 1200}, "thumb": {...}}
    JSONB, а не отдельная таблица: варианты всегда читаются и пишутся
    целиком вместе с файлом, отдельных запросов к ним не бывает.
    Такая форма поддерживает обе стратегии обработки — собственный
    воркер и трансформации на стороне CDN (решение на этапе 6).
    """

    __tablename__ = "media_files"

    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    bucket: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    # Имя файла у пользователя — только для отображения в медиатеке.
    # В ключе объекта не участвует никогда: ключ строится из UUID.
    original_filename: Mapped[str | None] = mapped_column(String(LEN_SHORT_NAME), default=None)
    # Код причины для FAILED (MediaFailureReason). Без него админка
    # может сказать только «не получилось».
    failure_reason: Mapped[str | None] = mapped_column(String(LEN_CODE), default=None)

    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    checksum: Mapped[str | None] = mapped_column(String(64), default=None)

    status: Mapped[str] = mapped_column(
        String(LEN_STATUS), server_default=MediaStatus.PENDING.value, nullable=False
    )
    variants: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )

    uploaded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    __table_args__ = (
        enum_check("status", MediaStatus, "status"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        Index("uq_media_files_storage_key", "storage_key", unique=True),
        # Для уборки брошенных загрузок
        Index("ix_media_files_status_created", "status", "created_at"),
        # Дедупликация одинаковых файлов при повторной загрузке
        Index("ix_media_files_checksum", "checksum", postgresql_where=text("checksum IS NOT NULL")),
    )


class ProductImage(Base, IntPkMixin, TimestampMixin):
    """Привязка файла медиатеки к товару.

    Две таблицы вместо одной, потому что один файл (схема узла, логотип
    бренда) может использоваться в нескольких товарах и на контентных
    страницах. Разделение также позволяет удалить товар, не потеряв файл,
    и заменить файл, не трогая порядок изображений.

    alt_i18n — JSONB: alt-текст короткий, локализуемый и всегда читается
    вместе со строкой. Отдельная таблица переводов ради одного поля
    добавила бы JOIN в запрос карточки товара.
    """

    __tablename__ = "product_images"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    media_file_id: Mapped[int] = mapped_column(
        ForeignKey("media_files.id", ondelete="RESTRICT"), nullable=False
    )

    kind: Mapped[str] = mapped_column(
        String(LEN_STATUS), server_default=ImageKind.PHOTO.value, nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    is_main: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    alt_i18n: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )

    product: Mapped[Product] = relationship(back_populates="images")
    media_file: Mapped[MediaFile] = relationship()

    __table_args__ = (
        enum_check("kind", ImageKind, "kind"),
        Index("ix_product_images_product_sort", "product_id", "sort_order"),
        Index("ix_product_images_media_file_id", "media_file_id"),
        # Обложка карточки может быть только одна
        Index(
            "uq_product_images_main",
            "product_id",
            unique=True,
            postgresql_where=text("is_main"),
        ),
        Index(
            "uq_product_images_product_media",
            "product_id",
            "media_file_id",
            unique=True,
        ),
    )
