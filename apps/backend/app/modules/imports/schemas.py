"""Схемы Admin API импорта и экспорта каталога."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.imports.enums import ImportJobKind, ImportJobStatus


class ImportIssueRead(BaseModel):
    """Ошибка или предупреждение в данных файла.

    `row` — номер строки Excel (заголовок — строка 1), `column` — имя
    колонки из заголовка. Для ошибок уровня книги оба поля пусты.
    """

    sheet: str | None
    row: int | None
    column: str | None
    code: str
    message: str
    value: str | None = None


class EntityCounts(BaseModel):
    create: int = 0
    update: int = 0
    unchanged: int = 0


class ImportSummaryRead(BaseModel):
    rows_total: int = 0
    sheets: dict[str, int] = Field(default_factory=dict)
    products: EntityCounts = Field(default_factory=EntityCounts)
    categories: EntityCounts = Field(default_factory=EntityCounts)
    attributes: EntityCounts = Field(default_factory=EntityCounts)
    attribute_options: EntityCounts = Field(default_factory=EntityCounts)


class ProductChangeRead(BaseModel):
    """Что произойдёт с товаром. `changed` — изменившиеся части:
    поля (`slug`, `status`, ...), `translations`, `categories`,
    `attributes`, `specs`, `pricing`."""

    row: int
    sku: str
    action: Literal["create", "update"]
    changed: list[str] = Field(default_factory=list)


class ImportJobListItem(BaseModel):
    uuid: UUID
    kind: ImportJobKind
    status: ImportJobStatus
    filename: str
    file_size: int
    # Пусто, пока архив пакетного импорта не загружен и не проверен.
    file_sha256: str | None = None
    rows_total: int
    # На предпросмотре — план, после подтверждения — факт.
    products_created: int
    products_updated: int
    products_unchanged: int
    error_count: int
    warning_count: int
    failure_code: str | None = None
    created_by_id: int | None = None
    committed_by_id: int | None = None
    created_at: datetime
    committed_at: datetime | None = None
    expires_at: datetime
    can_commit: bool


class ImportJobRead(ImportJobListItem):
    summary: ImportSummaryRead
    errors: list[ImportIssueRead] = Field(default_factory=list)
    warnings: list[ImportIssueRead] = Field(default_factory=list)


class ImportPreviewRead(BaseModel):
    """Результат предпросмотра. Каталог при этом не меняется."""

    job: ImportJobListItem
    valid: bool
    summary: ImportSummaryRead
    error_count: int
    errors: list[ImportIssueRead]
    warning_count: int
    warnings: list[ImportIssueRead]
    changes: list[ProductChangeRead]
    changes_truncated: bool = False


class ImportCommitRead(BaseModel):
    job: ImportJobListItem
    summary: ImportSummaryRead
    warnings: list[ImportIssueRead] = Field(default_factory=list)
