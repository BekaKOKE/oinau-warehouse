"""Документы в медиатеке: схемы и чертежи (PDF, DWG, DXF).

Документ — такой же файл медиатеки, как изображение: оригинал лежит
в приватном префиксе, наружу через CDN отдаётся только вариант. Отличие
одно — вместо перекодирования в WebP воркер проверяет сигнатуру и кладёт
рядом копию `variants/file.<ext>`. Содержимое на сервере не
интерпретируется: PDF не рендерится, DWG/DXF не разбираются. Файл
только хранится и отдаётся на скачивание.

Сигнатуры — единственная проверка содержимого, поэтому правила строгие:
файл обязан начинаться с сигнатуры своего формата с первого байта.
"""

from __future__ import annotations

import re
from urllib.parse import quote

PDF_MIME = "application/pdf"
DWG_MIME = "image/vnd.dwg"
DXF_MIME = "image/vnd.dxf"

# MIME -> расширение ключа объекта. Как и у изображений, расширение
# берётся из проверенного типа, а не из имени файла клиента.
DOCUMENT_EXTENSIONS: dict[str, str] = {
    PDF_MIME: "pdf",
    DWG_MIME: "dwg",
    DXF_MIME: "dxf",
}
DOCUMENT_MIMES = frozenset(DOCUMENT_EXTENSIONS)

# Расширение имени файла -> тип, на который оно претендует. Нужен
# импорту: в ZIP нет заявленного Content-Type, есть только имя.
EXTENSION_DOCUMENT_MIME: dict[str, str] = {ext: mime for mime, ext in DOCUMENT_EXTENSIONS.items()}

# Вариант документа: одна копия оригинала, доступная через CDN.
DOCUMENT_VARIANT = "file"

# Сколько байт нужно для распознавания любого из форматов.
DOCUMENT_SNIFF_BYTES = 64

_DWG_SIGNATURE = re.compile(rb"^AC10\d\d")
# DXF в текстовом виде начинается с пары «код группы — значение»:
# `0 / SECTION` или комментария `999 / ...`. Пробелы перед кодом
# допустимы — AutoCAD выравнивает коды по правому краю.
_DXF_ASCII_SIGNATURE = re.compile(rb"^[ \t]*(0|999)[ \t]*\r?\n")
_DXF_BINARY_SIGNATURE = b"AutoCAD Binary DXF\r\n\x1a\x00"


def is_document(mime_type: str | None) -> bool:
    return mime_type in DOCUMENT_MIMES


def sniff_document_mime(head: bytes) -> str | None:
    """Тип документа по первым байтам. None — не поддерживаемый документ."""
    if head.startswith(b"%PDF-"):
        return PDF_MIME
    if _DWG_SIGNATURE.match(head):
        return DWG_MIME
    if head.startswith(_DXF_BINARY_SIGNATURE) or _DXF_ASCII_SIGNATURE.match(head):
        return DXF_MIME
    return None


def document_variant_key(storage_key: str, mime_type: str) -> str:
    """`products/{uuid}/variants/file.pdf` — рядом с приватным оригиналом."""
    base = storage_key.rsplit("/", 1)[0]
    return f"{base}/variants/{DOCUMENT_VARIANT}.{DOCUMENT_EXTENSIONS[mime_type]}"


def content_disposition(mime_type: str, filename: str | None) -> str:
    """Как браузер обращается с файлом по ссылке CDN.

    PDF открывается во встроенном просмотрщике (`inline`), DWG/DXF
    браузер показать не может — сразу скачивание (`attachment`). Имя
    для сохранения — в ASCII-форме и в RFC 5987 (`filename*`), чтобы
    кириллица не превращалась в кракозябры.
    """
    disposition = "inline" if mime_type == PDF_MIME else "attachment"
    extension = DOCUMENT_EXTENSIONS.get(mime_type, "bin")
    name = (filename or "").strip() or f"scheme.{extension}"
    ascii_name = "".join(
        char if char.isascii() and (char.isalnum() or char in "._-") else "_" for char in name
    )
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"
