"""Запросы истории импортов."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select

from app.core.pagination import PageParams
from app.core.repository import BaseRepository
from app.modules.imports.enums import ImportJobKind
from app.modules.imports.models import ImportJob

# Ключ транзакционной advisory-блокировки импорта каталога. Два
# подтверждения не выполняются одновременно: второе дождётся первого
# и проверит файл уже по его результату.
CATALOG_IMPORT_LOCK_KEY = 7_246_915_001


class ImportJobRepository(BaseRepository[ImportJob]):
    model = ImportJob

    async def get_by_uuid(
        self, job_uuid: UUID, *, kind: ImportJobKind, for_update: bool = False
    ) -> ImportJob | None:
        query = select(ImportJob).where(ImportJob.uuid == job_uuid, ImportJob.kind == kind.value)
        if for_update:
            query = query.with_for_update()
        query = query.execution_options(populate_existing=True)
        return (await self.session.execute(query)).scalars().first()

    async def list_jobs(
        self, *, kind: ImportJobKind, status: str | None, params: PageParams
    ) -> tuple[Sequence[ImportJob], int]:
        query = select(ImportJob).where(ImportJob.kind == kind.value)
        if status is not None:
            query = query.where(ImportJob.status == status)
        total = (
            await self.session.execute(
                select(func.count()).select_from(query.with_only_columns(ImportJob.id).subquery())
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                query.order_by(ImportJob.created_at.desc(), ImportJob.id.desc())
                .limit(params.limit)
                .offset(params.offset)
            )
        ).scalars()
        return rows.all(), total

    async def acquire_catalog_lock(self) -> None:
        """Снимается автоматически при COMMIT/ROLLBACK."""
        await self.session.execute(select(func.pg_advisory_xact_lock(CATALOG_IMPORT_LOCK_KEY)))

    async def lock_job(self, job_id: int, *, kind: ImportJobKind) -> ImportJob | None:
        """Строка задачи для воркера. SKIP LOCKED: повторная постановка той
        же задачи в очередь не приведёт к двойной обработке."""
        query = (
            select(ImportJob)
            .where(ImportJob.id == job_id, ImportJob.kind == kind.value)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(query)).scalars().first()

    async def list_stale(
        self, *, kind: ImportJobKind, statuses: Sequence[str], before: datetime, limit: int
    ) -> Sequence[ImportJob]:
        """Задачи в указанных статусах, не менявшиеся с момента `before`."""
        query = (
            select(ImportJob)
            .where(
                ImportJob.kind == kind.value,
                ImportJob.status.in_(list(statuses)),
                ImportJob.updated_at < before,
            )
            .order_by(ImportJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return (await self.session.execute(query)).scalars().all()
