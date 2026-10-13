"""Admin API: пакетный импорт каталога (ZIP) — /api/v1/admin/catalog/bundle-imports.

Права — из существующей матрицы RBAC:
  * история, статус, отчёт, шаблон и пример — `catalog.read`;
  * загрузка архива, проверка, применение и отмена — `catalog.write`
    и `media.upload`: архив ложится в хранилище, а применение создаёт
    файлы медиатеки. У MANAGER и VIEWER этих прав нет.

Проверка и применение выполняются воркером (arq). Ответ на /check и
/commit — задача в статусе CHECKING / APPLYING; админка опрашивает
GET /{uuid}, пока статус не станет итоговым.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import SessionDep, rate_limit, require_permissions
from app.core.config import settings
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams
from app.infrastructure.storage.base import ObjectStorage
from app.infrastructure.storage.s3 import get_object_storage
from app.modules.imports.bundle_schemas import (
    BUNDLE_CONTENT_TYPE,
    BundleJobRead,
    BundleUploadCreate,
    BundleUploadCreated,
)
from app.modules.imports.bundle_service import (
    BundleImportService,
    BundleQueue,
    get_bundle_queue,
)
from app.modules.imports.bundle_template import build_example_zip, build_report, build_template
from app.modules.imports.enums import ImportJobStatus
from app.modules.imports.export import export_filename
from app.modules.imports.schemas import ImportJobListItem
from app.modules.imports.xlsx_format import XLSX_MIME
from app.modules.media.queue import MediaQueue, get_media_queue
from app.modules.users.models import User
from app.modules.users.permissions import CATALOG_READ, CATALOG_WRITE, MEDIA_UPLOAD

CatalogReader = Annotated[User, Depends(require_permissions(CATALOG_READ))]
BundleWriter = Annotated[User, Depends(require_permissions(CATALOG_WRITE, MEDIA_UPLOAD))]
StorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]
QueueDep = Annotated[BundleQueue, Depends(get_bundle_queue)]
MediaQueueDep = Annotated[MediaQueue, Depends(get_media_queue)]

router = APIRouter(prefix="/catalog/bundle-imports", tags=["admin:catalog-bundle"])

_import_rate_limit = Depends(rate_limit("catalog_import", "RATE_LIMIT_CATALOG_IMPORT"))
_XLSX_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {"content": {XLSX_MIME: {}}, "description": "Книга XLSX"}
}
_ZIP_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {"content": {BUNDLE_CONTENT_TYPE: {}}, "description": "ZIP-архив"}
}


def _service(
    session: SessionDep, storage: ObjectStorage, queue: BundleQueue, media_queue: MediaQueue
) -> BundleImportService:
    return BundleImportService(session, storage=storage, queue=queue, media_queue=media_queue)


def _download(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/template",
    response_class=Response,
    responses=_XLSX_RESPONSE,
    summary="Шаблон книги для ZIP-импорта",
)
async def bundle_template(_: CatalogReader) -> Response:
    return _download(build_template(), XLSX_MIME, "products.xlsx")


@router.get(
    "/example",
    response_class=Response,
    responses=_ZIP_RESPONSE,
    summary="Пример ZIP-архива",
)
async def bundle_example(_: CatalogReader) -> Response:
    return _download(build_example_zip(), BUNDLE_CONTENT_TYPE, "oinau-import-example.zip")


@router.post(
    "",
    response_model=BundleUploadCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Начать импорт: ссылка на загрузку архива",
    dependencies=[_import_rate_limit],
)
async def create_bundle_import(
    payload: BundleUploadCreate,
    session: SessionDep,
    actor: BundleWriter,
    storage: StorageDep,
    queue: QueueDep,
    media_queue: MediaQueueDep,
) -> BundleUploadCreated:
    """Архив загружается браузером PUT-запросом по выданной ссылке прямо
    в приватный префикс хранилища — мимо API и лимита тела на прокси."""
    return await _service(session, storage, queue, media_queue).create_upload(payload, actor)


@router.post(
    "/{job_uuid}/check",
    response_model=BundleJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Проверить загруженный архив",
)
async def check_bundle_import(
    job_uuid: UUID,
    session: SessionDep,
    actor: BundleWriter,
    storage: StorageDep,
    queue: QueueDep,
    media_queue: MediaQueueDep,
) -> BundleJobRead:
    """Каталог не меняется. Итог — статус VALID или INVALID с отчётом."""
    service = _service(session, storage, queue, media_queue)
    job = await service.start_check(job_uuid, actor)
    if settings.IMPORT_BUNDLE_INLINE and job.status is ImportJobStatus.CHECKING:
        await service.run_check((await service.get_job_model(job_uuid)).id)
        job = await service.get_job(job_uuid)
    return job


@router.post(
    "/{job_uuid}/commit",
    response_model=BundleJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Применить проверенный архив",
    dependencies=[_import_rate_limit],
)
async def commit_bundle_import(
    job_uuid: UUID,
    session: SessionDep,
    actor: BundleWriter,
    storage: StorageDep,
    queue: QueueDep,
    media_queue: MediaQueueDep,
) -> BundleJobRead:
    """Архив проверяется заново по свежему состоянию каталога и применяется
    целиком одной транзакцией. Повторное применение — 409."""
    service = _service(session, storage, queue, media_queue)
    job = await service.commit_import(job_uuid, actor)
    if settings.IMPORT_BUNDLE_INLINE and job.status is ImportJobStatus.APPLYING:
        await service.run_apply((await service.get_job_model(job_uuid)).id)
        job = await service.get_job(job_uuid)
    return job


@router.delete("/{job_uuid}", response_model=BundleJobRead, summary="Отменить импорт")
async def cancel_bundle_import(
    job_uuid: UUID,
    session: SessionDep,
    actor: BundleWriter,
    storage: StorageDep,
    queue: QueueDep,
    media_queue: MediaQueueDep,
) -> BundleJobRead:
    """До применения. Архив удаляется из хранилища."""
    return await _service(session, storage, queue, media_queue).cancel(job_uuid, actor)


@router.get("", response_model=Page[ImportJobListItem], summary="История ZIP-импортов")
async def list_bundle_imports(
    session: SessionDep,
    _: CatalogReader,
    storage: StorageDep,
    job_status: Annotated[ImportJobStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[ImportJobListItem]:
    return await BundleImportService(session, storage=storage).list_jobs(
        status=job_status, params=PageParams(page=page, page_size=page_size)
    )


@router.get("/{job_uuid}", response_model=BundleJobRead, summary="Статус и отчёт ZIP-импорта")
async def get_bundle_import(
    job_uuid: UUID, session: SessionDep, _: CatalogReader, storage: StorageDep
) -> BundleJobRead:
    return await BundleImportService(session, storage=storage).get_job(job_uuid)


@router.get(
    "/{job_uuid}/report",
    response_class=Response,
    responses=_XLSX_RESPONSE,
    summary="Отчёт ZIP-импорта в XLSX",
)
async def bundle_import_report(
    job_uuid: UUID, session: SessionDep, _: CatalogReader, storage: StorageDep
) -> Response:
    job = await BundleImportService(session, storage=storage).get_job_model(job_uuid)
    return _download(build_report(job), XLSX_MIME, export_filename("oinau-import-report"))
