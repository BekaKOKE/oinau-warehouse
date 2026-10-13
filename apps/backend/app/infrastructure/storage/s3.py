"""Реализация ObjectStorage поверх S3 API.

Работает одинаково с Cloudflare R2 и MinIO: провайдер определяется
только переменными окружения (S3_ENDPOINT_URL, ключи, бакет).
Никаких вызовов, специфичных для R2, здесь нет — переезд на любой
другой S3-совместимый сервис не требует правки кода.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import BinaryIO

from botocore.exceptions import ClientError

from app.core.config import settings
from app.infrastructure.storage.base import (
    ObjectStorage,
    ObjectTooLargeError,
    PresignedUpload,
    StoredObject,
)
from app.infrastructure.storage.client import s3_client

# S3 DeleteObjects принимает не больше 1000 ключей за вызов.
_DELETE_BATCH = 1000

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
# Кусок потокового скачивания: большие архивы импорта не читаются в память.
_DOWNLOAD_CHUNK = 1024 * 1024


class S3ObjectStorage:
    def __init__(self, bucket: str) -> None:
        self.bucket = bucket

    async def create_upload_url(
        self, key: str, *, content_type: str, expires_in: int
    ) -> PresignedUpload:
        # Подпись делается на публичный адрес хранилища: ссылкой
        # воспользуется браузер, которому внутренний адрес недоступен.
        async with s3_client(settings.S3_PUBLIC_ENDPOINT_URL) as client:
            url = await client.generate_presigned_url(
                "put_object",
                Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=expires_in,
                HttpMethod="PUT",
            )
        return PresignedUpload(
            url=str(url),
            method="PUT",
            expires_in=expires_in,
            headers={"Content-Type": content_type},
        )

    async def stat(self, key: str) -> StoredObject | None:
        async with s3_client() as client:
            try:
                response = await client.head_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                if str(exc.response.get("Error", {}).get("Code")) in _NOT_FOUND_CODES:
                    return None
                raise
        return StoredObject(
            size=int(response.get("ContentLength", 0)),
            content_type=response.get("ContentType"),
        )

    async def read(self, key: str, *, max_bytes: int | None = None) -> bytes:
        params: dict[str, str] = {"Bucket": self.bucket, "Key": key}
        if max_bytes is not None:
            params["Range"] = f"bytes=0-{max_bytes - 1}"
        async with s3_client() as client:
            response = await client.get_object(**params)
            async with response["Body"] as stream:
                data: bytes = await stream.read()
        return data

    async def download(self, key: str, target: BinaryIO, *, max_bytes: int) -> int:
        written = 0
        async with s3_client() as client:
            response = await client.get_object(Bucket=self.bucket, Key=key)
            async with response["Body"] as stream:
                while True:
                    chunk: bytes = await stream.read(_DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise ObjectTooLargeError(key)
                    target.write(chunk)
        return written

    async def write(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        cache_control: str | None = None,
        content_disposition: str | None = None,
    ) -> None:
        extra: dict[str, str] = {}
        if cache_control:
            extra["CacheControl"] = cache_control
        if content_disposition:
            # Хранится как метаданные объекта: CDN отдаёт его заголовком
            # ответа, и браузер знает, открыть файл или сохранить.
            extra["ContentDisposition"] = content_disposition
        async with s3_client() as client:
            await client.put_object(
                Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, **extra
            )

    async def delete(self, keys: Sequence[str]) -> None:
        unique_keys = list(dict.fromkeys(key for key in keys if key))
        if not unique_keys:
            return
        async with s3_client() as client:
            for start in range(0, len(unique_keys), _DELETE_BATCH):
                batch = unique_keys[start : start + _DELETE_BATCH]
                await client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
                )


@lru_cache
def get_object_storage() -> ObjectStorage:
    """FastAPI-зависимость и точка входа для воркера.

    Тесты подменяют её через `app.dependency_overrides`.
    """
    return S3ObjectStorage(settings.S3_BUCKET)
