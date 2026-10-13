"""Безопасное чтение ZIP-пакета импорта.

Архив пришёл от пользователя, поэтому до чтения любого файла проверяется
весь каталог архива:

* пути: абсолютные, с буквой диска, с `..`, пустыми сегментами и
  управляющими символами отвергаются целиком — архив «с сюрпризом» не
  обрабатывается частично. На диск по именам из архива ничего не
  распаковывается: файлы читаются из ZIP в память по одному, поэтому
  обход пути невозможен в принципе, а проверка — второй рубеж;
* символические ссылки и зашифрованные файлы — отказ;
* ZIP-бомба: число файлов, суммарный распакованный размер и степень
  сжатия каждого файла ограничены до чтения содержимого. zipfile не
  отдаёт больше заявленного размера файла и сверяет CRC, так что
  заявленные размеры честные;
* размер каждого файла — по его роли: книга, фотография, схема;
* ничего не исполняется: книга читается тем же безопасным разбором,
  что и обычный XLSX, остальные файлы — только байты для хранилища.

Модуль синхронный и не трогает базу: чтение идёт в пуле потоков.
"""

from __future__ import annotations

import stat
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import BinaryIO

from app.modules.imports.bundle_format import (
    BUNDLE_XLSX_NAME,
    IGNORED_NAMES,
    IGNORED_PREFIXES,
    PHOTOS_DIR,
    SCHEMES_DIR,
)

ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06")
# Файлы меньше этого не проверяются на степень сжатия: текстовый DXF
# или пустая книга законно сжимаются в десятки раз.
RATIO_CHECK_MIN_BYTES = 1024 * 1024
MAX_PATH_LENGTH = 512

# Папки пакета и их синонимы (без учёта регистра).
FOLDER_ALIASES: dict[str, str] = {
    PHOTOS_DIR: PHOTOS_DIR,
    "фото": PHOTOS_DIR,
    "images": PHOTOS_DIR,
    "изображения": PHOTOS_DIR,
    SCHEMES_DIR: SCHEMES_DIR,
    "схемы": SCHEMES_DIR,
    "чертежи": SCHEMES_DIR,
    "drawings": SCHEMES_DIR,
}


class BundleRejectedError(Exception):
    """Архив не принят целиком. Сообщение — для администратора, по-русски."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BundleLimits:
    max_files: int
    max_uncompressed: int
    max_ratio: int
    max_workbook: int
    max_photo: int
    max_scheme: int


@dataclass(frozen=True)
class BundleFile:
    """Файл пакета. `path` — путь внутри пакета («photos/504-176.jpg»)."""

    path: str
    folder: str
    relative: str
    size: int
    info: zipfile.ZipInfo

    @property
    def name(self) -> str:
        return PurePosixPath(self.relative).name

    @property
    def extension(self) -> str:
        suffix = PurePosixPath(self.relative).suffix
        return suffix[1:].lower() if suffix else ""


@dataclass
class BundleArchive:
    """Разобранный каталог архива. Содержимое читается по требованию."""

    archive: zipfile.ZipFile
    limits: BundleLimits
    workbook: BundleFile
    files: dict[str, dict[str, list[BundleFile]]] = field(default_factory=dict)
    # Файлы вне photos/ и schemes/ — пропускаются с предупреждением.
    ignored: list[str] = field(default_factory=list)

    def all_files(self, folder: str) -> list[BundleFile]:
        return [item for items in self.files.get(folder, {}).values() for item in items]

    def lookup(self, folder: str, reference: str) -> list[BundleFile]:
        """Файлы папки по ссылке из книги.

        Ссылка — имя файла («504-176.jpg»), путь внутри папки
        («2024/504-176.jpg») или путь с папкой («photos/504-176.jpg»).
        Сначала точное совпадение, затем без учёта регистра — Excel
        и Windows регистр имён не различают. Несколько совпадений без
        учёта регистра — неоднозначность, решает вызывающий код.
        """
        normalized = _clean_reference(reference)
        if normalized is None:
            return []
        parts = normalized.split("/")
        if len(parts) > 1 and FOLDER_ALIASES.get(parts[0].casefold()) == folder:
            normalized = "/".join(parts[1:])
        candidates = self.files.get(folder, {}).get(normalized.casefold(), [])
        exact = [item for item in candidates if item.relative == normalized]
        if exact:
            return exact
        if candidates:
            return candidates
        if "/" not in normalized:
            # Только имя без подпапки — ищем по имени во всей папке.
            key = normalized.casefold()
            return [item for item in self.all_files(folder) if item.name.casefold() == key]
        return []

    def read(self, item: BundleFile, *, limit: int) -> bytes:
        if item.size > limit:
            raise BundleRejectedError(
                "file_too_large", f"Файл {item.path} больше {limit // (1024 * 1024)} МБ"
            )
        try:
            with self.archive.open(item.info) as stream:
                data = stream.read(limit + 1)
        except (zipfile.BadZipFile, OSError, ValueError, RuntimeError) as exc:
            raise BundleRejectedError("bundle_corrupted", f"Файл {item.path} повреждён") from exc
        if len(data) > limit:
            raise BundleRejectedError(
                "file_too_large", f"Файл {item.path} больше {limit // (1024 * 1024)} МБ"
            )
        return data

    def read_workbook(self) -> bytes:
        return self.read(self.workbook, limit=self.limits.max_workbook)

    def close(self) -> None:
        self.archive.close()


def _decode_name(info: zipfile.ZipInfo) -> str:
    """Имя файла в архиве с учётом кодировки.

    Флаг UTF-8 (бит 11) ставят не все архиваторы: «Сжатая папка»
    Windows пишет имена в кодировке OEM (для русской Windows — cp866),
    а zipfile тогда декодирует их как cp437. Возвращаем исходные байты
    и пробуем UTF-8, затем cp866.
    """
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for encoding in ("utf-8", "cp866"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return name


def _safe_path(name: str) -> str:
    """Нормализованный относительный путь или отказ всему архиву."""
    normalized = unicodedata.normalize("NFC", name).replace("\\", "/")
    if (
        not normalized
        or len(normalized) > MAX_PATH_LENGTH
        or normalized.startswith("/")
        or (len(normalized) > 1 and normalized[1] == ":")
        or any(unicodedata.category(char).startswith("C") for char in normalized)
    ):
        raise BundleRejectedError("unsafe_path", f"Недопустимый путь в архиве: {name!r}")
    parts = normalized.rstrip("/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise BundleRejectedError("unsafe_path", f"Недопустимый путь в архиве: {name!r}")
    return "/".join(parts)


def _clean_reference(reference: str) -> str | None:
    text = unicodedata.normalize("NFC", reference).strip().replace("\\", "/").strip("/")
    if not text:
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def open_bundle(source: BinaryIO, limits: BundleLimits) -> BundleArchive:
    """Проверяет каталог архива и находит книгу, фото и схемы."""
    head = source.read(4)
    source.seek(0)
    if not head.startswith(ZIP_SIGNATURES):
        raise BundleRejectedError("not_zip", "Файл не является ZIP-архивом")
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, OSError) as exc:
        raise BundleRejectedError("bundle_corrupted", "ZIP-архив повреждён") from exc

    try:
        return _inspect(archive, limits)
    except BaseException:
        archive.close()
        raise


def _inspect(archive: zipfile.ZipFile, limits: BundleLimits) -> BundleArchive:
    entries = archive.infolist()
    if len(entries) > limits.max_files:
        raise BundleRejectedError(
            "too_many_files", f"В архиве больше {limits.max_files} файлов — разбейте его на части"
        )

    total = 0
    files: list[tuple[str, zipfile.ZipInfo]] = []
    seen: set[str] = set()
    for info in entries:
        path = _safe_path(_decode_name(info))
        if info.flag_bits & 0x1:
            raise BundleRejectedError("encrypted", "Архивы с паролем не принимаются")
        if _is_symlink(info):
            raise BundleRejectedError("symlink", f"Символические ссылки не принимаются: {path}")
        if info.is_dir():
            continue
        total += info.file_size
        if total > limits.max_uncompressed:
            raise BundleRejectedError(
                "uncompressed_too_large",
                "Распакованное содержимое архива больше "
                f"{limits.max_uncompressed // (1024 * 1024)} МБ",
            )
        if (
            info.file_size >= RATIO_CHECK_MIN_BYTES
            and info.file_size > info.compress_size * limits.max_ratio
        ):
            raise BundleRejectedError(
                "compression_ratio", f"Подозрительно сильно сжатый файл: {path}"
            )
        folded = path.casefold()
        if folded in seen:
            raise BundleRejectedError("duplicate_path", f"Файл указан в архиве дважды: {path}")
        seen.add(folded)
        files.append((path, info))

    visible = [
        (path, info)
        for path, info in files
        if PurePosixPath(path).name.casefold() not in IGNORED_NAMES
        and not path.casefold().startswith(IGNORED_PREFIXES)
    ]
    workbooks = [
        (path, info)
        for path, info in visible
        if PurePosixPath(path).name.casefold() == BUNDLE_XLSX_NAME
        and len(PurePosixPath(path).parts) <= 2
    ]
    if not workbooks:
        raise BundleRejectedError(
            "workbook_missing",
            f"В архиве нет {BUNDLE_XLSX_NAME}: положите книгу в корень архива "
            "рядом с папками photos и schemes",
        )
    if len(workbooks) > 1:
        raise BundleRejectedError(
            "workbook_ambiguous",
            f"В архиве несколько {BUNDLE_XLSX_NAME}: " + ", ".join(path for path, _ in workbooks),
        )
    workbook_path, workbook_info = workbooks[0]
    # Корень пакета — папка книги: архив «папки целиком» содержит
    # общий верхний каталог, и это нормально.
    root_parts = PurePosixPath(workbook_path).parts[:-1]

    bundle = BundleArchive(
        archive=archive,
        limits=limits,
        workbook=BundleFile(
            path=BUNDLE_XLSX_NAME,
            folder="",
            relative=BUNDLE_XLSX_NAME,
            size=workbook_info.file_size,
            info=workbook_info,
        ),
    )
    for path, info in visible:
        if path == workbook_path:
            continue
        parts = PurePosixPath(path).parts
        if parts[: len(root_parts)] != root_parts:
            bundle.ignored.append(path)
            continue
        inner = parts[len(root_parts) :]
        folder = FOLDER_ALIASES.get(inner[0].casefold()) if len(inner) > 1 else None
        if folder is None:
            bundle.ignored.append("/".join(inner))
            continue
        relative = "/".join(inner[1:])
        item = BundleFile(
            path=f"{folder}/{relative}",
            folder=folder,
            relative=relative,
            size=info.file_size,
            info=info,
        )
        bundle.files.setdefault(folder, {}).setdefault(relative.casefold(), []).append(item)
    return bundle


__all__ = [
    "BundleArchive",
    "BundleFile",
    "BundleLimits",
    "BundleRejectedError",
    "open_bundle",
]
