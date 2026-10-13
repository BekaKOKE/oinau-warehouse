"""Схемы Admin API заявок.

Публичные схемы не переиспользуются: админка видит контакты, историю
статусов и внутренние комментарии, которых у витрины нет и не будет.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.modules.pricing.enums import PricingType
from app.modules.requests.enums import RequestKind, RequestSource, RequestStatus

MAX_COMMENT_BODY = 5000
MAX_STATUS_COMMENT = 2000


class RegionRef(BaseModel):
    id: int
    code: str
    name: str


class UserRef(BaseModel):
    """Сотрудник — автор комментария или смены статуса.

    Идентификатор — uuid, как и во всём API пользователей."""

    uuid: uuid.UUID
    full_name: str


# ------------------------------------------------------------------ список


class RequestListItem(BaseModel):
    id: int
    number: str
    kind: RequestKind
    source: RequestSource
    status: RequestStatus
    customer_name: str
    phone: str
    email: str | None = None
    company: str | None = None
    region: RegionRef | None = None
    items_count: int
    total_estimate: Decimal | None = None
    currency: str
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------- карточка


class RequestItemRead(BaseModel):
    """Позиция заявки — снапшот, а не текущий товар.

    `product_id` — только ссылка: товар мог быть удалён или изменён,
    а позиция обязана показывать то, что видел клиент.
    """

    id: int
    product_id: int | None = None
    sku: str
    name: str
    unit: str
    pricing_type: PricingType
    quantity: Decimal
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    # Цвет позиции (снапшот); null — без цвета.
    color: str | None = None
    color_name: str | None = None


class RequestAttachmentRead(BaseModel):
    """Метаданные приложенного файла. Содержимое — отдельным запросом."""

    id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class RequestCommentRead(BaseModel):
    id: int
    body: str
    is_internal: bool
    author: UserRef | None = None
    created_at: datetime


class RequestStatusHistoryRead(BaseModel):
    id: int
    # null — запись о создании заявки
    from_status: RequestStatus | None = None
    to_status: RequestStatus
    comment: str | None = None
    # null — изменение сделано не сотрудником (создание с сайта)
    changed_by: UserRef | None = None
    created_at: datetime


class RequestDetail(BaseModel):
    id: int
    uuid: uuid.UUID
    number: str
    kind: RequestKind
    status: RequestStatus
    source: RequestSource

    customer_name: str
    phone: str
    email: str | None = None
    company: str | None = None
    bin: str | None = None
    region: RegionRef | None = None
    comment: str | None = None
    page_url: str | None = None

    currency: str
    total_estimate: Decimal | None = None
    items: list[RequestItemRead] = Field(default_factory=list)
    attachments: list[RequestAttachmentRead] = Field(default_factory=list)

    comments: list[RequestCommentRead] = Field(default_factory=list)
    status_history: list[RequestStatusHistoryRead] = Field(default_factory=list)

    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ запись


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


class RequestStatusUpdate(BaseModel):
    """Смена статуса. Переход в любой статус разрешён: движка
    workflow нет, воронку задаёт менеджер."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: RequestStatus
    comment: Annotated[str | None, BeforeValidator(_blank_to_none)] = Field(
        default=None, max_length=MAX_STATUS_COMMENT
    )


class RequestCommentCreate(BaseModel):
    """Комментарий по умолчанию внутренний.

    `visible_to_customer=true` — ответ клиенту: он виден в кабинете,
    если заявка отправлена из кабинета, и порождает уведомление. Флаг
    назван явно, а не `is_internal`, чтобы видимость нельзя было открыть
    случайно, забыв поле: отсутствие флага всегда означает «внутренний».
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    body: str = Field(min_length=1, max_length=MAX_COMMENT_BODY)
    visible_to_customer: bool = False
