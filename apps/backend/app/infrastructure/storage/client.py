"""Клиент объектного хранилища (Cloudflare R2 в проде, MinIO локально).

Оба говорят на S3 API — код один, различается только S3_ENDPOINT_URL.
Прикладной код работает не с этим клиентом, а с протоколом
`ObjectStorage` (base.py); здесь — только транспорт.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from aiobotocore.config import AioConfig
from aiobotocore.session import get_session as get_aws_session

from app.core.config import settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# AioConfig, а не botocore.config.Config: aiobotocore 3.x принимает
# только собственный класс (он же наследник botocore Config в 2.x).
_CONFIG = AioConfig(
    signature_version="s3v4",
    retries={"max_attempts": 3, "mode": "standard"},
    connect_timeout=3,
    read_timeout=10,
    # R2 и MinIO одинаково понимают path-style адресацию; virtual-host
    # потребовал бы DNS-записи на каждый бакет в локальном окружении.
    s3={"addressing_style": "path"},
)


@asynccontextmanager
async def s3_client(endpoint_url: str | None = None) -> AsyncIterator[Any]:
    """S3-клиент.

    `endpoint_url` переопределяется только для подписи presigned URL:
    внутри Docker backend ходит в `http://minio:9000`, а браузер этот
    адрес не видит — ему нужна ссылка на `S3_PUBLIC_ENDPOINT_URL`.
    """
    session = get_aws_session()
    async with session.create_client(
        "s3",
        endpoint_url=endpoint_url or settings.S3_ENDPOINT_URL,
        region_name=settings.S3_REGION,
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        config=_CONFIG,
    ) as client:
        yield client


async def ping_storage() -> None:
    """Проверяет, что бакет существует и доступен."""
    async with s3_client() as client:
        await client.head_bucket(Bucket=settings.S3_BUCKET)


def build_public_url(storage_key: str) -> str:
    """Публичный URL файла.

    В БД хранится только storage_key. URL собирается здесь, поэтому смена
    CDN-домена — это правка переменной окружения, а не UPDATE по таблице.
    """
    return f"{settings.CDN_BASE_URL.rstrip('/')}/{storage_key.lstrip('/')}"
