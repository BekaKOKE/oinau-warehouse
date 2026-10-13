"""Admin API: экспорт и импорт каталога в XLSX — /api/v1/admin/catalog.

Права — из существующей матрицы RBAC, новых не вводится:
  * экспорт, шаблон, предпросмотр и история — `catalog.read`;
  * подтверждение импорта (изменение каталога) — `catalog.write`.
Предпросмотр каталог не меняет, поэтому доступен и тем, у кого нет
права записи: проверить файл может любой, применить — только редактор
каталога. У роли MANAGER права `catalog.write` нет — импортировать
каталог она не может.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import SessionDep, rate_limit, require_permissions
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams
from app.modules.imports.enums import ImportJobStatus
from app.modules.imports.export import CatalogExportService, export_filename
from app.modules.imports.schemas import (
    ImportCommitRead,
    ImportJobListItem,
    ImportJobRead,
    ImportPreviewRead,
)
from app.modules.imports.service import CatalogImportService
from app.modules.imports.upload import read_xlsx_upload
from app.modules.imports.xlsx_format import XLSX_MIME
from app.modules.users.models import User
from app.modules.users.permissions import CATALOG_READ, CATALOG_WRITE

CatalogReader = Annotated[User, Depends(require_permissions(CATALOG_READ))]
CatalogWriter = Annotated[User, Depends(require_permissions(CATALOG_WRITE))]

router = APIRouter(prefix="/catalog", tags=["admin:catalog-excel"])

_XLSX_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {"content": {XLSX_MIME: {}}, "description": "Книга XLSX"}
}
_UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}
_import_rate_limit = Depends(rate_limit("catalog_import", "RATE_LIMIT_CATALOG_IMPORT"))


def _xlsx(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/export",
    response_class=Response,
    responses=_XLSX_RESPONSE,
    summary="Экспорт каталога в XLSX",
)
async def export_catalog(session: SessionDep, _: CatalogReader) -> Response:
    """Живые товары и категории, характеристики, цены публичного
    прайс-листа. Без остатков и без ключей медиатеки. Файл можно
    отредактировать и вернуть через импорт."""
    return _xlsx(await CatalogExportService(session).export_catalog(), export_filename())


@router.get(
    "/imports/template",
    response_class=Response,
    responses=_XLSX_RESPONSE,
    summary="Пустой шаблон XLSX",
)
async def import_template(session: SessionDep, _: CatalogReader) -> Response:
    return _xlsx(await CatalogExportService(session).template(), "oinau-catalog-template.xlsx")


@router.post(
    "/imports/preview",
    response_model=ImportPreviewRead,
    summary="Предпросмотр импорта",
    dependencies=[_import_rate_limit],
    openapi_extra=_UPLOAD_BODY,
)
async def preview_import(
    request: Request, session: SessionDep, actor: CatalogReader
) -> ImportPreviewRead:
    """Проверяет файл и показывает, что будет создано и изменено.
    Каталог не меняется. Ошибки данных — в теле ответа (200, valid=false),
    отказ принять файл целиком — ошибкой 413/415/422."""
    upload = await read_xlsx_upload(request)
    return await CatalogImportService(session).preview(upload, actor)


@router.post(
    "/imports/{job_uuid}/commit",
    response_model=ImportCommitRead,
    summary="Подтвердить импорт",
    dependencies=[_import_rate_limit],
    openapi_extra=_UPLOAD_BODY,
)
async def commit_import(
    job_uuid: UUID, request: Request, session: SessionDep, actor: CatalogWriter
) -> ImportCommitRead:
    """Тот же файл, что был на предпросмотре (сверяется SHA-256).
    Проверяется заново и применяется целиком одной транзакцией.
    Повторное подтверждение того же импорта — 409."""
    upload = await read_xlsx_upload(request)
    return await CatalogImportService(session).commit_import(job_uuid, upload, actor)


@router.get("/imports", response_model=Page[ImportJobListItem], summary="История импортов")
async def list_imports(
    session: SessionDep,
    _: CatalogReader,
    job_status: Annotated[ImportJobStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[ImportJobListItem]:
    return await CatalogImportService(session).list_jobs(
        status=job_status, params=PageParams(page=page, page_size=page_size)
    )


@router.get("/imports/{job_uuid}", response_model=ImportJobRead, summary="Импорт с ошибками")
async def get_import(job_uuid: UUID, session: SessionDep, _: CatalogReader) -> ImportJobRead:
    return await CatalogImportService(session).get_job(job_uuid)
