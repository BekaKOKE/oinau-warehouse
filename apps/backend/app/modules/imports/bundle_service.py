"""Пакетный импорт каталога: ZIP с книгой, фотографиями и схемами.

Поток (docs/api-catalog-import-export.md, раздел «Пакетный импорт»):

    1. POST /bundle-imports              -> задача UPLOADING + presigned PUT
    2. PUT архива в приватный префикс     (браузер -> R2, мимо API и прокси)
    3. POST /bundle-imports/{uuid}/check -> CHECKING, задача в очередь
    4. воркер: проверка архива и книги    -> VALID | INVALID (предпросмотр)
    5. POST /bundle-imports/{uuid}/commit -> APPLYING, задача в очередь
    6. воркер: загрузка новых файлов в медиатеку, затем под блокировкой
       импорта повторная проверка и применение одной транзакцией
                                          -> COMMITTED | FAILED
    7. после коммита — обработка новых файлов воркером медиатеки
       (варианты WebP / публичная копия документа), архив удаляется

Каталог меняется только на шаге 6. Катастрофа посередине (обрыв БД,
ошибка кода) откатывает транзакцию целиком: товары, цены, остатки и
привязки файлов не применяются частично. Уже загруженные в хранилище
новые файлы при откате удаляются.

Почему воркер, а не запрос: архив с сотнями фотографий весит сотни
мегабайт — он не пройдёт через лимит тела запроса на прокси, а его
проверка и загрузка файлов в хранилище занимают минуты.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError, ConflictError
from app.core.integrity import translate_integrity_error
from app.core.logging import get_logger
from app.core.pagination import Page, PageParams
from app.core.service import BaseService
from app.infrastructure.storage.base import ObjectStorage, ObjectTooLargeError
from app.modules.audit.service import AuditService
from app.modules.catalog.integrity import CATALOG_UNIQUE_ERRORS
from app.modules.catalog.models import Product
from app.modules.imports.applier import CatalogImportApplier
from app.modules.imports.audit import IMPORT_JOB_ENTITY, ImportAuditAction
from app.modules.imports.bundle_archive import (
    BundleArchive,
    BundleLimits,
    BundleRejectedError,
    open_bundle,
)
from app.modules.imports.bundle_files import FileCheck, check_file, read_checked
from app.modules.imports.bundle_format import SCHEMES_DIR, build_bundle_sheet_specs
from app.modules.imports.bundle_plan import (
    BundleApplier,
    BundleContext,
    BundlePlan,
    BundlePlanner,
    UploadedFile,
    load_context,
    referenced_files,
)
from app.modules.imports.bundle_schemas import (
    BUNDLE_CONTENT_TYPE,
    BundleJobRead,
    BundleStatsRead,
    BundleUploadCreate,
    BundleUploadCreated,
)
from app.modules.imports.bundle_validator import BundleImportValidator
from app.modules.imports.cells import CellError, as_text
from app.modules.imports.enums import ImportJobKind, ImportJobStatus
from app.modules.imports.exceptions import ImportJobNotFoundError, ImportNotCommittableError
from app.modules.imports.issues import Issue, IssueCode, IssueCollector
from app.modules.imports.models import ImportJob
from app.modules.imports.repository import ImportJobRepository
from app.modules.imports.schemas import (
    ImportIssueRead,
    ImportJobListItem,
    ImportSummaryRead,
    ProductChangeRead,
)
from app.modules.imports.snapshot import CatalogSnapshot, CatalogSnapshotLoader
from app.modules.imports.validator import ValidationResult
from app.modules.imports.xlsx_format import Sheet
from app.modules.imports.xlsx_reader import ParsedWorkbook, read_workbook
from app.modules.media.enums import MediaPurpose
from app.modules.media.queue import MediaQueue
from app.modules.media.schemas_admin import UploadInstructions
from app.modules.media.service_admin import build_original_key
from app.modules.users.models import User

logger = get_logger(__name__)

MAX_REPORTED_CHANGES = 1_000
# Сколько файлов одновременно уходит в хранилище при применении.
UPLOAD_CONCURRENCY = 4
# Задача, застрявшая в CHECKING/APPLYING дольше, считается упавшей.
PROCESSING_TIMEOUT = timedelta(hours=2)
CLEANUP_BATCH = 100

# Статусы, в которых архив ещё лежит в хранилище.
_ARCHIVE_STATUSES = (
    ImportJobStatus.UPLOADING.value,
    ImportJobStatus.CHECKING.value,
    ImportJobStatus.VALID.value,
    ImportJobStatus.APPLYING.value,
)
_CANCELLABLE = frozenset(
    {
        ImportJobStatus.UPLOADING.value,
        ImportJobStatus.CHECKING.value,
        ImportJobStatus.VALID.value,
        ImportJobStatus.INVALID.value,
    }
)

CHECK_TASK = "check_catalog_bundle"
APPLY_TASK = "apply_catalog_bundle"


class BundleQueue(Protocol):
    async def enqueue_check(self, job_id: int) -> None: ...

    async def enqueue_apply(self, job_id: int) -> None: ...


class ArqBundleQueue:
    async def enqueue_check(self, job_id: int) -> None:
        from app.workers.queue import enqueue

        await enqueue(CHECK_TASK, job_id)

    async def enqueue_apply(self, job_id: int) -> None:
        from app.workers.queue import enqueue

        await enqueue(APPLY_TASK, job_id)


def get_bundle_queue() -> BundleQueue:
    return ArqBundleQueue()


def bundle_storage_key(job_uuid: UUID) -> str:
    """Приватный префикс: политика бакета открывает только `*/variants/*`."""
    return f"imports/{job_uuid}/bundle.zip"


def bundle_limits() -> BundleLimits:
    return BundleLimits(
        max_files=settings.IMPORT_BUNDLE_MAX_FILES,
        max_uncompressed=settings.import_bundle_max_uncompressed_bytes,
        max_ratio=settings.IMPORT_BUNDLE_MAX_RATIO,
        max_workbook=settings.upload_max_size_bytes,
        max_photo=settings.upload_max_size_bytes,
        max_scheme=settings.upload_max_document_size_bytes,
    )


class BundleStateError(ConflictError):
    code = "import_bundle_state"
    message = "Действие недоступно в текущем состоянии импорта"


class BundleArchiveMissingError(ConflictError):
    code = "upload_not_found"
    message = "Архив ещё не загружен в хранилище"


# ============================================================== внутреннее
@dataclass
class _Bundle:
    archive: BundleArchive
    workbook: ParsedWorkbook


@dataclass
class _Evaluation:
    snapshot: CatalogSnapshot
    result: ValidationResult
    checks: dict[str, FileCheck]
    context: BundleContext
    plan: BundlePlan


class _RevalidationFailedError(Exception):
    def __init__(self, result: ValidationResult) -> None:
        super().__init__("revalidation failed")
        self.result = result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_and_parse(path: Path) -> _Bundle:
    """Синхронно, в пуле потоков: каталог архива и разбор книги."""
    handle = path.open("rb")
    try:
        archive = open_bundle(handle, bundle_limits())
    except BaseException:
        handle.close()
        raise
    try:
        workbook = read_workbook(
            archive.read_workbook(),
            build_bundle_sheet_specs(settings.SUPPORTED_LOCALES, settings.DEFAULT_LOCALE),
            max_rows=settings.IMPORT_MAX_ROWS_PER_SHEET,
            max_uncompressed=settings.import_max_uncompressed_bytes,
        )
    except BaseException:
        archive.close()
        handle.close()
        raise
    return _Bundle(archive=archive, workbook=workbook)


def _close(bundle: _Bundle) -> None:
    fp = bundle.archive.archive.fp
    bundle.archive.close()
    if fp is not None:
        fp.close()


def _check_files(archive: BundleArchive, files: list[Any]) -> dict[str, FileCheck]:
    return {
        item.path: check_file(
            archive,
            item,
            max_photo=settings.upload_max_size_bytes,
            max_scheme=settings.upload_max_document_size_bytes,
            max_pixels=settings.UPLOAD_MAX_IMAGE_PIXELS,
        )
        for item in files
    }


class BundleImportService(BaseService):
    kind = ImportJobKind.CATALOG_BUNDLE

    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: ObjectStorage,
        queue: BundleQueue | None = None,
        media_queue: MediaQueue | None = None,
    ) -> None:
        super().__init__(session)
        self.storage = storage
        self.queue = queue
        self.media_queue = media_queue
        self.jobs = ImportJobRepository(session)
        self.loader = CatalogSnapshotLoader(session)
        self.audit = AuditService(session)

    # ================================================================ HTTP
    async def create_upload(self, payload: BundleUploadCreate, actor: User) -> BundleUploadCreated:
        job_uuid = uuid.uuid4()
        job = ImportJob(
            uuid=job_uuid,
            kind=self.kind.value,
            status=ImportJobStatus.UPLOADING.value,
            filename=payload.filename,
            file_size=payload.size_bytes,
            storage_key=bundle_storage_key(job_uuid),
            created_by_id=actor.id,
        )
        self.session.add(job)
        await self.session.flush()
        assert job.storage_key is not None
        upload = await self.storage.create_upload_url(
            job.storage_key,
            content_type=BUNDLE_CONTENT_TYPE,
            expires_in=settings.UPLOAD_PRESIGN_TTL_SECONDS,
        )
        self._record(
            ImportAuditAction.BUNDLE_UPLOAD_REQUESTED,
            job,
            actor.id,
            {"filename": job.filename, "declared_size": job.file_size},
        )
        await self.commit()
        await self.session.refresh(job)
        return BundleUploadCreated(
            job=self._to_read(job),
            upload=UploadInstructions(
                url=upload.url,
                method=upload.method,
                headers=upload.headers,
                expires_in=upload.expires_in,
            ),
        )

    async def start_check(self, job_uuid: UUID, actor: User) -> BundleJobRead:
        """Архив загружен — проверить. Повтор для CHECKING ставит задачу снова."""
        job = await self._require(job_uuid, for_update=True)
        if job.status == ImportJobStatus.CHECKING.value:
            await self.commit()
            await self._enqueue_check(job.id)
            return self._to_read(job)
        if job.status != ImportJobStatus.UPLOADING.value:
            raise BundleStateError(details={"status": job.status})

        assert job.storage_key is not None
        stored = await self.storage.stat(job.storage_key)
        if stored is None:
            raise BundleArchiveMissingError
        job.file_size = stored.size
        if stored.size > settings.import_bundle_max_bytes:
            # Presigned PUT не ограничивает размер тела: проверка по факту.
            self._reject(
                job,
                IssueCode.BUNDLE_REJECTED,
                f"Архив больше {settings.IMPORT_BUNDLE_MAX_MB} МБ",
            )
            await self.commit()
            await self._delete_objects([job.storage_key])
            return self._to_read(job)

        job.status = ImportJobStatus.CHECKING.value
        self._record(
            ImportAuditAction.BUNDLE_CHECK_STARTED, job, actor.id, {"file_size": stored.size}
        )
        await self.commit()
        await self._enqueue_check(job.id)
        await self.session.refresh(job)
        return self._to_read(job)

    async def commit_import(self, job_uuid: UUID, actor: User) -> BundleJobRead:
        job = await self._require(job_uuid, for_update=True)
        status = ImportJobStatus(job.status)
        if status is ImportJobStatus.APPLYING:
            # Повторное нажатие: задача уже в работе, ставим снова на случай,
            # если прошлая постановка не удалась.
            await self.commit()
            await self._enqueue_apply(job.id)
            return self._to_read(job)
        if status is ImportJobStatus.COMMITTED:
            raise ImportNotCommittableError("Импорт уже применён", code="import_already_committed")
        if status is not ImportJobStatus.VALID:
            raise ImportNotCommittableError(
                "Применить можно только проверенный архив без ошибок", code="import_not_valid"
            )
        if self._expires_at(job) <= datetime.now(UTC):
            raise ImportNotCommittableError(
                "Предпросмотр устарел: загрузите архив заново", code="import_preview_expired"
            )
        job.status = ImportJobStatus.APPLYING.value
        job.committed_by_id = actor.id
        self._record(ImportAuditAction.BUNDLE_APPLY_STARTED, job, actor.id, {})
        await self.commit()
        await self._enqueue_apply(job.id)
        await self.session.refresh(job)
        return self._to_read(job)

    async def cancel(self, job_uuid: UUID, actor: User) -> BundleJobRead:
        job = await self._require(job_uuid, for_update=True)
        if job.status not in _CANCELLABLE:
            raise BundleStateError(
                "Отменить можно только импорт, который ещё не применяется",
                details={"status": job.status},
            )
        job.status = ImportJobStatus.CANCELLED.value
        self._record(ImportAuditAction.BUNDLE_CANCELLED, job, actor.id, {})
        await self.commit()
        if job.storage_key:
            await self._delete_objects([job.storage_key])
        await self.session.refresh(job)
        return self._to_read(job)

    async def get_job(self, job_uuid: UUID) -> BundleJobRead:
        return self._to_read(await self._require(job_uuid))

    async def get_job_model(self, job_uuid: UUID) -> ImportJob:
        return await self._require(job_uuid)

    async def list_jobs(
        self, *, status: ImportJobStatus | None, params: PageParams
    ) -> Page[ImportJobListItem]:
        rows, total = await self.jobs.list_jobs(
            kind=self.kind, status=status.value if status else None, params=params
        )
        return Page.create([self._to_list_item(job) for job in rows], total, params)

    # ============================================================== воркер
    async def run_check(self, job_id: int) -> str:
        """Проверка архива — предпросмотр. Каталог не меняется."""
        job = await self.jobs.lock_job(job_id, kind=self.kind)
        if job is None or job.status != ImportJobStatus.CHECKING.value:
            await self.rollback()
            return "skipped"
        job_uuid, key = job.uuid, job.storage_key
        # Блокировка строки не держится всю проверку: отмена во время
        # проверки должна пройти сразу, а результат тогда отбросится.
        await self.commit()
        assert key is not None

        outcome: tuple[str, int, _Evaluation | None, list[Issue]]
        try:
            outcome = await self._check_archive(key)
        except Exception as exc:
            logger.warning("bundle_check_error", job_id=job_id, error=type(exc).__name__)
            await self.rollback()
            outcome = (
                "",
                0,
                None,
                [_book_issue(IssueCode.BUNDLE_REJECTED, "Архив не удалось проверить")],
            )

        sha, size, evaluation, rejected = outcome
        job = await self.jobs.lock_job(job_id, kind=self.kind)
        if job is None or job.status != ImportJobStatus.CHECKING.value:
            await self.rollback()
            return "discarded"
        if sha:
            job.file_sha256 = sha
            job.file_size = size
        if evaluation is None:
            self._fill_rejected(job, rejected)
        else:
            valid = evaluation.result.valid
            job.status = (ImportJobStatus.VALID if valid else ImportJobStatus.INVALID).value
            self._fill(job, evaluation)
        self._record(
            ImportAuditAction.PREVIEWED,
            job,
            None,
            {
                "job_uuid": str(job_uuid),
                "status": job.status,
                "file_sha256": job.file_sha256,
                "error_count": job.error_count,
            },
        )
        await self.commit()
        if job.status == ImportJobStatus.INVALID.value:
            # С ошибками архив применить нельзя — хранить его незачем.
            await self._delete_objects([key])
        return job.status

    async def _check_archive(self, key: str) -> tuple[str, int, _Evaluation | None, list[Issue]]:
        with tempfile.TemporaryDirectory(prefix="oinau-bundle-") as directory:
            path = Path(directory) / "bundle.zip"
            try:
                size = await self._download(key, path)
            except ObjectTooLargeError:
                return (
                    "",
                    0,
                    None,
                    [
                        _book_issue(
                            IssueCode.BUNDLE_REJECTED,
                            f"Архив больше {settings.IMPORT_BUNDLE_MAX_MB} МБ",
                        )
                    ],
                )
            sha = await asyncio.to_thread(_sha256_file, path)
            try:
                bundle = await asyncio.to_thread(_open_and_parse, path)
            except BundleRejectedError as exc:
                return sha, size, None, [_book_issue(IssueCode.BUNDLE_REJECTED, exc.message)]
            except AppError as exc:
                return sha, size, None, [_book_issue(IssueCode.BUNDLE_REJECTED, exc.message)]
            try:
                evaluation = await self._evaluate(bundle, lock=False)
            finally:
                await asyncio.to_thread(_close, bundle)
            await self.rollback()
            return sha, size, evaluation, []

    async def run_apply(self, job_id: int) -> str:
        """Применение проверенного архива."""
        job = await self.jobs.lock_job(job_id, kind=self.kind)
        if job is None or job.status != ImportJobStatus.APPLYING.value:
            await self.rollback()
            return "skipped"
        job_uuid, key, expected_sha = job.uuid, job.storage_key, job.file_sha256
        actor_id = job.committed_by_id or job.created_by_id
        await self.commit()
        assert key is not None and actor_id is not None

        uploaded: dict[str, UploadedFile] = {}
        used: set[str] = set()
        new_media_ids: list[int] = []
        try:
            with tempfile.TemporaryDirectory(prefix="oinau-bundle-") as directory:
                path = Path(directory) / "bundle.zip"
                await self._download(key, path)
                if await asyncio.to_thread(_sha256_file, path) != expected_sha:
                    raise _ApplyFailedError("import_file_mismatch")
                bundle = await asyncio.to_thread(_open_and_parse, path)
                try:
                    new_media_ids, used = await self._apply(
                        bundle, job_id, job_uuid, actor_id, uploaded
                    )
                finally:
                    await asyncio.to_thread(_close, bundle)
        except _RevalidationFailedError as failure:
            await self.rollback()
            await self._mark_failed(job_id, actor_id, "import_validation_failed", failure.result)
            await self._delete_objects([item.storage_key for item in uploaded.values()])
            return ImportJobStatus.FAILED.value
        except IntegrityError as exc:
            await self.rollback()
            domain = translate_integrity_error(exc, CATALOG_UNIQUE_ERRORS)
            await self._mark_failed(job_id, actor_id, domain.code if domain else "integrity_error")
            await self._delete_objects([item.storage_key for item in uploaded.values()])
            return ImportJobStatus.FAILED.value
        except Exception as exc:
            await self.rollback()
            code = (
                exc.code
                if isinstance(exc, _ApplyFailedError | AppError | BundleRejectedError)
                else "internal_error"
            )
            if not isinstance(exc, _ApplyFailedError | AppError | BundleRejectedError):
                logger.warning("bundle_apply_error", job_id=job_id, error=type(exc).__name__)
            await self._mark_failed(job_id, actor_id, code)
            await self._delete_objects([item.storage_key for item in uploaded.values()])
            return ImportJobStatus.FAILED.value

        # Загруженные на случай, но не понадобившиеся после повторной
        # проверки файлы (их успели загрузить через админку) — удаляются.
        await self._delete_objects(
            [item.storage_key for path, item in uploaded.items() if path not in used]
        )
        await self._delete_objects([key])
        for media_id in new_media_ids:
            await self._enqueue_media(media_id)
        return ImportJobStatus.COMMITTED.value

    async def _apply(
        self,
        bundle: _Bundle,
        job_id: int,
        job_uuid: UUID,
        actor_id: int,
        uploaded: dict[str, UploadedFile],
    ) -> tuple[list[int], set[str]]:
        # Сначала — проверка без блокировок и загрузка новых файлов:
        # это долго, и держать всё это время блокировку каталога нельзя.
        preliminary = await self._evaluate(bundle, lock=False)
        await self.rollback()
        if not preliminary.result.valid:
            raise _RevalidationFailedError(preliminary.result)
        await self._upload(bundle.archive, preliminary.plan.new_files, uploaded)

        await self.jobs.acquire_catalog_lock()
        job = await self.jobs.lock_job(job_id, kind=self.kind)
        if job is None or job.status != ImportJobStatus.APPLYING.value:
            raise _ApplyFailedError("import_bundle_state")

        evaluation = await self._evaluate(bundle, lock=True, checks=preliminary.checks)
        if not evaluation.result.valid:
            raise _RevalidationFailedError(evaluation.result)
        # Каталог мог измениться между проверками (файл удалили из
        # медиатеки) — догружаем недостающее. Обычно список пуст.
        await self._upload(bundle.archive, evaluation.plan.new_files, uploaded)

        await CatalogImportApplier(
            self.session,
            evaluation.snapshot,
            evaluation.result.plan,
            actor_id=actor_id,
            job_reference=str(job_uuid),
        ).apply()
        product_ids = await self._product_ids([*evaluation.plan.media, *evaluation.plan.stock])
        new_media_ids = await BundleApplier(
            self.session,
            evaluation.plan,
            evaluation.context,
            uploaded=uploaded,
            actor_id=actor_id,
            job_reference=str(job_uuid),
        ).apply(product_ids)

        job.status = ImportJobStatus.COMMITTED.value
        job.committed_at = datetime.now(UTC)
        self._fill(job, evaluation)
        summary = evaluation.result.summary()
        self._record(
            ImportAuditAction.COMMITTED,
            job,
            actor_id,
            {
                "job_uuid": str(job_uuid),
                "file_sha256": job.file_sha256,
                "rows_total": summary["rows_total"],
                "products": summary["products"],
                "categories": summary["categories"],
                "bundle": evaluation.plan.stats,
            },
        )
        await self.commit()
        return new_media_ids, set(evaluation.plan.new_files)

    async def _evaluate(
        self,
        bundle: _Bundle,
        *,
        lock: bool,
        checks: dict[str, FileCheck] | None = None,
    ) -> _Evaluation:
        workbook = bundle.workbook
        snapshot = await self.loader.load(_skus(workbook), lock_products=lock)
        validator = BundleImportValidator(
            workbook,
            snapshot,
            locales=settings.SUPPORTED_LOCALES,
            default_locale=settings.DEFAULT_LOCALE,
        )
        result = validator.validate()
        # Сверка с архивом — для всех разобранных товаров, в том числе
        # с ошибками в других колонках: так отчёт сразу показывает и
        # «нет категории», и «нет файла».
        products = list(validator.products.values())
        files = referenced_files(bundle.archive, products)
        known = dict(checks or {})
        missing = [item for path, item in files.items() if path not in known]
        if missing:
            known.update(await asyncio.to_thread(_check_files, bundle.archive, missing))
        context = await load_context(
            self.session,
            [plan.existing.id for plan in products if plan.existing is not None],
            [check.sha256 for check in known.values() if check.sha256],
        )
        sheet = workbook.sheets.get(Sheet.PRODUCTS)
        plan = BundlePlanner(
            products,
            bundle.archive,
            known,
            context,
            errors=result.errors,
            warnings=result.warnings,
            labels=sheet.labels if sheet is not None else {},
        ).build()
        relabel(result.errors, workbook)
        relabel(result.warnings, workbook)
        return _Evaluation(
            snapshot=snapshot, result=result, checks=known, context=context, plan=plan
        )

    async def _upload(
        self,
        archive: BundleArchive,
        files: dict[str, FileCheck],
        uploaded: dict[str, UploadedFile],
    ) -> None:
        pending = [(path, check) for path, check in files.items() if path not in uploaded]
        if not pending:
            return
        semaphore = asyncio.Semaphore(UPLOAD_CONCURRENCY)

        async def send(path: str, check: FileCheck) -> None:
            assert check.mime is not None
            limit = (
                settings.upload_max_document_size_bytes
                if check.file.folder == SCHEMES_DIR
                else settings.upload_max_size_bytes
            )
            async with semaphore:
                data = await asyncio.to_thread(read_checked, archive, check, limit=limit)
                media_uuid = uuid.uuid4()
                key = build_original_key(MediaPurpose.PRODUCT, media_uuid, check.mime)
                await self.storage.write(key, data, content_type=check.mime)
                uploaded[path] = UploadedFile(media_uuid=media_uuid, storage_key=key)

        await asyncio.gather(*(send(path, check) for path, check in pending))

    async def _product_ids(self, skus: list[str]) -> dict[str, int]:
        if not skus:
            return {}
        rows = await self.session.execute(
            select(Product.id, Product.sku).where(
                Product.sku.in_(sorted(set(skus))), Product.deleted_at.is_(None)
            )
        )
        return {row.sku: row.id for row in rows}

    async def _mark_failed(
        self,
        job_id: int,
        actor_id: int,
        code: str,
        result: ValidationResult | None = None,
    ) -> None:
        try:
            job = await self.jobs.lock_job(job_id, kind=self.kind)
            if job is None or job.status != ImportJobStatus.APPLYING.value:
                await self.rollback()
                return
            job.status = ImportJobStatus.FAILED.value
            job.failure_code = code
            if result is not None:
                job.error_count = result.errors.total
                job.warning_count = result.warnings.total
                job.errors = [issue.as_dict() for issue in result.errors.items]
                job.warnings = [issue.as_dict() for issue in result.warnings.items]
            self._record(
                ImportAuditAction.COMMIT_FAILED,
                job,
                actor_id,
                {"job_uuid": str(job.uuid), "failure_code": code},
            )
            await self.commit()
            if job.storage_key:
                await self._delete_objects([job.storage_key])
        except Exception as exc:
            await self.rollback()
            logger.warning("bundle_mark_failed_error", error=type(exc).__name__)

    # ============================================================= уборка
    async def cleanup(self, now: datetime | None = None) -> int:
        """Просроченные предпросмотры и зависшие задачи.

        Архив в хранилище не живёт дольше предпросмотра: не применённый
        за IMPORT_PREVIEW_TTL_HOURS импорт отменяется, архив удаляется.
        Задача, застрявшая в проверке или применении (воркер упал),
        помечается FAILED — повторить её можно новым импортом.
        """
        moment = now or datetime.now(UTC)
        ttl = timedelta(hours=settings.IMPORT_PREVIEW_TTL_HOURS)
        expired = await self.jobs.list_stale(
            kind=self.kind,
            statuses=(ImportJobStatus.UPLOADING.value, ImportJobStatus.VALID.value),
            before=moment - ttl,
            limit=CLEANUP_BATCH,
        )
        stuck = await self.jobs.list_stale(
            kind=self.kind,
            statuses=(ImportJobStatus.CHECKING.value, ImportJobStatus.APPLYING.value),
            before=moment - PROCESSING_TIMEOUT,
            limit=CLEANUP_BATCH,
        )
        keys: list[str] = []
        for job in expired:
            job.status = ImportJobStatus.CANCELLED.value
            job.failure_code = "import_preview_expired"
            keys.append(job.storage_key or "")
        for job in stuck:
            job.status = (
                ImportJobStatus.FAILED.value
                if job.status == ImportJobStatus.APPLYING.value
                else ImportJobStatus.INVALID.value
            )
            job.failure_code = "timeout"
            keys.append(job.storage_key or "")
        await self.commit()
        await self._delete_objects([key for key in keys if key])
        return len(expired) + len(stuck)

    # ========================================================== внутреннее
    async def _download(self, key: str, path: Path) -> int:
        with path.open("wb") as handle:
            return await self.storage.download(
                key, handle, max_bytes=settings.import_bundle_max_bytes
            )

    async def _enqueue_check(self, job_id: int) -> None:
        if self.queue is None:
            return
        try:
            await self.queue.enqueue_check(job_id)
        except Exception as exc:
            # Задача остаётся CHECKING: повторный запрос проверки поставит
            # её снова, а уборка через PROCESSING_TIMEOUT пометит упавшей.
            logger.warning("bundle_enqueue_failed", job_id=job_id, error=type(exc).__name__)

    async def _enqueue_apply(self, job_id: int) -> None:
        if self.queue is None:
            return
        try:
            await self.queue.enqueue_apply(job_id)
        except Exception as exc:
            logger.warning("bundle_enqueue_failed", job_id=job_id, error=type(exc).__name__)

    async def _enqueue_media(self, media_id: int) -> None:
        if self.media_queue is None:
            return
        try:
            await self.media_queue.enqueue_processing(media_id)
        except Exception as exc:
            logger.warning("media_enqueue_failed", media_id=media_id, error=type(exc).__name__)

    async def _delete_objects(self, keys: list[str]) -> None:
        keys = [key for key in keys if key]
        if not keys:
            return
        try:
            await self.storage.delete(keys)
        except Exception as exc:
            logger.warning("bundle_storage_delete_failed", error=type(exc).__name__)

    async def _require(self, job_uuid: UUID, *, for_update: bool = False) -> ImportJob:
        job = await self.jobs.get_by_uuid(job_uuid, kind=self.kind, for_update=for_update)
        if job is None:
            raise ImportJobNotFoundError
        return job

    def _record(
        self, action: str, job: ImportJob, actor_id: int | None, changes: dict[str, Any]
    ) -> None:
        self.audit.record(
            action=action,
            entity_type=IMPORT_JOB_ENTITY,
            entity_id=job.id,
            user_id=actor_id,
            actor="user" if actor_id is not None else "system",
            changes={"kind": job.kind, **changes},
        )

    def _reject(self, job: ImportJob, code: str, message: str) -> None:
        self._fill_rejected(job, [_book_issue(code, message)])

    @staticmethod
    def _fill_rejected(job: ImportJob, issues: list[Issue]) -> None:
        job.status = ImportJobStatus.INVALID.value
        job.error_count = len(issues)
        job.warning_count = 0
        job.errors = [issue.as_dict() for issue in issues]
        job.warnings = []
        job.summary = {}

    def _fill(self, job: ImportJob, evaluation: _Evaluation) -> None:
        result = evaluation.result
        summary = result.summary()
        products = summary["products"]
        job.rows_total = result.rows_total
        job.products_created = products["create"]
        job.products_updated = products["update"]
        job.products_unchanged = products["unchanged"]
        job.error_count = result.errors.total
        job.warning_count = result.warnings.total
        changes = result.product_changes()
        job.summary = {
            **summary,
            "bundle": evaluation.plan.stats,
            "changes": changes[:MAX_REPORTED_CHANGES],
            "changes_total": len(changes),
        }
        job.errors = [issue.as_dict() for issue in result.errors.items]
        job.warnings = [issue.as_dict() for issue in result.warnings.items]

    @staticmethod
    def _expires_at(job: ImportJob) -> datetime:
        return job.created_at + timedelta(hours=settings.IMPORT_PREVIEW_TTL_HOURS)

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

    def _to_read(self, job: ImportJob) -> BundleJobRead:
        summary = job.summary or {}
        changes = summary.get("changes") or []
        return BundleJobRead(
            **self._to_list_item(job).model_dump(),
            summary=ImportSummaryRead.model_validate(summary),
            bundle=BundleStatsRead.model_validate(summary.get("bundle") or {}),
            errors=[ImportIssueRead.model_validate(item) for item in job.errors or []],
            warnings=[ImportIssueRead.model_validate(item) for item in job.warnings or []],
            changes=[ProductChangeRead.model_validate(item) for item in changes],
            changes_truncated=int(summary.get("changes_total") or 0) > len(changes),
            can_cancel=job.status in _CANCELLABLE,
        )


class _ApplyFailedError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _book_issue(code: str, message: str) -> Issue:
    return Issue(sheet=None, row=None, column=None, code=code, message=message)


def _skus(workbook: ParsedWorkbook) -> list[str]:
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


def relabel(issues: IssueCollector, workbook: ParsedWorkbook) -> None:
    """Имена колонок и листа в отчёте — как в файле пользователя."""
    sheet = workbook.sheets.get(Sheet.PRODUCTS)
    if sheet is None:
        return
    for index, issue in enumerate(issues.items):
        if issue.sheet != Sheet.PRODUCTS:
            continue
        issues.items[index] = replace(
            issue,
            sheet=sheet.title or issue.sheet,
            column=sheet.labels.get(issue.column, issue.column) if issue.column else None,
        )


__all__ = [
    "APPLY_TASK",
    "CHECK_TASK",
    "BundleImportService",
    "BundleQueue",
    "bundle_storage_key",
    "get_bundle_queue",
]
