"""Складская упаковка заявок (_docs/warehouse-design.md).

Пока здесь только номер складского документа. Модели, расчёт
доступного остатка и создание документов добавляются отдельными
задачами.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

# Год в номере — по времени склада, а не UTC: документ, созданный
# в Алматы в ночь на 1 января, относится уже к новому году.
NUMBER_TZ = ZoneInfo("Asia/Almaty")

DOCUMENT_NUMBER_PREFIX = "WH"


def build_document_number(value: int, moment: datetime) -> str:
    """Номер складского документа вида WH-2026-000123 (design §1.6).

    `value` — очередное значение последовательности
    warehouse_document_number_seq, она начинается с 1. Номер дополняется
    нулями до шести цифр и никогда не обрезается.

    `moment` передаёт вызывающий код: функция не читает часы и не
    обращается к БД. Время без часового пояса отвергается — во всём
    проекте метки времени хранятся с поясом.
    """
    if value < 1:
        raise ValueError(f"Номер документа должен быть не меньше 1, получено {value}")
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("Время для номера документа должно содержать часовой пояс")

    year = moment.astimezone(NUMBER_TZ).year
    return f"{DOCUMENT_NUMBER_PREFIX}-{year}-{value:06d}"
