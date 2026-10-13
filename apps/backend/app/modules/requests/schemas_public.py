"""Схемы публичного API заявок.

`extra="forbid"`: цена, снапшоты, статус и служебные поля от клиента
не принимаются вовсе. Молча игнорировать их хуже — фронтенд решил бы,
что переданная им цена куда-то записалась.

Товар указывается артикулом: публичный каталог отдаёт `sku` и `slug`,
а внутренний `id` наружу не выходит. Сервер сам находит товар и пишет
`product_id` в позицию.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.db.types import (
    LEN_CODE,
    LEN_EMAIL,
    LEN_PHONE,
    LEN_SHORT_NAME,
    LEN_SLUG,
    LEN_URL,
    QTY_PRECISION,
    QTY_SCALE,
)
from app.modules.pricing.enums import PricingType
from app.modules.requests.enums import QuickRequestMode
from app.modules.requests.sku_list import MAX_SKU_LIST_LENGTH

# Точность совпадает с колонкой NUMERIC(14,3): лишние знаки отвергаются
# явно, а не округляются базой молча. Канат заказывают метрами.
QuantityField = Annotated[Decimal, Field(gt=0, max_digits=QTY_PRECISION, decimal_places=QTY_SCALE)]

MAX_REQUEST_ITEMS = 100
MAX_COMMENT_LENGTH = 2000

# Цифры, пробелы, дефисы, скобки и ведущий «+». Хранится нормализованный
# вид: одинаковый номер, введённый по-разному, должен находиться поиском
# и сравниваться при разборе повторных обращений.
_PHONE_PATTERN = re.compile(r"^\+?[0-9\s\-()]+$")
_MIN_PHONE_DIGITS = 5  # совпадает с CHECK phone_min_length
_MAX_PHONE_DIGITS = 15  # E.164


def normalize_phone(value: str) -> str:
    raw = value.strip()
    if not _PHONE_PATTERN.fullmatch(raw):
        raise ValueError("Телефон может содержать только цифры, пробелы, «+», «-» и скобки")
    digits = re.sub(r"\D", "", raw)
    if not _MIN_PHONE_DIGITS <= len(digits) <= _MAX_PHONE_DIGITS:
        raise ValueError(
            f"В номере телефона должно быть от {_MIN_PHONE_DIGITS} до {_MAX_PHONE_DIGITS} цифр"
        )
    return f"+{digits}" if raw.startswith("+") else digits


# Код цвета из справочника (`colors.code`), как его отдаёт каталог.
ColorCodeField = Annotated[str, Field(min_length=1, max_length=LEN_SLUG)]


class PublicRequestItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sku: str = Field(min_length=1, max_length=LEN_CODE)
    quantity: QuantityField
    # Цвет товара, если товар продаётся в нескольких цветах.
    color: ColorCodeField | None = None


class PublicRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=LEN_SHORT_NAME)
    phone: str = Field(min_length=1, max_length=LEN_PHONE)
    email: EmailStr | None = None
    company: str | None = Field(default=None, max_length=LEN_SHORT_NAME)
    # Регион необязателен: на форме заявки его нет, менеджер уточняет
    # адрес доставки при подтверждении. Пришедшее значение (кабинет,
    # импорт, API) по-прежнему проверяется по справочнику.
    region_id: int | None = Field(default=None, ge=1)
    comment: str | None = Field(default=None, max_length=MAX_COMMENT_LENGTH)
    items: list[PublicRequestItemInput] = Field(min_length=1, max_length=MAX_REQUEST_ITEMS)

    @field_validator("email", "company", "comment", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        """Пустое необязательное поле формы — это отсутствие значения."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("email")
    @classmethod
    def _check_email_length(cls, value: str | None) -> str | None:
        if value is not None and len(value) > LEN_EMAIL:
            raise ValueError(f"Email длиннее {LEN_EMAIL} символов")
        return value

    @model_validator(mode="after")
    def _check_duplicates(self) -> PublicRequestCreate:
        """Один товар в одном цвете — одна позиция. Иначе непонятно,
        какое из количеств определяет ступень цены. Разные цвета одного
        товара — разные позиции."""
        keys = [(item.sku, item.color) for item in self.items]
        duplicates = sorted({sku for sku, color in keys if keys.count((sku, color)) > 1})
        if duplicates:
            raise ValueError(f"Товар указан в заявке несколько раз: {', '.join(duplicates)}")
        return self


class PublicRequestItemRead(BaseModel):
    """Позиция в подтверждении — ровно то, что зафиксировано снапшотом."""

    sku: str
    name: str
    unit: str
    quantity: Decimal
    pricing_type: PricingType
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    color: str | None = None
    color_name: str | None = None


class PublicRequestCreated(BaseModel):
    """Подтверждение приёма заявки.

    Только номер для связи с менеджером и рассчитанный состав. Статус,
    комментарии менеджеров и прочие внутренние данные наружу не выходят,
    публичного чтения заявки нет.
    """

    number: str
    created_at: datetime
    currency: str
    # null, если хотя бы одна позиция «по запросу»: неполная сумма
    # выглядела бы окончательной.
    total_estimate: Decimal | None = None
    items: list[PublicRequestItemRead]


# ----------------------------------------------------------- быстрый заказ

_BIN_PATTERN = re.compile(r"^[0-9]{12}$")


class PublicQuickRequestCreate(BaseModel):
    """Окно «Быстрый заказ» — поля формы multipart.

    Контакты те же, что у обычной заявки, но регион не спрашивается:
    каждое лишнее поле в быстрой форме снижает её смысл. Регион, если
    он важен, уточнит менеджер.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: QuickRequestMode
    name: str = Field(min_length=1, max_length=LEN_SHORT_NAME)
    phone: str = Field(min_length=1, max_length=LEN_PHONE)
    email: EmailStr | None = None
    company: str | None = Field(default=None, max_length=LEN_SHORT_NAME)
    bin: str | None = None
    comment: str | None = Field(default=None, max_length=MAX_COMMENT_LENGTH)
    # SKU_LIST: текст как его вставил клиент; разбирает сервер.
    sku_list: str | None = Field(default=None, max_length=MAX_SKU_LIST_LENGTH)
    # CALLBACK с карточки товара — «заказ в 1 клик».
    product_sku: str | None = Field(default=None, max_length=LEN_CODE)
    # Цвет товара в заказе в 1 клик.
    product_color: str | None = Field(default=None, max_length=LEN_SLUG)
    quantity: QuantityField | None = None
    page_url: str | None = Field(default=None, max_length=LEN_URL)

    @field_validator(
        "email",
        "company",
        "bin",
        "comment",
        "sku_list",
        "product_sku",
        "product_color",
        "quantity",
        "page_url",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        """Пустое поле формы — это отсутствие значения."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("email")
    @classmethod
    def _check_email_length(cls, value: str | None) -> str | None:
        if value is not None and len(value) > LEN_EMAIL:
            raise ValueError(f"Email длиннее {LEN_EMAIL} символов")
        return value

    @field_validator("bin")
    @classmethod
    def _check_bin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        digits = re.sub(r"\s", "", value)
        if not _BIN_PATTERN.fullmatch(digits):
            raise ValueError("БИН — 12 цифр")
        return digits

    @model_validator(mode="after")
    def _check_mode(self) -> PublicQuickRequestCreate:
        if self.mode is QuickRequestMode.SKU_LIST and not self.sku_list:
            raise ValueError("Вставьте список артикулов")
        if self.mode is QuickRequestMode.QUOTE and not self.email:
            # Коммерческое предложение — документ, его отправляют письмом.
            raise ValueError("Укажите email: на него придёт коммерческое предложение")
        if self.product_sku and self.mode is not QuickRequestMode.CALLBACK:
            raise ValueError("Товар передаётся только в заказе в 1 клик")
        if self.quantity is not None and not self.product_sku:
            raise ValueError("Количество задаётся только вместе с товаром")
        if self.product_color is not None and not self.product_sku:
            raise ValueError("Цвет задаётся только вместе с товаром")
        return self


class QuickRequestBelowMinimum(BaseModel):
    """Позиция списка артикулов меньше минимальной партии.

    Заявку это не отклоняет — список вставляли руками, и менеджер
    согласует количество сам. Клиенту показывается предупреждение.
    """

    sku: str
    quantity: Decimal
    min_order_qty: Decimal


class PublicAttachmentRead(BaseModel):
    filename: str
    size_bytes: int


class PublicQuickRequestCreated(PublicRequestCreated):
    """Подтверждение быстрого заказа.

    `unrecognized` и `below_minimum` — чтобы клиент сразу увидел, что
    из списка не нашлось. Повтор по Idempotency-Key возвращает их
    пустыми: разбор не хранится отдельно, менеджер видит его в
    комментарии заявки.
    """

    mode: QuickRequestMode
    unrecognized: list[str] = Field(default_factory=list)
    below_minimum: list[QuickRequestBelowMinimum] = Field(default_factory=list)
    attachment: PublicAttachmentRead | None = None
