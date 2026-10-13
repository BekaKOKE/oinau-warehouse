"""Помощники тестов пакетного импорта: сборка архивов, загрузка, «воркер»."""

from __future__ import annotations

import stat
import zipfile
from collections.abc import Sequence
from io import BytesIO
from typing import Any

from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.modules.imports.bundle_service import BundleImportService
from app.modules.imports.models import ImportJob
from tests.media_helpers import FakeMediaQueue, InMemoryObjectStorage, jpeg_bytes, png_bytes

BUNDLES = "/api/v1/admin/catalog/bundle-imports"
PDF_BYTES = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
DWG_BYTES = b"AC1032" + b"\x00" * 64
DXF_BYTES = b"  0\nSECTION\n  2\nHEADER\n  0\nENDSEC\n  0\nEOF\n"


class FakeBundleQueue:
    def __init__(self) -> None:
        self.checks: list[int] = []
        self.applies: list[int] = []

    async def enqueue_check(self, job_id: int) -> None:
        self.checks.append(job_id)

    async def enqueue_apply(self, job_id: int) -> None:
        self.applies.append(job_id)


def workbook_bytes(
    rows: Sequence[dict[str, Any]],
    *,
    title: str = "Товары",
    headers: Sequence[str] | None = None,
    extra_sheets: dict[str, list[list[Any]]] | None = None,
) -> bytes:
    """Книга с одним листом товаров: заголовки — ключи строк (или `headers`)."""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = title
    columns = list(headers or dict.fromkeys(key for row in rows for key in row))
    sheet.append(columns)
    for row in rows:
        sheet.append([row.get(column) for column in columns])
    for name, values in (extra_sheets or {}).items():
        extra = workbook.create_sheet(name)
        for line in values:
            extra.append(line)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def make_bundle(
    rows: Sequence[dict[str, Any]] | None = None,
    files: dict[str, bytes] | None = None,
    *,
    workbook: bytes | None = None,
    workbook_name: str = "products.xlsx",
    raw_entries: Sequence[tuple[zipfile.ZipInfo, bytes]] = (),
) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if workbook is not None or rows is not None:
            archive.writestr(workbook_name, workbook or workbook_bytes(rows or []))
        for path, data in (files or {}).items():
            archive.writestr(path, data)
        for info, data in raw_entries:
            archive.writestr(info, data)
    return buffer.getvalue()


def symlink_entry(name: str, target: str) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info, target.encode()


def photo(color: tuple[int, int, int] = (200, 30, 30), size: tuple[int, int] = (64, 48)) -> bytes:
    from tests.media_helpers import image_bytes

    return image_bytes("JPEG", size, color)


async def create_job(
    api: AsyncClient,
    headers: dict[str, str],
    storage: InMemoryObjectStorage,
    data: bytes,
    *,
    filename: str = "catalog.zip",
) -> dict[str, Any]:
    """Шаги 1–2: ссылка на загрузку и PUT архива в хранилище."""
    response = await api.post(
        BUNDLES, headers=headers, json={"filename": filename, "size_bytes": len(data)}
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    storage.put_by_url(created["upload"]["url"], data, "application/zip")
    return created["job"]


def _service(
    session: Any, storage: InMemoryObjectStorage, media_queue: FakeMediaQueue | None = None
) -> BundleImportService:
    return BundleImportService(
        session, storage=storage, queue=FakeBundleQueue(), media_queue=media_queue
    )


async def job_id(engine: AsyncEngine, job_uuid: str) -> int:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        return int(
            (
                await session.execute(select(ImportJob.id).where(ImportJob.uuid == job_uuid))
            ).scalar_one()
        )


async def run_check(engine: AsyncEngine, storage: InMemoryObjectStorage, job_uuid: str) -> str:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        return await _service(session, storage).run_check(await job_id(engine, job_uuid))


async def run_apply(
    engine: AsyncEngine,
    storage: InMemoryObjectStorage,
    job_uuid: str,
    media_queue: FakeMediaQueue | None = None,
) -> str:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        return await _service(session, storage, media_queue).run_apply(
            await job_id(engine, job_uuid)
        )


async def check_bundle(
    api: AsyncClient,
    headers: dict[str, str],
    storage: InMemoryObjectStorage,
    engine: AsyncEngine,
    data: bytes,
) -> dict[str, Any]:
    """Загрузка + проверка воркером. Возвращает задачу после проверки."""
    job = await create_job(api, headers, storage, data)
    response = await api.post(f"{BUNDLES}/{job['uuid']}/check", headers=headers)
    assert response.status_code == 202, response.text
    await run_check(engine, storage, job["uuid"])
    result = await api.get(f"{BUNDLES}/{job['uuid']}", headers=headers)
    assert result.status_code == 200, result.text
    body: dict[str, Any] = result.json()
    return body


async def apply_bundle(
    api: AsyncClient,
    headers: dict[str, str],
    storage: InMemoryObjectStorage,
    engine: AsyncEngine,
    job: dict[str, Any],
    media_queue: FakeMediaQueue | None = None,
) -> dict[str, Any]:
    response = await api.post(f"{BUNDLES}/{job['uuid']}/commit", headers=headers)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "APPLYING"
    await run_apply(engine, storage, job["uuid"], media_queue)
    result = await api.get(f"{BUNDLES}/{job['uuid']}", headers=headers)
    body: dict[str, Any] = result.json()
    return body


async def import_bundle(
    api: AsyncClient,
    headers: dict[str, str],
    storage: InMemoryObjectStorage,
    engine: AsyncEngine,
    data: bytes,
    media_queue: FakeMediaQueue | None = None,
) -> dict[str, Any]:
    """Полный цикл: загрузка, проверка без ошибок, применение."""
    job = await check_bundle(api, headers, storage, engine, data)
    assert job["status"] == "VALID", job["errors"]
    applied = await apply_bundle(api, headers, storage, engine, job, media_queue)
    assert applied["status"] == "COMMITTED", applied
    return applied


def messages(job: dict[str, Any], key: str = "errors") -> list[str]:
    return [item["message"] for item in job[key]]


__all__ = [
    "BUNDLES",
    "DWG_BYTES",
    "DXF_BYTES",
    "PDF_BYTES",
    "FakeBundleQueue",
    "apply_bundle",
    "check_bundle",
    "create_job",
    "import_bundle",
    "jpeg_bytes",
    "make_bundle",
    "messages",
    "photo",
    "png_bytes",
    "run_apply",
    "run_check",
    "symlink_entry",
    "workbook_bytes",
]
