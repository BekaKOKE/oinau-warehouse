"""Схемы кабинета клиента: профиль, избранное, заявки, проекты, уведомления.

Наружу выходят только публичные идентификаторы: `uuid` проекта и
уведомления, номер заявки, артикул товара. Внутренние `id` не отдаются.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.types import LEN_CODE, LEN_SHORT_NAME
from app.modules.customers.enums import CustomerRequestStatus, NotificationType, ProjectStatus
from app.modules.pricing.enums import PricingType
from app.modules.requests.enums import RequestSource
from app.modules.requests.schemas_public import (
    PublicRequestCreate,
    QuantityField,
    normalize_phone,
)

MAX_PROJECT_DESCRIPTION = 5000
MAX_NOTE_LENGTH = 1000


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


class RegionRef(BaseModel):
    id: int
    code: str
    name: str


# ------------------------------------------------------------------ профиль
class CustomerProfileRead(BaseModel):
    uuid: uuid.UUID
    email: str
    contact_name: str
    company_name: str | None
    phone: str
    region: RegionRef | None
    email_verified_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime


class CustomerProfileUpdate(BaseModel):
    """Частичное обновление профиля.

    Email здесь не принимается (`extra="forbid"` → 422): смена адреса,
    на который приходят ссылки восстановления доступа, требует отдельного
    сценария с подтверждением нового адреса.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contact_name: str | None = Field(default=None, min_length=1, max_length=LEN_SHORT_NAME)
    company_name: str | None = Field(default=None, max_length=LEN_SHORT_NAME)
    phone: str | None = Field(default=None, min_length=1, max_length=64)
    region_id: int | None = Field(default=None, ge=1)

    @field_validator("company_name", mode="before")
    @classmethod
    def _blank_company(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return normalize_phone(value) if value is not None else None


# ---------------------------------------------------------------- избранное
class FavoriteAdd(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sku: str = Field(min_length=1, max_length=LEN_CODE)


class FavoriteRead(BaseModel):
    sku: str
    slug: str
    name: str
    unit: str
    added_at: datetime


# ------------------------------------------------------------------- заявки
class ProjectRef(BaseModel):
    uuid: uuid.UUID
    name: str


class CustomerRequestCreate(PublicRequestCreate):
    """Та же форма, что у публичной заявки, плюс необязательный проект."""

    project_uuid: uuid.UUID | None = None


class CustomerRequestListItem(BaseModel):
    number: str
    status: CustomerRequestStatus
    # Корзина, быстрый заказ, запрос КП — кабинет подписывает заявку,
    # в которой нет позиций, чтобы она не выглядела пустой.
    source: RequestSource
    currency: str
    total_estimate: Decimal | None
    items_count: int
    project: ProjectRef | None
    created_at: datetime
    updated_at: datetime


class CustomerRequestItemRead(BaseModel):
    """Позиция — строго из снапшота request_items."""

    sku: str
    name: str
    unit: str
    quantity: Decimal
    pricing_type: PricingType
    unit_price: Decimal | None
    line_total: Decimal | None
    color: str | None = None
    color_name: str | None = None


class CustomerRequestCommentRead(BaseModel):
    """Комментарий менеджера, предназначенный клиенту.

    Автор не раскрывается: клиенту достаточно, что это ответ компании,
    а внутренняя структура отдела продаж — служебные данные.
    """

    body: str
    created_at: datetime


class CustomerRequestStatusRead(BaseModel):
    """Шаг истории статусов без комментария менеджера и без автора:
    комментарий к смене статуса пишется для коллег."""

    status: CustomerRequestStatus
    created_at: datetime


class CustomerRequestDetail(CustomerRequestListItem):
    customer_name: str
    phone: str
    email: str | None
    company: str | None
    region: RegionRef | None
    comment: str | None
    items: list[CustomerRequestItemRead]
    comments: list[CustomerRequestCommentRead]
    status_history: list[CustomerRequestStatusRead]


# ------------------------------------------------------------------ проекты
class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=LEN_SHORT_NAME)
    description: str | None = Field(default=None, max_length=MAX_PROJECT_DESCRIPTION)
    region_id: int | None = Field(default=None, ge=1)
    status: ProjectStatus = ProjectStatus.PLANNING

    @field_validator("description", mode="before")
    @classmethod
    def _blank_description(cls, value: Any) -> Any:
        return _blank_to_none(value)


class ProjectUpdate(BaseModel):
    """Частичное обновление: переданный `null` очищает описание и регион."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=LEN_SHORT_NAME)
    description: str | None = Field(default=None, max_length=MAX_PROJECT_DESCRIPTION)
    region_id: int | None = Field(default=None, ge=1)
    status: ProjectStatus | None = None

    @field_validator("description", mode="before")
    @classmethod
    def _blank_description(cls, value: Any) -> Any:
        return _blank_to_none(value)


class ProjectItemAdd(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sku: str = Field(min_length=1, max_length=LEN_CODE)
    quantity: QuantityField | None = None
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)


class ProjectItemRead(BaseModel):
    sku: str
    name: str
    # null — товар снят с публикации или удалён: позиция остаётся
    # в проекте по снапшоту, но перейти в карточку нельзя.
    slug: str | None
    is_available: bool
    quantity: Decimal | None
    note: str | None
    added_at: datetime


class ProjectRequestRef(BaseModel):
    number: str
    status: CustomerRequestStatus
    currency: str
    total_estimate: Decimal | None
    created_at: datetime


class ProjectListItem(BaseModel):
    uuid: uuid.UUID
    name: str
    status: ProjectStatus
    region: RegionRef | None
    items_count: int
    requests_count: int
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectListItem):
    description: str | None
    items: list[ProjectItemRead]
    requests: list[ProjectRequestRef]


# -------------------------------------------------------------- уведомления
class NotificationRead(BaseModel):
    uuid: uuid.UUID
    type: NotificationType
    title: str
    message: str
    payload: dict[str, Any]
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int
