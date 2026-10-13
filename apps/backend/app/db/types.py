"""Общие типы колонок и хелперы ограничений.

Единое место, где зафиксированы точность денег и количеств. Если эти
значения разъедутся по моделям, рассинхронизация обнаружится только на
проде при округлении суммы заявки.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, Numeric

# Деньги: NUMERIC, никогда не float. 14 знаков хватает на 999 млрд тенге.
MONEY_PRECISION = 14
MONEY_SCALE = 2

# Количество: тоже NUMERIC. Канат продаётся метрами, крепёж — килограммами,
# и 1С регулярно отдаёт дробные количества.
QTY_PRECISION = 14
QTY_SCALE = 3


def money_type() -> Numeric[Decimal]:
    return Numeric(MONEY_PRECISION, MONEY_SCALE, asdecimal=True)


def qty_type() -> Numeric[Decimal]:
    return Numeric(QTY_PRECISION, QTY_SCALE, asdecimal=True)


def enum_check(column: str, enum_cls: type[StrEnum], name: str) -> CheckConstraint:
    """CHECK-ограничение по значениям Python-перечисления.

    Используем VARCHAR + CHECK, а не PostgreSQL ENUM: расширение нативного
    ENUM — отдельная миграция с блокировкой типа, а CHECK переписывается
    обычным ALTER без блокировки таблицы на чтение.
    """
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=name)


# Длины строковых колонок — тоже в одном месте.
LEN_CODE = 64
LEN_SLUG = 200
LEN_NAME = 500
LEN_SHORT_NAME = 255
LEN_LOCALE = 8
LEN_EXTERNAL_ID = 64
LEN_STATUS = 32
LEN_UNIT = 16
LEN_PHONE = 32
LEN_EMAIL = 255
LEN_HASH = 128
LEN_URL = 1000
