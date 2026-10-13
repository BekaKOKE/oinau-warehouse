"""Модульные тесты: безопасный текст и проверка изображений (без БД)."""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from app.core.text import clean_localized, clean_plain_text
from app.modules.media.enums import MediaFailureReason
from app.modules.media.images import ImageRejectedError, process_image, sniff_mime
from tests.media_helpers import image_bytes, jpeg_bytes, png_bytes


# ------------------------------------------------------------------ текст
@pytest.mark.parametrize(
    "value",
    [
        "Канат 16 мм",
        "Диаметр < 16 мм и > 10 мм",
        "x < y",
        "Цена: 3 500 ₸ — «оптом»",
        "Строка\n\nАбзац",
        "Табуляция\tвнутри",
    ],
)
def test_plain_text_is_accepted(value: str) -> None:
    assert clean_plain_text(value, max_length=100, multiline=True) == value


@pytest.mark.parametrize(
    "value",
    [
        "<b>жирный</b>",
        "</p>",
        # «<» вплотную к букве браузер читает как начало тега — это
        # разметка, даже если автор имел в виду сравнение.
        "a<b",
        "</ p>",
        "<!DOCTYPE html>",
        "<![CDATA[x]]>",
        "<?xml version='1.0'?>",
        "нулевой\x00байт",
        "звонок\x07",
        "подмена‮текста",
        "изоляция⁦текста",
    ],
)
def test_markup_and_control_characters_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        clean_plain_text(value, max_length=100, multiline=True)


def test_text_is_nfc_normalized() -> None:
    decomposed = "й"  # «и» + комбинируемая краткая
    assert clean_plain_text(decomposed, max_length=10, multiline=False) == "й"


def test_localized_requires_default_locale() -> None:
    assert clean_localized(
        {"ru": " Да ", "kk": ""}, max_length=10, multiline=False, default_locale="ru"
    ) == {"ru": "Да"}
    with pytest.raises(ValueError):
        clean_localized({"kk": "Иә"}, max_length=10, multiline=False, default_locale="ru")


# ------------------------------------------------------------ изображения
@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (png_bytes(), "image/png"),
        (jpeg_bytes(), "image/jpeg"),
        (image_bytes("WEBP"), "image/webp"),
        (b"GIF89a....", None),
        (b"%PDF-1.7", None),
        (b"", None),
    ],
)
def test_sniff_mime(data: bytes, expected: str | None) -> None:
    assert sniff_mime(data[:32]) == expected


def test_palette_and_cmyk_images_are_converted() -> None:
    palette = BytesIO()
    Image.new("P", (30, 20)).save(palette, format="PNG")
    assert process_image(palette.getvalue(), mime_type="image/png", max_pixels=10_000).width == 30

    cmyk = BytesIO()
    Image.new("CMYK", (30, 20)).save(cmyk, format="JPEG")
    result = process_image(cmyk.getvalue(), mime_type="image/jpeg", max_pixels=10_000)
    assert [variant.name for variant in result.variants] == ["large", "medium", "small", "thumb"]


def test_declared_type_must_match_decoder() -> None:
    """Pillow не угадывает формат: JPEG, названный PNG, не декодируется."""
    with pytest.raises(ImageRejectedError) as error:
        process_image(jpeg_bytes(), mime_type="image/png", max_pixels=10_000)
    assert error.value.reason is MediaFailureReason.DECODE_FAILED


def test_unsupported_type_is_rejected() -> None:
    with pytest.raises(ImageRejectedError) as error:
        process_image(png_bytes(), mime_type="image/gif", max_pixels=10_000)
    assert error.value.reason is MediaFailureReason.TYPE_MISMATCH
