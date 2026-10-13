"""Контракт объектного хранилища.

Прикладной код (медиатека, воркер обработки) зависит от этого протокола,
а не от aiobotocore или конкретного провайдера. Реализация для S3 API
(R2 в проде, MinIO локально) — в s3.py; тесты подставляют хранилище
в памяти через dependency override.

Набор операций минимален — ровно то, что нужно потоку загрузки:
выдать ссылку на загрузку, проверить объект, прочитать, записать
варианты и удалить.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import BinaryIO, Protocol


@dataclass(frozen=True)
class PresignedUpload:
    """Одноразовая ссылка для загрузки файла напрямую в хранилище.

    `headers` — заголовки, которые клиент обязан передать в PUT
    буквально: Content-Type входит в подпись, и загрузка с другим
    типом будет отвергнута самим хранилищем.
    """

    url: str
    method: str
    expires_in: int
    headers: dict[str, str] = field(default_factory=dict)


class ObjectTooLargeError(Exception):
    """Объект больше разрешённого — скачивание прервано."""


@dataclass(frozen=True)
class StoredObject:
    size: int
    content_type: str | None = None


class ObjectStorage(Protocol):
    async def create_upload_url(
        self, key: str, *, content_type: str, expires_in: int
    ) -> PresignedUpload: ...

    async def stat(self, key: str) -> StoredObject | None:
        """Метаданные объекта или None, если объекта нет."""
        ...

    async def read(self, key: str, *, max_bytes: int | None = None) -> bytes:
        """Содержимое объекта; `max_bytes` — только первые N байт (Range)."""
        ...

    async def download(self, key: str, target: BinaryIO, *, max_bytes: int) -> int:
        """Пишет объект в открытый файл по частям, не держа его в памяти.

        Возвращает число записанных байт. Больше `max_bytes` не читается:
        объект крупнее — ошибка `ObjectTooLargeError`, файл не дочитывается.
        """
        ...

    async def write(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        cache_control: str | None = None,
        content_disposition: str | None = None,
    ) -> None: ...

    async def delete(self, keys: Sequence[str]) -> None:
        """Удаляет объекты. Отсутствующий ключ ошибкой не считается."""
        ...
