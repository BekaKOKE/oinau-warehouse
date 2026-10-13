"""Безопасный простой текст для редактируемого контента.

Контент сайта (CMS, alt-тексты изображений) хранится как ПРОСТОЙ ТЕКСТ,
а не HTML. Абзацы — переводы строк, оформление — дело фронтенда.

Почему не «санитизированный HTML»: санитайзер — это вечная гонка
с обходами, а любой пропущенный атрибут превращается в хранимый XSS на
всех страницах сайта. Простой текст фронтенд выводит с экранированием,
и атаковать там нечего. Проверки здесь — второй рубеж: они не дают
сохранить разметку вообще, чтобы её не пришлось обезвреживать при выводе.

Отвергаются:
  * HTML/XML-теги и комментарии (`<b>`, `</p>`, `<!--`, `<?xml`);
  * управляющие символы, кроме перевода строки и табуляции;
  * символы управления направлением текста (bidi override): ими
    маскируют ссылки и подменяют видимый текст.
"""

from __future__ import annotations

import re
import unicodedata

# Начало тега по правилам HTML: «<» вплотную к латинской букве, «/», «!»
# или «?» (`<b>`, `</p>`, `<!--`, `<?xml`). Знак «меньше» с пробелом или
# перед цифрой («диаметр < 16 мм») браузер считает текстом — он допустим.
_TAG_PATTERN = re.compile(r"<[/!?A-Za-z]")
_ALLOWED_CONTROL = {"\n", "\t"}
_BIDI_CONTROLS = {chr(code) for code in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))}

LOCALE_PATTERN = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")


def clean_plain_text(value: str, *, max_length: int, multiline: bool) -> str:
    """Нормализует и проверяет строку. Бросает ValueError с понятным текстом."""
    text = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip()

    if not multiline and "\n" in text:
        raise ValueError("Перевод строки в этом поле недопустим")
    for char in text:
        if char in _BIDI_CONTROLS:
            raise ValueError("Недопустимый управляющий символ направления текста")
        if unicodedata.category(char) == "Cc" and char not in _ALLOWED_CONTROL:
            raise ValueError("Недопустимый управляющий символ")
    if _TAG_PATTERN.search(text):
        raise ValueError("HTML-разметка не допускается: поле хранит простой текст")
    if len(text) > max_length:
        raise ValueError(f"Текст длиннее {max_length} символов")
    return text


def clean_localized(
    value: dict[str, str], *, max_length: int, multiline: bool, default_locale: str
) -> dict[str, str]:
    """Локализованный текст вида {"ru": "...", "kk": "..."}.

    Пустые переводы отбрасываются. Текст на локали по умолчанию
    обязателен: иначе на витрине в основной версии сайта окажется пусто.
    Другие локали можно заполнять заранее, до включения языка на сайте.
    """
    result: dict[str, str] = {}
    for locale, raw in value.items():
        if not LOCALE_PATTERN.fullmatch(locale):
            raise ValueError(f"Некорректный код локали: {locale}")
        text = clean_plain_text(raw, max_length=max_length, multiline=multiline)
        if text:
            result[locale] = text
    if default_locale not in result:
        raise ValueError(f"Обязателен текст для локали {default_locale}")
    return result
