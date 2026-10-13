"""Импорт каталога из XLSX: предпросмотр -> подтверждение.

Предпросмотр
    читает и проверяет файл, сравнивает с каталогом и сохраняет итог
    в историю (`import_jobs`). Каталог НЕ меняется.

Подтверждение
    принимает тот же файл повторно (сверка SHA-256 с предпросмотром),
    под блокировкой проверяет его заново по свежему состоянию каталога
    и применяет одной транзакцией. Любая ошибка — откат всего файла:
    состояния «строки 1–86 записаны, остальные нет» не бывает.

Файл не хранится ни в базе, ни в хранилище. Если однажды разбор
станет тяжёлым, подтверждение переносится в воркер без изменения
контракта: файл кладётся в приватный префикс хранилища
(`imports/{job_uuid}.xlsx`), воркер выполняет тот же `_apply`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.integrity import translate_integrity_error
from app.core.logging import get_logger
from app.core.pagination import Page, PageParams
from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.catalog.integrity import CATALOG_UNIQUE_ERRORS
from app.modules.imports.applier import CatalogImportApplier
from app.modules.imports.audit import IMPORT_JOB_ENTITY, ImportAuditAction
from app.modules.imports.cells import CellError, as_text
from app.modules.imports.enums import ImportJobKind, ImportJobStatus
from app.modules.imports.exceptions import (
    ImportFileMismatchError,
    ImportJobNotFoundError,
    ImportNotCommittableError,
    ImportValidationFailedError,
)
from app.modules.imports.issues import IssueCollector
from app.modules.imports.models import ImportJob
from app.modules.imports.repository import ImportJobRepository
from app.modules.imports.schemas import (
    ImportCommitRead,
    ImportIssueRead,
    ImportJobListItem,
    ImportJobRead,
    ImportPreviewRead,
    ImportSummaryRead,
    ProductChangeRead,
)
from app.modules.imports.snapshot import CatalogSnapshot, CatalogSnapshotLoader
from app.modules.imports.upload import XlsxUpload
from app.modules.imports.validator import CatalogImportValidator, ValidationResult
from app.modules.imports.xlsx_format import Sheet, SheetSpec, build_sheet_specs
from app.modules.imports.xlsx_reader import ParsedWorkbook, read_workbook
from app.modules.users.models import User

logger = get_logger(__name__)

MAX_REPORTED_CHANGES = 1_000
# Сколько ошибок повторной проверки вернуть в теле 422 (все — в истории).
MAX_ERRORS_IN_RESPONSE = 50


class CatalogImportService(BaseService):
    kind = ImportJobKind.CATALOG

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.jobs = ImportJobRepository(session)
        self.loader = CatalogSnapshotLoader(session)
        self.audit = AuditService(session)

    # ----------------------------------------------------------- предпросмотр
    async def preview(self, upload: XlsxUpload, actor: User) -> ImportPreviewRead:
        workbook = await self._parse(upload)
        snapshot = await self.loader.load(self._skus(workbook))
        result = self._validate(workbook, snapshot)

        job = ImportJob(
            kind=self.kind.value,
            status=(ImportJobStatus.VALID if result.valid else ImportJobStatus.INVALID).value,
            filename=upload.filename,
            file_size=upload.size,
            file_sha256=upload.sha256,
            created_by_id=actor.id,
        )
        self._fill(job, result)
        self.session.add(job)
        await self.session.flush()

        self.audit.record(
            action=ImportAuditAction.PREVIEWED,
            entity_type=IMPORT_JOB_ENTITY,
            entity_id=job.id,
            user_id=actor.id,
            changes={
                "job_uuid": str(job.uuid),
                "filename": job.filename,
                "file_size": job.file_size,
                "file_sha256": job.file_sha256,
                "status": job.status,
                "rows_total": job.rows_total,
                "error_count": job.error_count,
                "products": result.summary()["products"],
            },
        )
        await self.commit()
        await self.session.refresh(job)

        changes = result.product_changes()
        return ImportPreviewRead(
            job=self._to_list_item(job),
            valid=result.valid,
            summary=ImportSummaryRead.model_validate(result.summary()),
            error_count=result.errors.total,
            errors=self._issues(result.errors),
            warning_count=result.warnings.total,
            warnings=self._issues(result.warnings),
            changes=[
                ProductChangeRead.model_validate(item) for item in changes[:MAX_REPORTED_CHANGES]
            ],
            changes_truncated=len(changes) > MAX_REPORTED_CHANGES,
        )

    # ---------------------------------------------------------- подтверждение
    async def commit_import(
        self, job_uuid: UUID, upload: XlsxUpload, actor: User
    ) -> ImportCommitRead:
        # rollback() ниже истекает все объекты сессии, включая пользователя
        # из зависимости аутентификации, — id запоминается заранее.
        actor_id = actor.id

        # Быстрый отказ до разбора файла: статус и хеш проверяются ещё раз
        # под блокировкой. Транзакция чтения закрывается, чтобы не держать
        # её открытой, пока файл разбирается.
        job = await self._require(job_uuid)
        self._ensure_committable(job, upload)
        await self.session.rollback()

        workbook = await self._parse(upload)

        applying = False
        try:
            await self.jobs.acquire_catalog_lock()
            job = await self._require(job_uuid, for_update=True)
            self._ensure_committable(job, upload)
            applying = True

            snapshot = await self.loader.load(self._skus(workbook), lock_products=True)
            result = self._validate(workbook, snapshot)
            if not result.valid:
                raise _RevalidationFailedError(result)

            await CatalogImportApplier(
                self.session, snapshot, result.plan, actor_id=actor_id, job_reference=str(job.uuid)
            ).apply()

            job.status = ImportJobStatus.COMMITTED.value
            job.committed_by_id = actor_id
            job.committed_at = datetime.now(UTC)
            self._fill(job, result)
            summary = result.summary()
            self.audit.record(
                action=ImportAuditAction.COMMITTED,
                entity_type=IMPORT_JOB_ENTITY,
                entity_id=job.id,
                user_id=actor_id,
                changes={
                    "job_uuid": str(job.uuid),
                    "file_sha256": job.file_sha256,
                    "rows_total": summary["rows_total"],
                    "products": summary["products"],
                    "categories": summary["categories"],
                    "attributes": summary["attributes"],
                    "attribute_options": summary["attribute_options"],
                },
            )
            await self.commit()
        except _RevalidationFailedError as failure:
            await self.session.rollback()
            await self._mark_failed(
                job_uuid, actor_id, code=ImportValidationFailedError.code, result=failure.result
            )
            raise ImportValidationFailedError(
                details={
                    "error_count": failure.result.errors.total,
                    "errors": [
                        issue.as_dict()
                        for issue in failure.result.errors.items[:MAX_ERRORS_IN_RESPONSE]
                    ],
                }
            ) from None
        except IntegrityError as exc:
            # Гонка: между проверкой и записью строку занял конкурент
            # (например, товар с тем же артикулом создали через админку).
            await self.session.rollback()
            domain_error = translate_integrity_error(exc, CATALOG_UNIQUE_ERRORS)
            await self._mark_failed(
                job_uuid, actor_id, code=domain_error.code if domain_error else "integrity_error"
            )
            if domain_error is None:
                raise
            raise domain_error from exc
        except Exception as exc:
            await self.session.rollback()
            if applying:
                code = exc.code if isinstance(exc, AppError) else "internal_error"
                await self._mark_failed(job_uuid, actor_id, code=code)
            raise

        await self.session.refresh(job)
        return ImportCommitRead(
            job=self._to_list_item(job),
            summary=ImportSummaryRead.model_validate(result.summary()),
            warnings=self._issues(result.warnings),
        )

    async def _mark_failed(
        self,
        job_uuid: UUID,
        actor_id: int,
        *,
        code: str,
        result: ValidationResult | None = None,
    ) -> None:
        """Отдельной транзакцией: основная уже откачена."""
        try:
            job = await self._require(job_uuid, for_update=True)
            if job.status != ImportJobStatus.VALID.value:
                await self.session.rollback()
                return
            job.status = ImportJobStatus.FAILED.value
            job.failure_code = code
            if result is not None:
                job.error_count = result.errors.total
                job.warning_count = result.warnings.total
                job.errors = [issue.as_dict() for issue in result.errors.items]
                job.warnings = [issue.as_dict() for issue in result.warnings.items]
            self.audit.record(
                action=ImportAuditAction.COMMIT_FAILED,
                entity_type=IMPORT_JOB_ENTITY,
                entity_id=job.id,
                user_id=actor_id,
                changes={"job_uuid": str(job.uuid), "failure_code": code},
            )
            await self.commit()
        except Exception as exc:
            # Не заслоняем исходную причину отказа.
            await self.session.rollback()
            logger.warning("import_mark_failed_error", error=type(exc).__name__)

    # --------------------------------------------------------------- история
    async def list_jobs(
        self, *, status: ImportJobStatus | None, params: PageParams
    ) -> Page[ImportJobListItem]:
        rows, total = await self.jobs.list_jobs(
            kind=self.kind, status=status.value if status else None, params=params
        )
        return Page.create([self._to_list_item(job) for job in rows], total, params)

    async def get_job(self, job_uuid: UUID) -> ImportJobRead:
        job = await self._require(job_uuid)
        return ImportJobRead(
            **self._to_list_item(job).model_dump(),
            summary=ImportSummaryRead.model_validate(job.summary or {}),
            errors=[ImportIssueRead.model_validate(item) for item in job.errors or []],
            warnings=[ImportIssueRead.model_validate(item) for item in job.warnings or []],
        )

    # ------------------------------------------------------------ внутреннее
    @staticmethod
    def _specs() -> dict[str, SheetSpec]:
        return build_sheet_specs(settings.SUPPORTED_LOCALES, settings.DEFAULT_LOCALE)

    async def _parse(self, upload: XlsxUpload) -> ParsedWorkbook:
        return await run_in_threadpool(
            read_workbook,
            upload.data,
            self._specs(),
            max_rows=settings.IMPORT_MAX_ROWS_PER_SHEET,
            max_uncompressed=settings.import_max_uncompressed_bytes,
        )

    @staticmethod
    def _skus(workbook: ParsedWorkbook) -> list[str]:
        """Артикулы с листа Products — для загрузки только нужных товаров."""
        sheet = workbook.sheets.get(Sheet.PRODUCTS)
        if sheet is None:
            return []
        skus: list[str] = []
        for row in sheet.rows:
            try:
                sku = as_text(row.cells.get("sku"), max_length=64)
            except CellError:
                continue
            if sku:
                skus.append(sku)
        return skus

    @staticmethod
    def _validate(workbook: ParsedWorkbook, snapshot: CatalogSnapshot) -> ValidationResult:
        return CatalogImportValidator(
            workbook,
            snapshot,
            locales=settings.SUPPORTED_LOCALES,
            default_locale=settings.DEFAULT_LOCALE,
        ).validate()

    async def _require(self, job_uuid: UUID, *, for_update: bool = False) -> ImportJob:
        job = await self.jobs.get_by_uuid(job_uuid, kind=self.kind, for_update=for_update)
        if job is None:
            raise ImportJobNotFoundError
        return job

    @staticmethod
    def _expires_at(job: ImportJob) -> datetime:
        return job.created_at + timedelta(hours=settings.IMPORT_PREVIEW_TTL_HOURS)

    def _ensure_committable(self, job: ImportJob, upload: XlsxUpload) -> None:
        status = ImportJobStatus(job.status)
        if status is ImportJobStatus.INVALID:
            raise ImportNotCommittableError(
                "Предпросмотр нашёл ошибки: исправьте файл и загрузите его заново",
                code="import_not_valid",
            )
        if status is ImportJobStatus.COMMITTED:
            raise ImportNotCommittableError("Импорт уже применён", code="import_already_committed")
        if status is ImportJobStatus.FAILED:
            raise ImportNotCommittableError(
                "Подтверждение уже было отклонено: загрузите файл на предпросмотр заново",
                code="import_failed",
            )
        if self._expires_at(job) <= datetime.now(UTC):
            raise ImportNotCommittableError(
                "Предпросмотр устарел: загрузите файл на предпросмотр заново",
                code="import_preview_expired",
            )
        if upload.sha256 != job.file_sha256:
            raise ImportFileMismatchError

    @staticmethod
    def _fill(job: ImportJob, result: ValidationResult) -> None:
        summary = result.summary()
        products = summary["products"]
        job.rows_total = result.rows_total
        job.products_created = products["create"]
        job.products_updated = products["update"]
        job.products_unchanged = products["unchanged"]
        job.error_count = result.errors.total
        job.warning_count = result.warnings.total
        job.summary = summary
        job.errors = [issue.as_dict() for issue in result.errors.items]
        job.warnings = [issue.as_dict() for issue in result.warnings.items]

    @staticmethod
    def _issues(collector: IssueCollector) -> list[ImportIssueRead]:
        return [ImportIssueRead.model_validate(issue.as_dict()) for issue in collector.items]

    def _to_list_item(self, job: ImportJob) -> ImportJobListItem:
        expires_at = self._expires_at(job)
        return ImportJobListItem(
            uuid=job.uuid,
            kind=ImportJobKind(job.kind),
            status=ImportJobStatus(job.status),
            filename=job.filename,
            file_size=job.file_size,
            file_sha256=job.file_sha256,
            rows_total=job.rows_total,
            products_created=job.products_created,
            products_updated=job.products_updated,
            products_unchanged=job.products_unchanged,
            error_count=job.error_count,
            warning_count=job.warning_count,
            failure_code=job.failure_code,
            created_by_id=job.created_by_id,
            committed_by_id=job.committed_by_id,
            created_at=job.created_at,
            committed_at=job.committed_at,
            expires_at=expires_at,
            can_commit=job.status == ImportJobStatus.VALID.value and expires_at > datetime.now(UTC),
        )


class _RevalidationFailedError(Exception):
    def __init__(self, result: ValidationResult) -> None:
        super().__init__("revalidation failed")
        self.result = result
