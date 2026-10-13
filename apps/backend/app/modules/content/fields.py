"""Типы полей контента с проверками.

Текст — только простой (app/core/text.py): без HTML, управляющих
символов и bidi-override. Ссылки — только http(s) или путь на своём
сайте: `javascript:`, `data:` и протокол-относительные `//host`
отвергаются. Реквизиты проверяются по формату РК.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field

from app.core.config import settings
from app.core.text import clean_localized, clean_plain_text
from app.db.types import LEN_PHONE, LEN_URL
from app.modules.requests.schemas_public import normalize_phone

# Больше языков сайт не поддержит никогда; предел отсекает мусорные ключи.
MAX_LOCALES = 5


def _localized(max_length: int, *, multiline: bool) -> Callable[[dict[str, str]], dict[str, str]]:
    def validate(value: dict[str, str]) -> dict[str, str]:
        return clean_localized(
            value,
            max_length=max_length,
            multiline=multiline,
            default_locale=settings.DEFAULT_LOCALE,
        )

    return validate


_LocaleMap = Annotated[dict[str, str], Field(max_length=MAX_LOCALES)]

# Заголовки, подписи, названия — одна строка.
LocalizedLine = Annotated[_LocaleMap, AfterValidator(_localized(255, multiline=False))]
# Вопрос FAQ — одна строка, но длиннее заголовка.
LocalizedQuestion = Annotated[_LocaleMap, AfterValidator(_localized(500, multiline=False))]
# SEO-описание: поисковики всё равно показывают ~160 символов.
LocalizedSeoText = Annotated[_LocaleMap, AfterValidator(_localized(500, multiline=False))]
# Короткий текст с переводами строк: подзаголовок, адрес, часы работы.
LocalizedShortText = Annotated[_LocaleMap, AfterValidator(_localized(1000, multiline=True))]
# Длинный текст: абзацы разделяются переводом строки.
LocalizedText = Annotated[_LocaleMap, AfterValidator(_localized(5000, multiline=True))]


def _validate_link(value: str) -> str:
    """Абсолютная http(s)-ссылка или путь на своём сайте (`/catalog`)."""
    link = clean_plain_text(value, max_length=LEN_URL, multiline=False)
    if not link:
        raise ValueError("Пустая ссылка")
    if any(char.isspace() for char in link):
        raise ValueError("Ссылка не может содержать пробелы")
    if link.startswith("/"):
        if link.startswith("//"):
            raise ValueError("Протокол-относительные ссылки (//host) не допускаются")
        return link
    return _validate_absolute(link, allow_http=True)


def _validate_https(value: str) -> str:
    link = clean_plain_text(value, max_length=LEN_URL, multiline=False)
    if any(char.isspace() for char in link):
        raise ValueError("Ссылка не может содержать пробелы")
    return _validate_absolute(link, allow_http=False)


def _validate_absolute(link: str, *, allow_http: bool) -> str:
    parts = urlsplit(link)
    schemes = {"https", "http"} if allow_http else {"https"}
    if parts.scheme.lower() not in schemes:
        raise ValueError(
            "Допустимы только ссылки https://" + (", http:// или путь /..." if allow_http else "")
        )
    if not parts.netloc or parts.username or parts.password:
        raise ValueError("Некорректный адрес ссылки")
    return link


Link = Annotated[str, AfterValidator(_validate_link)]
HttpsUrl = Annotated[str, AfterValidator(_validate_https)]


def _validate_phone(value: str) -> str:
    """Номер хранится так, как его ввели (для показа), но проверяется
    тем же правилом, что телефон в заявках."""
    display = re.sub(r"\s+", " ", value.strip())
    if len(display) > LEN_PHONE:
        raise ValueError(f"Номер длиннее {LEN_PHONE} символов")
    normalize_phone(display)
    return display


PhoneNumber = Annotated[str, AfterValidator(_validate_phone)]


def _compact_upper(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _validate_bin(value: str) -> str:
    compact = _compact_upper(value)
    if not re.fullmatch(r"\d{12}", compact):
        raise ValueError("БИН/ИИН — 12 цифр")
    return compact


def _validate_iban(value: str) -> str:
    """IBAN Казахстана: KZ + 2 контрольные цифры + 16 знаков.

    Контрольная сумма (ISO 13616, mod 97) проверяется: опечатка в счёте
    на странице реквизитов — это деньги клиента, ушедшие не туда.
    """
    compact = _compact_upper(value)
    if not re.fullmatch(r"KZ\d{2}[A-Z0-9]{16}", compact):
        raise ValueError("IBAN должен иметь вид KZ + 18 знаков")
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(char, 36)) for char in rearranged)
    if int(numeric) % 97 != 1:
        raise ValueError("Неверная контрольная сумма IBAN")
    return compact


def _validate_bik(value: str) -> str:
    compact = _compact_upper(value)
    if not re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?", compact):
        raise ValueError("БИК (SWIFT) — 8 или 11 знаков")
    return compact


def _validate_kbe(value: str) -> str:
    compact = _compact_upper(value)
    if not re.fullmatch(r"\d{2}", compact):
        raise ValueError("КБе — 2 цифры")
    return compact


Bin = Annotated[str, AfterValidator(_validate_bin)]
Iban = Annotated[str, AfterValidator(_validate_iban)]
Bik = Annotated[str, AfterValidator(_validate_bik)]
Kbe = Annotated[str, AfterValidator(_validate_kbe)]
