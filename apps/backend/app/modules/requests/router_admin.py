"""Admin API заявок — /api/v1/admin/requests.

Чтение — `request.read`, изменения (статус, комментарии) —
`request.write`. Оба права уже есть в матрице ролей: MANAGER получает
чтение и запись заявок, VIEWER — только чтение, CONTENT_MANAGER —
ни того, ни другого. Новых прав не вводится.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.api.deps import SessionDep, require_permissions
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams
from app.modules.notifications.queue import NotificationQueue, get_notification_queue
from app.modules.requests.enums import RequestSource, RequestStatus
from app.modules.requests.exceptions import InvalidDateRangeError
from app.modules.requests.repository_admin import (
    MAX_SEARCH_LENGTH,
    RequestAdminFilters,
    RequestAdminSort,
)
from app.modules.requests.schemas_admin import (
    RequestCommentCreate,
    RequestCommentRead,
    RequestDetail,
    RequestListItem,
    RequestStatusHistoryRead,
    RequestStatusUpdate,
)
from app.modules.requests.service_admin import AdminRequestService
from app.modules.users.models import User
from app.modules.users.permissions import REQUEST_READ, REQUEST_WRITE

RequestReader = Annotated[User, Depends(require_permissions(REQUEST_READ))]
RequestWriter = Annotated[User, Depends(require_permissions(REQUEST_WRITE))]

IdPath = Annotated[int, Path(ge=1)]

router = APIRouter(prefix="/requests", tags=["admin:requests"])

NotificationQueueDep = Annotated[NotificationQueue, Depends(get_notification_queue)]


def _as_utc(value: datetime | None) -> datetime | None:
    """Время без часового пояса считается UTC — так хранятся все
    метки. Перевод в Asia/Almaty — забота фронтенда."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


@router.get("", response_model=Page[RequestListItem], summary="Список заявок")
async def list_requests(
    session: SessionDep,
    _: RequestReader,
    request_status: Annotated[RequestStatus | None, Query(alias="status")] = None,
    source: Annotated[RequestSource | None, Query(description="Откуда пришла заявка")] = None,
    region_id: Annotated[int | None, Query(ge=1)] = None,
    created_from: Annotated[
        datetime | None, Query(description="Создана не раньше (включительно)")
    ] = None,
    created_to: Annotated[datetime | None, Query(description="Создана раньше (исключительно)")] = (
        None
    ),
    search: Annotated[
        str | None,
        Query(max_length=MAX_SEARCH_LENGTH, description="Номер, имя, телефон, email, компания"),
    ] = None,
    sort: RequestAdminSort = RequestAdminSort.NEWEST,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[RequestListItem]:
    """Новые заявки сверху. Удалённые (мягко) не показываются."""
    created_from = _as_utc(created_from)
    created_to = _as_utc(created_to)
    if created_from is not None and created_to is not None and created_from >= created_to:
        raise InvalidDateRangeError

    filters = RequestAdminFilters(
        status=request_status.value if request_status else None,
        source=source.value if source else None,
        region_id=region_id,
        created_from=created_from,
        created_to=created_to,
        search=search,
    )
    return await AdminRequestService(session).list_requests(
        filters=filters, sort=sort, params=PageParams(page=page, page_size=page_size)
    )


@router.get("/{request_id}", response_model=RequestDetail, summary="Карточка заявки")
async def get_request(
    request_id: IdPath,
    session: SessionDep,
    _: RequestReader,
) -> RequestDetail:
    """Контакты, состав со снапшотами цен, комментарии и история статусов."""
    return await AdminRequestService(session).get_request(request_id)


@router.get(
    "/{request_id}/attachments/{attachment_id}",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "Файл"}},
    summary="Скачать файл заявки",
)
async def download_attachment(
    request_id: IdPath,
    attachment_id: IdPath,
    session: SessionDep,
    _: RequestReader,
) -> Response:
    """Файл, приложенный клиентом к запросу КП.

    Всегда отдаётся как вложение и с запретом угадывать тип: файл
    прислал анонимный посетитель, и открыть его «на месте» в контексте
    админки было бы небезопасно (HTML или SVG под видом PDF).
    """
    attachment = await AdminRequestService(session).get_attachment(request_id, attachment_id)
    return Response(
        content=attachment.data,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": _content_disposition(attachment.filename),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "private, no-store",
        },
    )


def _content_disposition(filename: str) -> str:
    """Имя файла по RFC 6266: ASCII-запасное и полное в UTF-8.

    Кириллица в `filename="…"` ломает заголовок в части клиентов,
    поэтому оно дублируется в `filename*` с процентной кодировкой.
    """
    fallback = "".join(
        char if char.isascii() and char.isprintable() and char not in '"\\' else "_"
        for char in filename
    )
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.patch("/{request_id}/status", response_model=RequestDetail, summary="Сменить статус")
async def update_status(
    request_id: IdPath,
    payload: RequestStatusUpdate,
    session: SessionDep,
    actor: RequestWriter,
    delivery: NotificationQueueDep,
) -> RequestDetail:
    """Переход в любой статус. Повтор текущего статуса ничего не меняет."""
    return await AdminRequestService(session, delivery).update_status(request_id, payload, actor)


@router.get(
    "/{request_id}/comments",
    response_model=list[RequestCommentRead],
    summary="Комментарии к заявке",
)
async def list_comments(
    request_id: IdPath,
    session: SessionDep,
    _: RequestReader,
) -> list[RequestCommentRead]:
    return await AdminRequestService(session).list_comments(request_id)


@router.post(
    "/{request_id}/comments",
    response_model=RequestCommentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить внутренний комментарий",
)
async def add_comment(
    request_id: IdPath,
    payload: RequestCommentCreate,
    session: SessionDep,
    actor: RequestWriter,
    delivery: NotificationQueueDep,
) -> RequestCommentRead:
    """По умолчанию комментарий внутренний: клиент его не видит.

    Видимый комментарий (`visible_to_customer`) попадает в кабинет и,
    если адрес клиента подтверждён, уходит письмом.
    """
    return await AdminRequestService(session, delivery).add_comment(request_id, payload, actor)


@router.get(
    "/{request_id}/history",
    response_model=list[RequestStatusHistoryRead],
    summary="История статусов",
)
async def list_history(
    request_id: IdPath,
    session: SessionDep,
    _: RequestReader,
) -> list[RequestStatusHistoryRead]:
    return await AdminRequestService(session).list_history(request_id)
