"""Разбор списка «артикул × количество», вставленного клиентом.

Клиент копирует список откуда угодно: из письма, из спецификации, из
Excel. Поэтому формат нестрогий, а разбор — терпимый:

    OIN-1042 × 20          OIN-1042 x 20         OIN-1042 - 20 шт
    OIN-1042: 20           OIN-1042;20           OIN-1042×20
    OIN-1042<TAB>Подвес<TAB>20   (строка из Excel: количество — последняя ячейка)
    OIN-1042 × 20, OIN-2210 × 4   (несколько позиций в одной строке)
    OIN-1042               (без количества — минимальная партия товара)

Артикул — первое слово записи. Разбор не решает, существует ли
артикул: это делает сервис по каталогу. Поэтому для слова без пробелов
(«BOX-2x4») возвращаются варианты по порядку предпочтения — сначала
слово целиком, затем разрезанное по «x»; сервис берёт первый найденный.

Нераспознанное не теряется: исходный текст каждой записи сохраняется,
и то, чего нет в каталоге, менеджер видит в заявке как есть.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

MAX_SKU_LIST_LENGTH = 5000

_LINE_SPLIT = re.compile(r"[\r\n]+")
# Запятая или точка с запятой перед буквой — граница позиций в одной
# строке. Перед цифрой это десятичная запятая («12,5 м») или разделитель
# «артикул;количество», их резать нельзя. Строку из Excel (с табуляцией)
# не режем вовсе: запятая там — часть названия в соседней ячейке.
_INLINE_SPLIT = re.compile(r"[,;](?=\s*[^\W\d_])")

_NUMBER = r"\d{1,9}(?:[.,]\d{1,3})?"
# После артикула: необязательный разделитель, число, необязательный хвост
# (единица, «шт.», пояснение). Хвост не начинается с цифры — иначе
# «20 30» читалось бы как 20.
_TAIL = re.compile(rf"^\s*(?:[×*xхX:;=]|[-—–])?\s*(?P<qty>{_NUMBER})(?:\s*[^\d\s.,].*)?$")
# Слово без пробелов с количеством внутри: «OIN-1042×20», «KRP-M10x5».
_GLUED = re.compile(rf"^(?P<sku>.+?)(?:[×*:;=]|[xхX])(?P<qty>{_NUMBER})$")
_FULL_NUMBER = re.compile(rf"^\s*(?P<qty>{_NUMBER})\s*$")
_FIRST_WORD = re.compile(r"(\S+)(\s.*)?$", flags=re.DOTALL)
# Знаки, которые клиент ставит сразу после артикула: «OIN-1042:».
_SKU_TRAILING = ":;=,."


@dataclass(frozen=True)
class SkuListEntry:
    """Одна позиция списка.

    `candidates` — пары (артикул, количество) по порядку предпочтения.
    Количество None — не указано: сервис подставит минимальную партию.
    """

    raw: str
    candidates: tuple[tuple[str, Decimal | None], ...]


def _quantity(value: str) -> Decimal | None:
    try:
        quantity = Decimal(value.replace(",", "."))
    except InvalidOperation:
        return None
    return quantity if quantity > 0 else None


def _tail_quantity(rest: str) -> Decimal | None:
    """Количество из текста после артикула."""
    if "\t" in rest:
        # Строка из Excel: количество — последняя числовая ячейка.
        for cell in reversed(rest.split("\t")):
            match = _FULL_NUMBER.match(cell)
            if match:
                return _quantity(match.group("qty"))
        return None
    match = _TAIL.match(rest)
    return _quantity(match.group("qty")) if match else None


def _parse_entry(raw: str) -> SkuListEntry | None:
    text = raw.strip()
    match = _FIRST_WORD.match(text)
    if match is None:
        return None
    # Остаток — с ведущим пробельным символом: по табуляции
    # `_tail_quantity` узнаёт строку из Excel.
    head, rest = match.group(1), match.group(2) or ""
    sku = head.rstrip(_SKU_TRAILING)
    if not sku:
        return None

    candidates: list[tuple[str, Decimal | None]] = [(sku, _tail_quantity(rest))]
    if not rest.strip():
        glued = _GLUED.match(sku)
        if glued:
            quantity = _quantity(glued.group("qty"))
            glued_sku = glued.group("sku").rstrip(_SKU_TRAILING)
            if quantity is not None and glued_sku:
                candidates.append((glued_sku, quantity))
    return SkuListEntry(raw=text, candidates=tuple(candidates))


def parse_sku_list(text: str) -> list[SkuListEntry]:
    """Текст → позиции в порядке появления. Пустые записи пропускаются."""
    parts: list[str] = []
    for line in _LINE_SPLIT.split(text[:MAX_SKU_LIST_LENGTH]):
        parts.extend([line] if "\t" in line else _INLINE_SPLIT.split(line))
    entries = (_parse_entry(part) for part in parts)
    return [entry for entry in entries if entry is not None]
