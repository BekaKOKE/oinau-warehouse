"""Проверка и обработка изображений.

Чистые функции без обращения к БД и хранилищу: их вызывает сервис
обработки в воркере, и их же удобно проверять тестами напрямую.

Что гарантируется для файла, дошедшего до READY:
  * сигнатура (magic bytes) совпадает с заявленным типом — скрипт,
    переименованный в .png, отсекается ещё до воркера;
  * Pillow действительно декодирует файл заявленного формата;
  * число пикселей ограничено (защита от «декомпрессионной бомбы»);
  * публичные варианты перекодированы в WebP — EXIF с геометками
    и данными камеры в них не попадает, ориентация применена.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.modules.media.enums import MediaFailureReason

# Сколько байт читать из начала объекта для проверки сигнатуры.
SNIFF_BYTES = 32

# Расширение ключа берётся из проверенного MIME, а не из имени файла
# клиента: имя пользователя в ключ не попадает никогда.
MIME_EXTENSIONS: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

_PIL_FORMATS: dict[str, str] = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}

# Публичные варианты: имя -> длинная сторона в пикселях. Меньшее
# изображение не растягивается — вариант просто равен оригиналу по размеру.
VARIANTS: tuple[tuple[str, int], ...] = (
    ("large", 1600),
    ("medium", 800),
    ("small", 400),
    ("thumb", 200),
)
VARIANT_MIME = "image/webp"
VARIANT_EXTENSION = "webp"
_VARIANT_QUALITY = 82


class ImageRejectedError(Exception):
    def __init__(self, reason: MediaFailureReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class RenderedVariant:
    name: str
    data: bytes
    width: int
    height: int


@dataclass(frozen=True)
class ProcessedImage:
    width: int
    height: int
    variants: list[RenderedVariant]


def sniff_mime(head: bytes) -> str | None:
    """Тип по сигнатуре первых байт. None — не поддерживаемое изображение."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def process_image(data: bytes, *, mime_type: str, max_pixels: int) -> ProcessedImage:
    """Проверяет файл и строит публичные варианты.

    CPU-bound: вызывается из воркера через `asyncio.to_thread`.
    """
    pil_format = _PIL_FORMATS.get(mime_type)
    if pil_format is None:
        raise ImageRejectedError(MediaFailureReason.TYPE_MISMATCH)

    try:
        # formats=[...]: Pillow не будет угадывать формат по содержимому,
        # файл обязан быть именно тем, чем назван.
        with Image.open(BytesIO(data), formats=[pil_format]) as probe:
            width, height = probe.size
            if width * height > max_pixels:
                raise ImageRejectedError(MediaFailureReason.TOO_MANY_PIXELS)
            probe.verify()

        # verify() оставляет объект непригодным для работы — открываем заново.
        with Image.open(BytesIO(data), formats=[pil_format]) as source:
            source.load()
            image = ImageOps.exif_transpose(source) or source
            image = _normalize_mode(image)
            width, height = image.size
            variants = [_render(image, name, max_side) for name, max_side in VARIANTS]
    except ImageRejectedError:
        raise
    except Image.DecompressionBombError as exc:
        raise ImageRejectedError(MediaFailureReason.TOO_MANY_PIXELS) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageRejectedError(MediaFailureReason.DECODE_FAILED) from exc

    return ProcessedImage(width=width, height=height, variants=variants)


def _normalize_mode(image: Image.Image) -> Image.Image:
    """WebP понимает только RGB/RGBA; палитра и CMYK приводятся явно."""
    if image.mode in ("RGB", "RGBA"):
        return image
    has_alpha = "A" in image.getbands() or "transparency" in image.info
    return image.convert("RGBA" if has_alpha else "RGB")


def _render(image: Image.Image, name: str, max_side: int) -> RenderedVariant:
    variant = image.copy()
    variant.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    # exif не передаётся — метаданные камеры в публичный файл не попадают.
    variant.save(buffer, format="WEBP", quality=_VARIANT_QUALITY, method=4)
    return RenderedVariant(
        name=name, data=buffer.getvalue(), width=variant.width, height=variant.height
    )
