"""Схемы Admin API медиатеки и изображений товаров.

Ключ объекта в хранилище (`storage_key`) не отдаётся даже в админку:
интерфейсу он не нужен, а ссылки на показ строятся на сервере.
"""

from __future__ import annotations

import os
import unicodedata
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings
from app.core.text import clean_localized
from app.db.types import LEN_SHORT_NAME
from app.modules.media.documents import is_document
from app.modules.media.enums import ImageKind, MediaPurpose, MediaStatus

MAX_ALT_LENGTH = 255

# Изображений у товара больше этого числа не бывает по делу, а без
# предела одна ошибка скрипта или импорта раздует карточку до сотен фото.
MAX_PRODUCT_IMAGES = 30


def sanitize_filename(value: str) -> str:
    """Имя файла только для отображения.

    Путь отбрасывается (браузеры и скрипты иногда присылают его целиком),
    управляющие символы вырезаются. В ключ объекта имя не попадает.
    """
    name = unicodedata.normalize("NFC", value).replace("\\", "/")
    name = os.path.basename(name)
    name = "".join(
        char
        for char in name
        if unicodedata.category(char) not in ("Cc", "Cf") and char not in "<>\"'`"
    ).strip()
    if not name:
        raise ValueError("Пустое имя файла")
    return name[:LEN_SHORT_NAME]


def clean_alt(value: dict[str, str]) -> dict[str, str]:
    """Alt-текст необязателен, но если задан — с русской версией."""
    if not any(text.strip() for text in value.values()):
        return {}
    return clean_localized(
        value,
        max_length=MAX_ALT_LENGTH,
        multiline=False,
        default_locale=settings.DEFAULT_LOCALE,
    )


# ------------------------------------------------------------- медиатека


class MediaUploadCreate(BaseModel):
    """Запрос ссылки на загрузку.

    Тип и размер, заявленные клиентом, — только предварительный фильтр.
    Реальные значения проверяются после загрузки: размер — по HEAD
    объекта, тип — по сигнатуре и декодированию в воркере.
    """

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=1000)
    content_type: str = Field(min_length=1, max_length=64)
    size_bytes: int = Field(ge=1)
    purpose: MediaPurpose = MediaPurpose.PRODUCT

    @field_validator("filename")
    @classmethod
    def _clean_filename(cls, value: str) -> str:
        return sanitize_filename(value)

    @field_validator("content_type")
    @classmethod
    def _check_content_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = allowed_upload_mime()
        if normalized not in allowed:
            raise ValueError("Недопустимый тип файла. Разрешены: " + ", ".join(allowed))
        return normalized

    @model_validator(mode="after")
    def _check_size(self) -> MediaUploadCreate:
        # Предел зависит от типа: схема в PDF законно тяжелее фотографии.
        if is_document(self.content_type):
            if self.size_bytes > settings.upload_max_document_size_bytes:
                raise ValueError(f"Файл больше {settings.UPLOAD_MAX_DOCUMENT_SIZE_MB} МБ")
        elif self.size_bytes > settings.upload_max_size_bytes:
            raise ValueError(f"Файл больше {settings.UPLOAD_MAX_SIZE_MB} МБ")
        return self


def allowed_upload_mime() -> list[str]:
    """Изображения и документы, которые принимает медиатека."""
    return [*settings.UPLOAD_ALLOWED_MIME, *settings.UPLOAD_ALLOWED_DOCUMENT_MIME]


class UploadInstructions(BaseModel):
    """Как загрузить файл: PUT на `url` с заголовками `headers` без изменений."""

    url: str
    method: str
    headers: dict[str, str]
    expires_in: int


class MediaRead(BaseModel):
    uuid: UUID
    status: MediaStatus
    original_filename: str | None = None
    content_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    # Только для READY: ссылка на основной вариант и все варианты.
    url: str | None = None
    variants: dict[str, str] = Field(default_factory=dict)
    failure_reason: str | None = None
    # Сколько товаров используют файл. Удаление возможно только при нуле.
    usage_count: int = 0
    uploaded_by_id: int | None = None
    created_at: datetime
    updated_at: datetime


class MediaProductUsage(BaseModel):
    product_id: int
    sku: str
    image_id: int
    is_deleted: bool


class MediaDetail(MediaRead):
    products: list[MediaProductUsage] = Field(default_factory=list)
    content_sections: list[str] = Field(default_factory=list)


class MediaUploadCreated(BaseModel):
    media: MediaRead
    upload: UploadInstructions


# ------------------------------------------------------ изображения товара


class ProductImageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_uuid: UUID
    kind: ImageKind = ImageKind.PHOTO
    alt: dict[str, str] = Field(default_factory=dict)
    # Первое изображение товара становится главным и без этого флага.
    is_main: bool = False

    @field_validator("alt")
    @classmethod
    def _check_alt(cls, value: dict[str, str]) -> dict[str, str]:
        return clean_alt(value)


class ProductImageUpdate(BaseModel):
    """Подпись и роль. Порядок и главное изображение — отдельными эндпоинтами."""

    model_config = ConfigDict(extra="forbid")

    kind: ImageKind | None = None
    alt: dict[str, str] | None = None

    @field_validator("alt")
    @classmethod
    def _check_alt(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return clean_alt(value) if value is not None else None


class ProductImagesOrder(BaseModel):
    """Новый порядок — полный список id изображений товара."""

    model_config = ConfigDict(extra="forbid")

    image_ids: list[int] = Field(min_length=1, max_length=MAX_PRODUCT_IMAGES)

    @field_validator("image_ids")
    @classmethod
    def _check_unique(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("Изображение указано в порядке несколько раз")
        return value


class ProductMainImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: int = Field(ge=1)


class ProductImageRead(BaseModel):
    id: int
    media_uuid: UUID
    kind: ImageKind
    alt: dict[str, str] = Field(default_factory=dict)
    is_main: bool
    sort_order: int
    # Статус файла: админка видит и ещё не готовые изображения,
    # витрина — только READY.
    status: MediaStatus
    is_publicly_visible: bool
    url: str | None = None
    variants: dict[str, str] = Field(default_factory=dict)
    width: int | None = None
    height: int | None = None
    original_filename: str | None = None
    # Тип файла: документ (PDF, DWG, DXF) админка показывает значком,
    # а не превью — картинки у него нет.
    content_type: str = "image/png"
    size_bytes: int = 0
    created_at: datetime


class ProductImageList(BaseModel):
    product_id: int
    items: list[ProductImageRead]
