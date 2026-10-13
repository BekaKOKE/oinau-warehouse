"""Приём формы «Быстрый заказ» (multipart/form-data с необязательным файлом).

Тело разбирается вручную, как и в импорте каталога (imports/upload.py):
FastAPI с параметром `UploadFile` прочитал бы тело ДО зависимостей, и
ограничение частоты сработало бы уже после того, как анонимный клиент
прислал двадцать мегабайт. Здесь сначала отрабатывает rate limit, потом
читается тело — с жёстким лимитом по мере чтения.

Файл проверяется по расширению И по сигнатуре содержимого. Заявленный
браузером тип не используется: сохраняется тип, выведенный из
расширения, а скачивание в админке всегда идёт как вложение.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.config import settings
from app.core.exceptions import AppError
from app.modules.imports.upload import sanitize_filename
from app.modules.requests.exceptions import (
    QuickRequestFormError,
    RequestAttachmentEmptyError,
    RequestAttachmentTooLargeError,
    RequestAttachmentUnsupportedError,
)
from app.modules.requests.schemas_public import PublicQuickRequestCreate

# Заголовки частей, граница и текстовые поля формы — сверх размера файла.
MULTIPART_OVERHEAD = 64 * 1024
MAX_FORM_FIELDS = 20
FILE_FIELD = "file"

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # старые .xls и .doc
_ZIP = b"PK\x03\x04"  # .xlsx и .docx

# Расширение → (тип для хранения, допустимые сигнатуры). Пустой кортеж
# сигнатур — текстовый формат: проверяется отсутствием нулевых байтов.
_FORMATS: dict[str, tuple[str, tuple[bytes, ...]]] = {
    "pdf": ("application/pdf", (b"%PDF-",)),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", (_ZIP,)),
    "xls": ("application/vnd.ms-excel", (_OLE,)),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", (_ZIP,)),
    "doc": ("application/msword", (_OLE,)),
    # Версия DWG в первых байтах: AC1015, AC1018, AC1024, AC1032…
    "dwg": ("image/vnd.dwg", (b"AC1",)),
    "dxf": ("image/vnd.dxf", ()),
    "csv": ("text/csv", ()),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
}
ALLOWED_EXTENSIONS = tuple(sorted(_FORMATS))

# Сколько байт текстового файла смотреть на нулевые символы.
_TEXT_PROBE = 8192


@dataclass(frozen=True)
class AttachmentUpload:
    filename: str
    content_type: str
    data: bytes
    sha256: str

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class QuickRequestForm:
    fields: dict[str, str]
    attachment: AttachmentUpload | None


class _BodyTooLargeError(MultiPartException):
    """Наследник MultiPartException: парсер закроет временные файлы сам."""


def _too_large() -> RequestAttachmentTooLargeError:
    return RequestAttachmentTooLargeError(
        details={"max_size_mb": settings.REQUEST_ATTACHMENT_MAX_SIZE_MB}
    )


async def _limited(stream: AsyncIterator[bytes], limit: int) -> AsyncGenerator[bytes, None]:
    received = 0
    async for chunk in stream:
        received += len(chunk)
        if received > limit:
            raise _BodyTooLargeError("request body too large")
        yield chunk


def _signature_matches(data: bytes, signatures: tuple[bytes, ...]) -> bool:
    if not signatures:
        return b"\x00" not in data[:_TEXT_PROBE]
    return any(data.startswith(signature) for signature in signatures)


def validate_attachment(filename: str, data: bytes) -> AttachmentUpload:
    """Имя и содержимое файла → проверенное вложение."""
    if not data:
        raise RequestAttachmentEmptyError
    if len(data) > settings.request_attachment_max_size_bytes:
        raise _too_large()

    name = sanitize_filename(filename) or "file"
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    fmt = _FORMATS.get(extension)
    if fmt is None:
        raise RequestAttachmentUnsupportedError(
            details={"reason": "extension", "allowed": list(ALLOWED_EXTENSIONS)}
        )
    content_type, signatures = fmt
    if not _signature_matches(data, signatures):
        raise RequestAttachmentUnsupportedError(details={"reason": "content"})

    return AttachmentUpload(
        filename=name,
        content_type=content_type,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
    )


async def read_quick_request_form(request: Request) -> QuickRequestForm:
    limit = settings.request_attachment_max_size_bytes
    body_limit = limit + MULTIPART_OVERHEAD

    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > body_limit:
        raise _too_large()
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise QuickRequestFormError

    parser = MultiPartParser(
        request.headers,
        _limited(request.stream(), body_limit),
        max_files=1,
        max_fields=MAX_FORM_FIELDS,
    )
    try:
        form = await parser.parse()
    except _BodyTooLargeError as exc:
        raise _too_large() from exc
    except MultiPartException as exc:
        raise QuickRequestFormError from exc
    except AppError:
        raise
    except Exception as exc:
        # Обрыв соединения или битое тело — ответ один и тот же.
        raise QuickRequestFormError from exc

    try:
        fields = {key: value for key, value in form.multi_items() if isinstance(value, str)}
        upload = form.get(FILE_FIELD)
        attachment: AttachmentUpload | None = None
        if isinstance(upload, UploadFile):
            data = await upload.read(limit + 1)
            # Пустое поле файла браузер присылает, когда файл не выбран.
            if data or upload.filename:
                attachment = validate_attachment(upload.filename or "", data)
    finally:
        await form.close()

    return QuickRequestForm(fields=fields, attachment=attachment)


def validate_quick_fields(fields: dict[str, str]) -> PublicQuickRequestCreate:
    """Поля формы → схема. Ошибка — обычный 422 validation_error.

    Схема проверяется вручную (тело разобрано вне FastAPI), поэтому
    ошибку Pydantic нужно превратить в RequestValidationError: иначе
    общий обработчик принял бы её за сбой и ответил 500.
    """
    try:
        return PublicQuickRequestCreate.model_validate(fields)
    except ValidationError as exc:
        raise RequestValidationError(
            [{**error, "loc": ("body", *error["loc"])} for error in exc.errors()]
        ) from exc


# Описание тела для OpenAPI: сам эндпоинт тело не объявляет (см. выше).
QUICK_REQUEST_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["mode", "name", "phone"],
                    "properties": {
                        **{
                            name: {"type": "string"}
                            for name in PublicQuickRequestCreate.model_fields
                        },
                        FILE_FIELD: {"type": "string", "format": "binary"},
                    },
                }
            }
        },
    }
}
