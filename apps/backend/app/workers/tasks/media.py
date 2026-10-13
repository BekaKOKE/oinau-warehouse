"""Задачи воркера медиатеки."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.infrastructure.storage.s3 import get_object_storage
from app.modules.media.service_processing import MediaProcessingService

logger = get_logger(__name__)


async def process_media(_ctx: dict[str, Any], media_id: int) -> str:
    """Проверка файла и построение публичных вариантов."""
    async with SessionFactory() as session:
        result = await MediaProcessingService(session, storage=get_object_storage()).process(
            media_id
        )
    logger.info("media_processed", media_id=media_id, result=result)
    return result
