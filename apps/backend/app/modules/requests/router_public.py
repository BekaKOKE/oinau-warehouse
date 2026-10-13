"""Приём заявок с сайта — /api/v1/public/requests и /quick-requests.

Без авторизации, с ограничением частоты по IP. Только создание:
публичного чтения заявки нет — клиенту достаточно номера для связи
с менеджером, а статус и комментарии — внутренние данные.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status

from app.api.deps import ContextDep, SessionDep, rate_limit
from app.modules.notifications.queue import NotificationQueue, get_notification_queue
from app.modules.requests.schemas_public import (
    PublicQuickRequestCreated,
    PublicRequestCreate,
    PublicRequestCreated,
)
from app.modules.requests.service import RequestSubmissionService
from app.modules.requests.service_quick import QuickRequestService
from app.modules.requests.upload import (
    QUICK_REQUEST_BODY,
    read_quick_request_form,
    validate_quick_fields,
)

router = APIRouter(tags=["requests"])

NotificationQueueDep = Annotated[NotificationQueue, Depends(get_notification_queue)]

# Ключ генерирует фронтенд при открытии формы (обычно UUID).
IdempotencyKeyHeader = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.:-]+$",
        description="Повтор с тем же ключом вернёт уже созданную заявку",
    ),
]

# Корзина и быстрый заказ делят одну норму: это одна и та же форма
# обращения, и спамер не должен получать двойной лимит.
_public_form_limit = Depends(rate_limit("public_request", "RATE_LIMIT_PUBLIC_FORM"))


@router.post(
    "/requests",
    response_model=PublicRequestCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Отправить заявку",
    dependencies=[_public_form_limit],
)
async def create_request(
    payload: PublicRequestCreate,
    session: SessionDep,
    context: ContextDep,
    notifications: NotificationQueueDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PublicRequestCreated:
    """Цены, названия и артикулы позиций сервер берёт из каталога сам.

    Клиент передаёт только контакты, регион и пары «артикул —
    количество». Любое лишнее поле (цена, статус и т. п.) — 422.
    """
    return await RequestSubmissionService(session, notifications).submit(
        payload, context, idempotency_key
    )


@router.post(
    "/quick-requests",
    response_model=PublicQuickRequestCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Быстрый заказ",
    dependencies=[_public_form_limit],
    openapi_extra=QUICK_REQUEST_BODY,
)
async def create_quick_request(
    request: Request,
    session: SessionDep,
    context: ContextDep,
    notifications: NotificationQueueDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PublicQuickRequestCreated:
    """Окно «Быстрый заказ»: звонок, список артикулов или запрос КП.

    multipart/form-data: поля схемы `PublicQuickRequestCreate` и
    необязательный файл `file` (только к запросу КП). Тело читается
    после проверки частоты, с лимитом REQUEST_ATTACHMENT_MAX_SIZE_MB.
    """
    form = await read_quick_request_form(request)
    payload = validate_quick_fields(form.fields)
    return await QuickRequestService(session, notifications).submit_quick(
        payload, form.attachment, context, idempotency_key
    )
