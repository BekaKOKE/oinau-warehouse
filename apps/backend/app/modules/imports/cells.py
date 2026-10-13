"""Разбор значений ячеек в типы домена.

Excel хранит числа как двоичные float. Decimal строится из кратчайшего
десятичного представления float (`repr`), а не из самого float:
Decimal(0.1) = 0.1000000000000000055…, а Decimal(repr(0.1)) = 0.1.
Для значений до 15 значащих цифр (NUMERIC(14, x) в базе) это
представление точно совпадает с тем, что пользователь видит в ячейке.

Лишние знаки после запятой отвергаются, а не округляются: молча
превратить цену 1200.555 в 1200.56 — значит изменить её за пользователя.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from app.core.text import clean_plain_text
from app.modules.imports.issues import IssueCode
from app.modules.imports.xlsx_format import LIST_SEPARATOR
from app.modules.imports.xlsx_reader import CellValue

INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1

_TRUE = {"true", "1", "yes", "y", "да", "д", "истина"}
_FALSE = {"false", "0", "no", "n", "нет", "н", "ложь"}
_SPACES = re.compile(r"[\s  ]")


class CellError(ValueError):
    def __init__(self, message: str, code: str = IssueCode.INVALID_VALUE) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _require(value: CellValue) -> CellValue:
    if value is None:
        raise CellError("Значение обязательно", IssueCode.REQUIRED)
    return value


def as_text(
    value: CellValue, *, max_length: int, multiline: bool = False, required: bool = False
) -> str | None:
    """Простой текст по общим правилам проекта (app/core/text.py).

    HTML-разметка, управляющие символы и символы смены направления
    текста отвергаются: из Excel в каталог попадает только текст.
    Число в текстовой ячейке допустимо (`5` -> "5").
    """
    if value is None:
        if required:
            raise CellError("Значение обязательно", IssueCode.REQUIRED)
        return None
    if isinstance(value, bool):
        raise CellError("Ожидается текст, а не логическое значение")
    if isinstance(value, float):
        raw = str(int(value)) if value.is_integer() else repr(value)
    else:
        raw = str(value)
    try:
        text = clean_plain_text(raw, max_length=max_length, multiline=multiline)
    except ValueError as exc:
        raise CellError(str(exc)) from exc
    if not text:
        if required:
            raise CellError("Значение обязательно", IssueCode.REQUIRED)
        return None
    return text


def as_identifier(value: CellValue, *, pattern: str, max_length: int, hint: str) -> str:
    """Артикул, slug, код: без пробелов по краям, строго по шаблону."""
    text = as_text(value, max_length=max_length, required=True)
    assert text is not None
    if not re.fullmatch(pattern, text):
        raise CellError(hint)
    return text


def as_bool(value: CellValue) -> bool:
    value = _require(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE:
            return True
        if normalized in _FALSE:
            return False
    raise CellError("Ожидается TRUE или FALSE (также 1/0, да/нет)")


def as_int(value: CellValue, *, minimum: int = INT32_MIN, maximum: int = INT32_MAX) -> int:
    value = _require(value)
    if isinstance(value, bool):
        raise CellError("Ожидается целое число")
    if isinstance(value, float):
        if not value.is_integer():
            raise CellError("Ожидается целое число")
        number = int(value)
    elif isinstance(value, int):
        number = value
    else:
        try:
            number = int(_SPACES.sub("", str(value)))
        except ValueError as exc:
            raise CellError("Ожидается целое число") from exc
    if not minimum <= number <= maximum:
        raise CellError(f"Число должно быть от {minimum} до {maximum}")
    return number


def as_decimal(
    value: CellValue,
    *,
    max_digits: int,
    decimal_places: int,
    greater_than: Decimal | None = None,
    at_least: Decimal | None = None,
) -> Decimal:
    value = _require(value)
    if isinstance(value, bool):
        raise CellError("Ожидается число")
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(repr(value))
    else:
        text = _SPACES.sub("", str(value))
        if "," in text and "." not in text:
            text = text.replace(",", ".")
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise CellError("Ожидается число") from exc

    if not number.is_finite():
        raise CellError("Ожидается число")

    exponent = number.as_tuple().exponent
    assert isinstance(exponent, int)
    places = max(-exponent, 0)
    if places > decimal_places:
        # Хвостовые нули (1.500) лишними знаками не считаются.
        normalized = number.normalize()
        normalized_exponent = normalized.as_tuple().exponent
        assert isinstance(normalized_exponent, int)
        if max(-normalized_exponent, 0) > decimal_places:
            raise CellError(f"Не больше {decimal_places} знаков после запятой")
        number = normalized
    integer_digits = max_digits - decimal_places
    if number != 0 and number.adjusted() + 1 > integer_digits:
        raise CellError(f"Слишком большое число: не больше {integer_digits} цифр до запятой")
    quantized = number.quantize(Decimal(1).scaleb(-decimal_places))

    if greater_than is not None and not quantized > greater_than:
        raise CellError(f"Число должно быть больше {greater_than}")
    if at_least is not None and quantized < at_least:
        raise CellError(f"Число должно быть не меньше {at_least}")
    return quantized


def as_enum[EnumT: StrEnum](value: CellValue, enum_cls: type[EnumT]) -> EnumT:
    value = _require(value)
    text = str(value).strip().upper()
    try:
        return enum_cls(text)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_cls)
        raise CellError(f"Допустимые значения: {allowed}") from exc


def as_list(value: CellValue) -> list[str]:
    """Список через «;». Пустые элементы (двойной разделитель) пропускаются."""
    if value is None:
        return []
    if isinstance(value, bool):
        raise CellError("Ожидается список через «;»")
    return [item.strip() for item in str(value).split(LIST_SEPARATOR) if item.strip()]


def format_values(values: Iterable[str]) -> str:
    return ", ".join(values)
