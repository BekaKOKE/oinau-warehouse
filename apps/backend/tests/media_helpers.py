"""Подмены хранилища и очереди, генераторы изображений для тестов медиатеки.

Настоящие R2/MinIO и arq в тестах не участвуют: хранилище живёт
в памяти, очередь только запоминает поставленные задачи, а «воркер»
вызывается напрямую — тем же сервисом, что и в проде.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, BinaryIO
from urllib.parse import urlsplit

from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.infrastructure.storage.base import ObjectTooLargeError, PresignedUpload, StoredObject
from app.modules.media.enums import MediaStatus
from app.modules.media.models import MediaFile
from app.modules.media.service_processing import MediaProcessingService

MEDIA_URL = "/api/v1/admin/media"
FAKE_STORAGE_HOST = "https://storage.test"


class InMemoryObjectStorage:
    """ObjectStorage в памяти. Ведёт журнал операций для проверок."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, str | None]] = {}
        self.deleted: list[str] = []
        self.presigned: list[str] = []
        self.dispositions: dict[str, str] = {}

    async def create_upload_url(
        self, key: str, *, content_type: str, expires_in: int
    ) -> PresignedUpload:
        self.presigned.append(key)
        return PresignedUpload(
            url=f"{FAKE_STORAGE_HOST}/bucket/{key}?X-Amz-Signature=fake",
            method="PUT",
            expires_in=expires_in,
            headers={"Content-Type": content_type},
        )

    async def stat(self, key: str) -> StoredObject | None:
        item = self.objects.get(key)
        return StoredObject(size=len(item[0]), content_type=item[1]) if item else None

    async def read(self, key: str, *, max_bytes: int | None = None) -> bytes:
        data = self.objects[key][0]
        return data[:max_bytes] if max_bytes is not None else data

    async def download(self, key: str, target: BinaryIO, *, max_bytes: int) -> int:
        data = self.objects[key][0]
        if len(data) > max_bytes:
            raise ObjectTooLargeError(key)
        target.write(data)
        return len(data)

    async def write(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        cache_control: str | None = None,
        content_disposition: str | None = None,
    ) -> None:
        self.objects[key] = (data, content_type, cache_control)
        if content_disposition is not None:
            self.dispositions[key] = content_disposition
        else:
            self.dispositions.pop(key, None)

    async def delete(self, keys: Sequence[str]) -> None:
        for key in keys:
            self.deleted.append(key)
            self.objects.pop(key, None)

    # ------------------------------------------------------------ для тестов
    def put_by_url(self, url: str, data: bytes, content_type: str) -> str:
        """То, что делает браузер: PUT по presigned URL."""
        key = urlsplit(url).path.removeprefix("/bucket/")
        self.objects[key] = (data, content_type, None)
        return key


class FakeMediaQueue:
    def __init__(self) -> None:
        self.enqueued: list[int] = []
        # True — очередь недоступна (Redis лежит).
        self.broken = False

    async def enqueue_processing(self, media_id: int) -> None:
        if self.broken:
            raise ConnectionError("redis is down")
        self.enqueued.append(media_id)


# ------------------------------------------------------------ изображения


def image_bytes(
    fmt: str = "PNG",
    size: tuple[int, int] = (64, 48),
    color: tuple[int, int, int] = (200, 30, 30),
    **save_kwargs: Any,
) -> bytes:
    buffer = BytesIO()
    mode = "RGBA" if fmt == "PNG" else "RGB"
    Image.new(mode, size, color).save(buffer, format=fmt, **save_kwargs)
    return buffer.getvalue()


def png_bytes(size: tuple[int, int] = (64, 48)) -> bytes:
    return image_bytes("PNG", size)


def jpeg_bytes(size: tuple[int, int] = (64, 48), **save_kwargs: Any) -> bytes:
    return image_bytes("JPEG", size, **save_kwargs)


# --------------------------------------------------------------- потоки


async def run_worker(engine: AsyncEngine, storage: InMemoryObjectStorage, media_id: int) -> str:
    """Выполняет задачу воркера в отдельной сессии — как в проде."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        return await MediaProcessingService(session, storage=storage).process(media_id)


async def media_id_by_uuid(engine: AsyncEngine, media_uuid: str) -> int:
    from sqlalchemy import select

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        return int(
            (
                await session.execute(
                    select(MediaFile.id).where(MediaFile.uuid == uuid.UUID(media_uuid))
                )
            ).scalar_one()
        )


async def upload(
    api: AsyncClient,
    headers: dict[str, str],
    storage: InMemoryObjectStorage,
    *,
    data: bytes,
    content_type: str = "image/png",
    filename: str = "photo.png",
    purpose: str | None = None,
) -> dict[str, Any]:
    """Шаги 1–3 потока загрузки: intent, PUT в хранилище, complete."""
    body: dict[str, Any] = {
        "filename": filename,
        "content_type": content_type,
        "size_bytes": len(data),
    }
    if purpose:
        body["purpose"] = purpose
    intent = await api.post(f"{MEDIA_URL}/upload-intent", headers=headers, json=body)
    assert intent.status_code == 201, intent.text
    created = intent.json()
    storage.put_by_url(created["upload"]["url"], data, content_type)
    complete = await api.post(f"{MEDIA_URL}/{created['media']['uuid']}/complete", headers=headers)
    assert complete.status_code == 202, complete.text
    return complete.json()


async def upload_ready(
    api: AsyncClient,
    headers: dict[str, str],
    storage: InMemoryObjectStorage,
    engine: AsyncEngine,
    *,
    data: bytes | None = None,
    filename: str = "photo.png",
    purpose: str | None = None,
) -> dict[str, Any]:
    """Полный цикл до READY: загрузка + обработка воркером."""
    media = await upload(
        api, headers, storage, data=data or png_bytes(), filename=filename, purpose=purpose
    )
    await run_worker(engine, storage, await media_id_by_uuid(engine, media["uuid"]))
    response = await api.get(f"{MEDIA_URL}/{media['uuid']}", headers=headers)
    assert response.json()["status"] == "READY", response.text
    return response.json()


async def make_media(
    session: AsyncSession, *, status: MediaStatus = MediaStatus.READY, **kwargs: Any
) -> MediaFile:
    """Запись медиатеки напрямую в БД — для массовых сценариев."""
    media_uuid = uuid.uuid4()
    key = f"products/{media_uuid}/original.png"
    variants = (
        {
            "large": {"key": f"products/{media_uuid}/variants/large.webp", "w": 64, "h": 48},
            "thumb": {"key": f"products/{media_uuid}/variants/thumb.webp", "w": 64, "h": 48},
        }
        if status is MediaStatus.READY
        else {}
    )
    media = MediaFile(
        uuid=media_uuid,
        storage_key=key,
        bucket="oinau-media",
        mime_type="image/png",
        size_bytes=1024,
        status=status.value,
        original_filename=kwargs.pop("original_filename", "photo.png"),
        variants=kwargs.pop("variants", variants),
        width=64 if status is MediaStatus.READY else None,
        height=48 if status is MediaStatus.READY else None,
        created_at=datetime.now(UTC),
        **kwargs,
    )
    session.add(media)
    await session.flush()
    return media
