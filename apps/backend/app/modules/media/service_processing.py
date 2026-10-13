"""Обработка загруженного файла — выполняется воркером.

PROCESSING -> READY: оригинал декодирован, построены WebP-варианты,
записаны размеры и контрольная сумма. Для документа (PDF, DWG, DXF)
вместо вариантов — проверка сигнатуры и публичная копия
`variants/file.<ext>`; содержимое документа не интерпретируется.
PROCESSING -> FAILED: файл не декодируется или слишком велик в пикселях;
объекты удаляются из хранилища.

Операция идемпотентна: файл не в статусе PROCESSING пропускается,
а строка берётся с SKIP LOCKED — повторная постановка в очередь
не приведёт к двойной обработке.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.service import BaseService
from app.infrastructure.storage.base import ObjectStorage
from app.modules.audit.service import AuditService
from app.modules.media.audit import MEDIA_ENTITY, SYSTEM_ACTOR, MediaAuditAction
from app.modules.media.documents import (
    DOCUMENT_VARIANT,
    content_disposition,
    document_variant_key,
    is_document,
    sniff_document_mime,
)
from app.modules.media.enums import MediaFailureReason, MediaStatus
from app.modules.media.images import (
    VARIANT_EXTENSION,
    VARIANT_MIME,
    ImageRejectedError,
    process_image,
)
from app.modules.media.models import MediaFile
from app.modules.media.repository_admin import AdminMediaRepository

logger = get_logger(__name__)

# Ключи иммутабельны (UUID в пути), поэтому кэш CDN может быть вечным.
VARIANT_CACHE_CONTROL = "public, max-age=31536000, immutable"


def variant_key(media: MediaFile, name: str) -> str:
    """`products/{uuid}/variants/large.webp` — рядом с оригиналом.

    Префикс `.../variants/` — единственное, что политика бакета отдаёт
    анонимно; оригинал рядом остаётся приватным.
    """
    base = media.storage_key.rsplit("/", 1)[0]
    return f"{base}/variants/{name}.{VARIANT_EXTENSION}"


class MediaProcessingService(BaseService):
    def __init__(self, session: AsyncSession, *, storage: ObjectStorage) -> None:
        super().__init__(session)
        self.repository = AdminMediaRepository(session)
        self.audit = AuditService(session)
        self.storage = storage

    async def process(self, media_id: int) -> str:
        """Возвращает итоговый статус (или `skipped`)."""
        media = await self.repository.lock_for_processing(media_id)
        if media is None or media.status != MediaStatus.PROCESSING.value:
            await self.rollback()
            return "skipped"

        if is_document(media.mime_type):
            return await self._process_document(media)

        written: list[str] = []
        try:
            original = await self.storage.read(media.storage_key)
            processed = await asyncio.to_thread(
                process_image,
                original,
                mime_type=media.mime_type,
                max_pixels=settings.UPLOAD_MAX_IMAGE_PIXELS,
            )
            variants: dict[str, Any] = {}
            for variant in processed.variants:
                key = variant_key(media, variant.name)
                await self.storage.write(
                    key,
                    variant.data,
                    content_type=VARIANT_MIME,
                    cache_control=VARIANT_CACHE_CONTROL,
                )
                written.append(key)
                variants[variant.name] = {"key": key, "w": variant.width, "h": variant.height}
        except ImageRejectedError as exc:
            return await self._fail(media, exc.reason, written)
        except Exception as exc:
            # Сбой хранилища или непредвиденная ошибка декодера. Файл
            # не остаётся навечно в PROCESSING: администратор увидит
            # FAILED и загрузит его заново.
            logger.warning("media_processing_error", media_id=media.id, error=type(exc).__name__)
            return await self._fail(media, MediaFailureReason.PROCESSING_ERROR, written)

        media.status = MediaStatus.READY.value
        media.width = processed.width
        media.height = processed.height
        media.checksum = hashlib.sha256(original).hexdigest()
        media.variants = variants
        media.failure_reason = None
        self.audit.record(
            action=MediaAuditAction.PROCESSED,
            entity_type=MEDIA_ENTITY,
            entity_id=media.id,
            actor=SYSTEM_ACTOR,
            changes={
                "status": {"old": MediaStatus.PROCESSING.value, "new": media.status},
                "width": media.width,
                "height": media.height,
                "variants": sorted(variants),
            },
        )
        await self.commit()
        return media.status

    async def _process_document(self, media: MediaFile) -> str:
        """Документ: сигнатура ещё раз и публичная копия рядом с оригиналом.

        Копия, а не публичный оригинал: политика бакета открывает только
        `*/variants/*`, и это правило не меняется ради одного типа файлов.
        """
        written: list[str] = []
        try:
            original = await self.storage.read(media.storage_key)
            if not original:
                return await self._fail(media, MediaFailureReason.EMPTY_FILE, written)
            if len(original) > settings.upload_max_document_size_bytes:
                return await self._fail(media, MediaFailureReason.SIZE_EXCEEDED, written)
            if sniff_document_mime(original[:64]) != media.mime_type:
                return await self._fail(media, MediaFailureReason.TYPE_MISMATCH, written)
            key = document_variant_key(media.storage_key, media.mime_type)
            await self.storage.write(
                key,
                original,
                content_type=media.mime_type,
                cache_control=VARIANT_CACHE_CONTROL,
                content_disposition=content_disposition(media.mime_type, media.original_filename),
            )
            written.append(key)
        except Exception as exc:
            logger.warning("media_processing_error", media_id=media.id, error=type(exc).__name__)
            return await self._fail(media, MediaFailureReason.PROCESSING_ERROR, written)

        media.status = MediaStatus.READY.value
        media.size_bytes = len(original)
        media.checksum = hashlib.sha256(original).hexdigest()
        media.variants = {DOCUMENT_VARIANT: {"key": key, "size": len(original)}}
        media.failure_reason = None
        self.audit.record(
            action=MediaAuditAction.PROCESSED,
            entity_type=MEDIA_ENTITY,
            entity_id=media.id,
            actor=SYSTEM_ACTOR,
            changes={
                "status": {"old": MediaStatus.PROCESSING.value, "new": media.status},
                "variants": [DOCUMENT_VARIANT],
            },
        )
        await self.commit()
        return media.status

    async def _fail(self, media: MediaFile, reason: MediaFailureReason, written: list[str]) -> str:
        media.status = MediaStatus.FAILED.value
        media.failure_reason = reason.value
        self.audit.record(
            action=MediaAuditAction.PROCESSING_FAILED,
            entity_type=MEDIA_ENTITY,
            entity_id=media.id,
            actor=SYSTEM_ACTOR,
            changes={"failure_reason": reason.value},
        )
        await self.commit()
        try:
            await self.storage.delete([media.storage_key, *written])
        except Exception as exc:
            logger.warning(
                "media_storage_delete_failed", media_id=media.id, error=type(exc).__name__
            )
        return media.status
