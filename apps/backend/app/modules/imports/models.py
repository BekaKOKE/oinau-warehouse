"""История импортов.

Сам XLSX в базе не хранится: только метаданные (имя, размер, SHA-256)
и итог проверки. Хеш связывает подтверждение с предпросмотром — при
подтверждении администратор отправляет тот же файл, и сервер убеждается,
что применяет ровно то, что было показано в отчёте.

Ошибки хранятся в JSONB с ограничением длины, а не отдельной таблицей
`import_job_errors`: их читают только целиком вместе с импортом, и
поиск по отдельной ошибке не нужен.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntPkMixin, PublicUuidMixin, TimestampMixin
from app.db.types import LEN_CODE, LEN_SHORT_NAME, LEN_STATUS, enum_check
from app.modules.imports.enums import ImportJobKind, ImportJobStatus


class ImportJob(Base, IntPkMixin, PublicUuidMixin, TimestampMixin):
    __tablename__ = "import_jobs"

    kind: Mapped[str] = mapped_column(String(LEN_STATUS), nullable=False)
    status: Mapped[str] = mapped_column(String(LEN_STATUS), nullable=False)

    # Имя файла у пользователя — только для показа в истории. В путь
    # файловой системы или ключ хранилища не попадает никогда.
    filename: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Пусто, пока архив пакетного импорта не загружен и не проверен.
    file_sha256: Mapped[str | None] = mapped_column(String(LEN_CODE), default=None)
    # Только у пакетного импорта: ключ архива в приватном префиксе
    # хранилища (`imports/{uuid}/bundle.zip`). Архив удаляется, как
    # только перестаёт быть нужен, — ключ остаётся для истории.
    storage_key: Mapped[str | None] = mapped_column(String(512), default=None)

    # Итог проверки. На предпросмотре — план, после подтверждения —
    # фактически применённые изменения.
    rows_total: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    products_created: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    products_updated: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    products_unchanged: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb"), nullable=False
    )
    errors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb"), nullable=False
    )
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb"), nullable=False
    )

    # Кто загрузил файл на предпросмотр и кто подтвердил. Это могут быть
    # разные люди: проверить файл может и тот, у кого нет права записи.
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    committed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Код причины для FAILED: import_validation_failed, sku_exists, ...
    failure_code: Mapped[str | None] = mapped_column(String(LEN_CODE), default=None)

    __table_args__ = (
        enum_check("kind", ImportJobKind, "kind"),
        enum_check("status", ImportJobStatus, "status"),
        CheckConstraint("file_size > 0", name="file_size_positive"),
        # История читается от новых к старым.
        Index("ix_import_jobs_kind_created", "kind", sql_text("created_at DESC")),
    )
