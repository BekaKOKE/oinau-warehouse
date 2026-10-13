"""Кабинет клиента — /api/v1/customer.

Все эндпоинты требуют access-токен клиента (аудитория кабинета).
Сотрудник с токеном админки сюда не попадёт, клиент — в админку.
Идентификатор клиента берётся только из токена, никогда из запроса.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status

from app.api.deps import (
    ContextDep,
    CurrentCustomerDep,
    SessionDep,
    get_current_customer,
    rate_limit,
)
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams
from app.db.types import LEN_CODE
from app.modules.customers.schemas_account import (
    CustomerProfileRead,
    CustomerProfileUpdate,
    CustomerRequestCreate,
    CustomerRequestDetail,
    CustomerRequestListItem,
    FavoriteAdd,
    FavoriteRead,
    NotificationRead,
    ProjectCreate,
    ProjectDetail,
    ProjectItemAdd,
    ProjectListItem,
    ProjectUpdate,
    UnreadCount,
)
from app.modules.customers.service_account import CustomerAccountService
from app.modules.customers.service_requests import CustomerRequestService
from app.modules.notifications.queue import NotificationQueue, get_notification_queue
from app.modules.requests.schemas_public import PublicQuickRequestCreated, PublicRequestCreated
from app.modules.requests.service_quick import QuickRequestService
from app.modules.requests.upload import (
    QUICK_REQUEST_BODY,
    read_quick_request_form,
    validate_quick_fields,
)

# Зависимость на уровне роутера: ни один эндпоинт кабинета не может
# случайно остаться без проверки токена.
router = APIRouter(
    prefix="/customer",
    tags=["customer"],
    dependencies=[Depends(get_current_customer)],
)

PageQuery = Annotated[int, Query(ge=1, le=10_000)]
PageSizeQuery = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
SkuPath = Annotated[str, Path(min_length=1, max_length=LEN_CODE)]
RequestNumberPath = Annotated[str, Path(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9-]+$")]

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


def _page(page: int, page_size: int) -> PageParams:
    return PageParams(page=page, page_size=page_size)


# ------------------------------------------------------------------ профиль
@router.get("/profile", response_model=CustomerProfileRead, summary="Профиль клиента")
async def get_profile(customer: CurrentCustomerDep, session: SessionDep) -> CustomerProfileRead:
    return await CustomerAccountService(session).get_profile(customer)


@router.patch("/profile", response_model=CustomerProfileRead, summary="Изменение профиля")
async def update_profile(
    payload: CustomerProfileUpdate,
    customer: CurrentCustomerDep,
    session: SessionDep,
    context: ContextDep,
) -> CustomerProfileRead:
    return await CustomerAccountService(session).update_profile(customer, payload, context)


# ---------------------------------------------------------------- избранное
@router.get("/favorites", response_model=Page[FavoriteRead], summary="Избранное")
async def list_favorites(
    customer: CurrentCustomerDep,
    session: SessionDep,
    page: PageQuery = 1,
    page_size: PageSizeQuery = DEFAULT_PAGE_SIZE,
) -> Page[FavoriteRead]:
    return await CustomerAccountService(session).list_favorites(customer, _page(page, page_size))


@router.post(
    "/favorites",
    response_model=FavoriteRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить товар в избранное",
)
async def add_favorite(
    payload: FavoriteAdd,
    response: Response,
    customer: CurrentCustomerDep,
    session: SessionDep,
) -> FavoriteRead:
    """Повторное добавление — 200 с той же позицией, а не ошибка."""
    favorite, created = await CustomerAccountService(session).add_favorite(customer, payload.sku)
    if not created:
        response.status_code = status.HTTP_200_OK
    return favorite


@router.delete(
    "/favorites/{sku}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Убрать товар из избранного",
)
async def remove_favorite(sku: SkuPath, customer: CurrentCustomerDep, session: SessionDep) -> None:
    await CustomerAccountService(session).remove_favorite(customer, sku)


# ------------------------------------------------------------------- заявки
@router.get("/requests", response_model=Page[CustomerRequestListItem], summary="Мои заявки")
async def list_requests(
    customer: CurrentCustomerDep,
    session: SessionDep,
    page: PageQuery = 1,
    page_size: PageSizeQuery = DEFAULT_PAGE_SIZE,
) -> Page[CustomerRequestListItem]:
    return await CustomerRequestService(session).list_requests(customer, _page(page, page_size))


@router.post(
    "/requests",
    response_model=PublicRequestCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Отправить заявку из кабинета",
    dependencies=[Depends(rate_limit("customer_request", "RATE_LIMIT_PUBLIC_FORM"))],
)
async def create_request(
    payload: CustomerRequestCreate,
    customer: CurrentCustomerDep,
    session: SessionDep,
    context: ContextDep,
    notifications: Annotated[NotificationQueue, Depends(get_notification_queue)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> PublicRequestCreated:
    return await CustomerRequestService(session, notifications).submit(
        customer, payload, context, idempotency_key
    )


@router.post(
    "/quick-requests",
    response_model=PublicQuickRequestCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Быстрый заказ из кабинета",
    dependencies=[Depends(rate_limit("customer_request", "RATE_LIMIT_PUBLIC_FORM"))],
    openapi_extra=QUICK_REQUEST_BODY,
)
async def create_quick_request(
    request: Request,
    customer: CurrentCustomerDep,
    session: SessionDep,
    context: ContextDep,
    notifications: Annotated[NotificationQueue, Depends(get_notification_queue)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> PublicQuickRequestCreated:
    """Тот же быстрый заказ, что на сайте, но с привязкой к клиенту:
    заявка появляется в истории кабинета."""
    form = await read_quick_request_form(request)
    payload = validate_quick_fields(form.fields)
    return await QuickRequestService(session, notifications).submit_quick(
        payload, form.attachment, context, idempotency_key, customer_id=customer.id
    )


@router.get("/requests/{number}", response_model=CustomerRequestDetail, summary="Заявка клиента")
async def get_request(
    number: RequestNumberPath, customer: CurrentCustomerDep, session: SessionDep
) -> CustomerRequestDetail:
    return await CustomerRequestService(session).get_request(customer, number)


# ------------------------------------------------------------------ проекты
@router.get("/projects", response_model=Page[ProjectListItem], summary="Мои проекты")
async def list_projects(
    customer: CurrentCustomerDep,
    session: SessionDep,
    page: PageQuery = 1,
    page_size: PageSizeQuery = DEFAULT_PAGE_SIZE,
) -> Page[ProjectListItem]:
    return await CustomerAccountService(session).list_projects(customer, _page(page, page_size))


@router.post(
    "/projects",
    response_model=ProjectDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Создать проект",
)
async def create_project(
    payload: ProjectCreate, customer: CurrentCustomerDep, session: SessionDep
) -> ProjectDetail:
    return await CustomerAccountService(session).create_project(customer, payload)


@router.get("/projects/{project_uuid}", response_model=ProjectDetail, summary="Проект")
async def get_project(
    project_uuid: uuid.UUID, customer: CurrentCustomerDep, session: SessionDep
) -> ProjectDetail:
    return await CustomerAccountService(session).get_project(customer, project_uuid)


@router.patch("/projects/{project_uuid}", response_model=ProjectDetail, summary="Изменить проект")
async def update_project(
    project_uuid: uuid.UUID,
    payload: ProjectUpdate,
    customer: CurrentCustomerDep,
    session: SessionDep,
) -> ProjectDetail:
    return await CustomerAccountService(session).update_project(customer, project_uuid, payload)


@router.delete(
    "/projects/{project_uuid}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить проект"
)
async def delete_project(
    project_uuid: uuid.UUID, customer: CurrentCustomerDep, session: SessionDep
) -> None:
    await CustomerAccountService(session).delete_project(customer, project_uuid)


@router.post(
    "/projects/{project_uuid}/items",
    response_model=ProjectDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить товар в проект",
)
async def add_project_item(
    project_uuid: uuid.UUID,
    payload: ProjectItemAdd,
    customer: CurrentCustomerDep,
    session: SessionDep,
) -> ProjectDetail:
    return await CustomerAccountService(session).add_project_item(customer, project_uuid, payload)


@router.delete(
    "/projects/{project_uuid}/items/{sku}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Убрать позицию из проекта",
)
async def remove_project_item(
    project_uuid: uuid.UUID, sku: SkuPath, customer: CurrentCustomerDep, session: SessionDep
) -> None:
    await CustomerAccountService(session).remove_project_item(customer, project_uuid, sku)


# -------------------------------------------------------------- уведомления
@router.get("/notifications", response_model=Page[NotificationRead], summary="Уведомления")
async def list_notifications(
    customer: CurrentCustomerDep,
    session: SessionDep,
    unread: bool = False,
    page: PageQuery = 1,
    page_size: PageSizeQuery = DEFAULT_PAGE_SIZE,
) -> Page[NotificationRead]:
    return await CustomerAccountService(session).list_notifications(
        customer, _page(page, page_size), unread_only=unread
    )


@router.get(
    "/notifications/unread-count", response_model=UnreadCount, summary="Непрочитанные уведомления"
)
async def unread_count(customer: CurrentCustomerDep, session: SessionDep) -> UnreadCount:
    return await CustomerAccountService(session).unread_count(customer)


@router.post(
    "/notifications/read-all", response_model=UnreadCount, summary="Отметить все прочитанными"
)
async def mark_all_read(customer: CurrentCustomerDep, session: SessionDep) -> UnreadCount:
    return await CustomerAccountService(session).mark_all_read(customer)


@router.post(
    "/notifications/{notification_uuid}/read",
    response_model=NotificationRead,
    summary="Отметить уведомление прочитанным",
)
async def mark_read(
    notification_uuid: uuid.UUID, customer: CurrentCustomerDep, session: SessionDep
) -> NotificationRead:
    return await CustomerAccountService(session).mark_read(customer, notification_uuid)
