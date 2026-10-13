"""Приём XLSX через multipart/form-data.

Тело запроса разбирается вручную, а не параметром `UploadFile`
эндпоинта. Причина — порядок: FastAPI читает тело ДО зависимостей, и
анонимный клиент успел бы прислать мегабайты, прежде чем получить 401.
Здесь сначала отрабатывают аутентификация и проверка прав, потом
читается тело — с жёстким лимитом по мере чтения, даже если клиент не
прислал Content-Length или соврал в нём.

Файл целиком держится в памяти (не больше UPLOAD_MAX_SIZE_MB). Временные
файлы, которые создаёт парсер multipart, закрываются (и удаляются) сразу
после чтения. Имя файла клиента используется только для показа в
истории импортов: в путь файловой системы оно не попадает.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass

from fastapi import Request
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.config import settings
from app.core.exceptions import AppError
from app.modules.imports.exceptions import (
    ImportFileEmptyError,
    ImportFileMissingError,
    ImportFileTooLargeError,
    ImportUnsupportedFileError,
    ImportUploadError,
)
from app.modules.imports.xlsx_format import XLSX_MIME

# Заявленный тип — лишь первое сито: браузеры и ОС нередко присылают
# octet-stream. Настоящая проверка — по содержимому (xlsx_reader).
ALLOWED_CONTENT_TYPES = frozenset({XLSX_MIME, "application/octet-stream"})
# Заголовки multipart и граница — сверх размера самого файла.
MULTIPART_OVERHEAD = 64 * 1024
MAX_FILENAME_LENGTH = 255


@dataclass(frozen=True)
class XlsxUpload:
    filename: str
    content_type: str
    data: bytes
    sha256: str

    @property
    def size(self) -> int:
        return len(self.data)


class _BodyTooLargeError(MultiPartException):
    """Наследник MultiPartException: парсер закроет временные файлы сам."""


def _too_large() -> ImportFileTooLargeError:
    return ImportFileTooLargeError(details={"max_size_mb": settings.UPLOAD_MAX_SIZE_MB})


async def _limited(stream: AsyncIterator[bytes], limit: int) -> AsyncGenerator[bytes, None]:
    received = 0
    async for chunk in stream:
        received += len(chunk)
        if received > limit:
            raise _BodyTooLargeError("request body too large")
        yield chunk


def sanitize_filename(raw: str) -> str:
    """Только последний компонент пути, без управляющих символов."""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(
        char
        for char in unicodedata.normalize("NFC", name)
        if not unicodedata.category(char).startswith("C")
    ).strip()
    if len(name) > MAX_FILENAME_LENGTH:
        stem, dot, extension = name.rpartition(".")
        if dot and len(extension) < 10:
            name = f"{stem[: MAX_FILENAME_LENGTH - len(extension) - 1]}.{extension}"
        else:
            name = name[:MAX_FILENAME_LENGTH]
    return name


async def read_xlsx_upload(request: Request) -> XlsxUpload:
    limit = settings.upload_max_size_bytes
    body_limit = limit + MULTIPART_OVERHEAD

    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > body_limit:
        raise _too_large()
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise ImportUploadError

    parser = MultiPartParser(
        request.headers, _limited(request.stream(), body_limit), max_files=1, max_fields=2
    )
    try:
        form = await parser.parse()
    except _BodyTooLargeError as exc:
        raise _too_large() from exc
    except MultiPartException as exc:
        raise ImportUploadError from exc
    except AppError:
        raise
    except Exception as exc:
        # Обрыв соединения или битое тело — ответ один и тот же.
        raise ImportUploadError from exc

    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise ImportFileMissingError
        data = await upload.read(limit + 1)
        filename = sanitize_filename(upload.filename or "")
        content_type = (upload.content_type or "").split(";")[0].strip().lower()
    finally:
        await form.close()

    if len(data) > limit:
        raise _too_large()
    if not filename.lower().endswith(".xlsx"):
        raise ImportUnsupportedFileError(details={"reason": "extension"})
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise ImportUnsupportedFileError(details={"reason": "content_type"})
    if not data:
        raise ImportFileEmptyError

    return XlsxUpload(
        filename=filename,
        content_type=content_type,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
    )
