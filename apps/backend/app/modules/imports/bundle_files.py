"""Проверка файлов пакета, на которые ссылается книга.

Каждый упомянутый файл читается один раз: проверяется расширение
(белый список по роли — фото или схема), размер, сигнатура содержимого
(тип определяется по байтам, а не по имени), у изображений — что Pillow
действительно открывает файл и число пикселей в пределах. Итог —
MIME по содержимому и SHA-256: по нему повторная загрузка того же файла
не создаёт дубликат в медиатеке.

Модуль синхронный, без базы: выполняется в пуле потоков.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from app.modules.imports.bundle_archive import BundleArchive, BundleFile, BundleRejectedError
from app.modules.imports.bundle_format import PHOTO_EXTENSIONS, SCHEME_EXTENSIONS, SCHEMES_DIR
from app.modules.imports.issues import IssueCode
from app.modules.media.documents import is_document, sniff_document_mime
from app.modules.media.images import sniff_mime

_PIL_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


@dataclass(frozen=True)
class FileCheck:
    """Итог проверки файла пакета. Ошибка — `code`/`message`, иначе тип и хеш."""

    file: BundleFile
    mime: str | None = None
    sha256: str | None = None
    code: str | None = None
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.code is None


def allowed_extensions(folder: str) -> dict[str, str]:
    return SCHEME_EXTENSIONS if folder == SCHEMES_DIR else PHOTO_EXTENSIONS


def check_file(
    archive: BundleArchive, item: BundleFile, *, max_photo: int, max_scheme: int, max_pixels: int
) -> FileCheck:
    extensions = allowed_extensions(item.folder)
    declared = extensions.get(item.extension)
    if declared is None:
        return FileCheck(
            file=item,
            code=IssueCode.FILE_UNSUPPORTED,
            message=(
                f"Недопустимый формат файла {item.path}. Разрешены: "
                + ", ".join(sorted(extensions))
            ),
        )
    # Предел — по папке: схема (в том числе в JPG) законно тяжелее фото.
    limit = max_scheme if item.folder == SCHEMES_DIR else max_photo
    if item.size > limit:
        return FileCheck(
            file=item,
            code=IssueCode.FILE_TOO_LARGE,
            message=f"Файл {item.path} больше {limit // (1024 * 1024)} МБ",
        )
    if item.size == 0:
        return FileCheck(
            file=item, code=IssueCode.FILE_CONTENT_MISMATCH, message=f"Файл {item.path} пуст"
        )
    try:
        data = archive.read(item, limit=limit)
    except BundleRejectedError as exc:
        return FileCheck(file=item, code=IssueCode.FILE_TOO_LARGE, message=exc.message)

    actual = sniff_document_mime(data[:64]) if is_document(declared) else sniff_mime(data[:32])
    if actual != declared:
        return FileCheck(
            file=item,
            code=IssueCode.FILE_CONTENT_MISMATCH,
            message=f"Содержимое файла {item.path} не соответствует расширению .{item.extension}",
        )
    if not is_document(declared):
        problem = _verify_image(data, declared, max_pixels)
        if problem is not None:
            return FileCheck(
                file=item,
                code=IssueCode.FILE_CONTENT_MISMATCH,
                message=f"Изображение {item.path}: {problem}",
            )
    return FileCheck(file=item, mime=declared, sha256=hashlib.sha256(data).hexdigest())


def _verify_image(data: bytes, mime: str, max_pixels: int) -> str | None:
    """Pillow открывает файл заявленного формата, пикселей не слишком много.

    Полное декодирование и варианты строит воркер медиатеки — здесь
    только быстрая проверка заголовка и структуры, чтобы битый файл был
    виден в предпросмотре, а не после импорта.
    """
    try:
        with Image.open(BytesIO(data), formats=[_PIL_FORMATS[mime]]) as probe:
            width, height = probe.size
            if width * height > max_pixels:
                return "слишком большое разрешение"
            probe.verify()
    except Image.DecompressionBombError:
        return "слишком большое разрешение"
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        return "файл повреждён или не открывается"
    return None


def read_checked(archive: BundleArchive, check: FileCheck, *, limit: int) -> bytes:
    """Содержимое проверенного файла для загрузки в хранилище.

    Хеш сверяется повторно: архив не должен измениться между проверкой
    и загрузкой, но дешёвая сверка защищает от сюрприза.
    """
    data = archive.read(check.file, limit=limit)
    if hashlib.sha256(data).hexdigest() != check.sha256:
        raise BundleRejectedError("bundle_changed", f"Файл {check.file.path} изменился")
    return data


__all__ = ["FileCheck", "allowed_extensions", "check_file", "read_checked"]
