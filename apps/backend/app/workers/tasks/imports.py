"""Задачи воркера пакетного импорта каталога (ZIP)."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.infrastructure.storage.s3 import get_object_storage
from app.modules.imports.bundle_service import BundleImportService, get_bundle_queue
from app.modules.media.queue import get_media_queue

logger = get_logger(__name__)


def _service(session: Any) -> BundleImportService:
    return BundleImportService(
        session,
        storage=get_object_storage(),
        queue=get_bundle_queue(),
        media_queue=get_media_queue(),
    )


async def check_catalog_bundle(_ctx: dict[str, Any], job_id: int) -> str:
    """Проверка архива: предпросмотр без изменения каталога."""
    async with SessionFactory() as session:
        result = await _service(session).run_check(job_id)
    logger.info("catalog_bundle_checked", job_id=job_id, result=result)
    return result


async def apply_catalog_bundle(_ctx: dict[str, Any], job_id: int) -> str:
    """Применение проверенного архива."""
    async with SessionFactory() as session:
        result = await _service(session).run_apply(job_id)
    logger.info("catalog_bundle_applied", job_id=job_id, result=result)
    return result


async def cleanup_catalog_bundles(_ctx: dict[str, Any]) -> int:
    """Просроченные предпросмотры и зависшие задачи; архивы удаляются."""
    async with SessionFactory() as session:
        count = await _service(session).cleanup()
    if count:
        logger.info("catalog_bundles_cleaned", count=count)
    return count
