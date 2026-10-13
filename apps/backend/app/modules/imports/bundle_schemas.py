"""Схемы Admin API пакетного импорта (ZIP)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.modules.imports.schemas import (
    ImportIssueRead,
    ImportJobListItem,
    ImportSummaryRead,
    ProductChangeRead,
)
from app.modules.imports.upload import sanitize_filename
from app.modules.media.schemas_admin import UploadInstructions

BUNDLE_CONTENT_TYPE = "application/zip"


class BundleUploadCreate(BaseModel):
    """Запрос ссылки на загрузку архива. Размер — заявленный, проверяется по факту."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=1000)
    size_bytes: int = Field(ge=1)

    @field_validator("filename")
    @classmethod
    def _check_filename(cls, value: str) -> str:
        name = sanitize_filename(value)
        if not name.lower().endswith(".zip"):
            raise ValueError("Ожидается ZIP-архив (.zip)")
        return name

    @field_validator("size_bytes")
    @classmethod
    def _check_size(cls, value: int) -> int:
        if value > settings.import_bundle_max_bytes:
            raise ValueError(f"Архив больше {settings.IMPORT_BUNDLE_MAX_MB} МБ")
        return value


class BundleMediaStats(BaseModel):
    """Фото или схемы пакета.

    total — позиций в итоговых наборах товаров; added — новых привязок;
    removed — снятых привязок; uploaded — новых файлов в медиатеке;
    reused — файлов, уже бывших в медиатеке (повторно не загружаются).
    """

    total: int = 0
    added: int = 0
    removed: int = 0
    uploaded: int = 0
    reused: int = 0


class BundleStatsRead(BaseModel):
    photos: BundleMediaStats = Field(default_factory=BundleMediaStats)
    schemes: BundleMediaStats = Field(default_factory=BundleMediaStats)
    stock_updated: int = 0
    files_in_archive: int = 0
    files_unused: int = 0


class BundleJobRead(ImportJobListItem):
    """Пакетный импорт: статус, итог проверки или применения, ошибки.

    Проверка и применение идут в фоне: пока статус UPLOADING, CHECKING
    или APPLYING, админка опрашивает этот ресурс.
    """

    summary: ImportSummaryRead
    bundle: BundleStatsRead
    errors: list[ImportIssueRead] = Field(default_factory=list)
    warnings: list[ImportIssueRead] = Field(default_factory=list)
    changes: list[ProductChangeRead] = Field(default_factory=list)
    changes_truncated: bool = False
    can_cancel: bool = False


class BundleUploadCreated(BaseModel):
    job: BundleJobRead
    upload: UploadInstructions


__all__ = [
    "BUNDLE_CONTENT_TYPE",
    "BundleJobRead",
    "BundleMediaStats",
    "BundleStatsRead",
    "BundleUploadCreate",
    "BundleUploadCreated",
]
