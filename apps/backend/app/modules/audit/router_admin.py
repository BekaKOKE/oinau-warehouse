"""Admin API журнала аудита — /api/v1/admin/audit.

Право — существующее `audit.read` (ADMIN, SUPERADMIN). Новых прав
не вводится. Эндпоинт только читает таблицу audit_log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep, require_permissions
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams
from app.modules.audit.repository import (
    MAX_ACTION_LENGTH,
    MAX_ACTOR_LENGTH,
    MAX_ENTITY_TYPE_LENGTH,
    MAX_REQUEST_ID_LENGTH,
    AuditFilters,
)
from app.modules.audit.schemas import AuditLogRead
from app.modules.audit.service_admin import AdminAuditService
from app.modules.requests.exceptions import InvalidDateRangeError
from app.modules.users.models import User
from app.modules.users.permissions import AUDIT_READ

AuditReader = Annotated[User, Depends(require_permissions(AUDIT_READ))]

router = APIRouter(prefix="/audit", tags=["admin:audit"])


def _as_utc(value: datetime | None) -> datetime | None:
    """Время без часового пояса считается UTC — так хранятся все метки."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


@router.get("", response_model=Page[AuditLogRead], summary="Журнал аудита")
async def list_audit_log(
    session: SessionDep,
    _: AuditReader,
    action: Annotated[
        str | None,
        Query(
            max_length=MAX_ACTION_LENGTH, description="Действие, например request.status_updated"
        ),
    ] = None,
    entity_type: Annotated[
        str | None, Query(max_length=MAX_ENTITY_TYPE_LENGTH, description="Тип сущности: product")
    ] = None,
    entity_id: Annotated[int | None, Query(ge=1)] = None,
    user_uuid: Annotated[uuid.UUID | None, Query(description="Сотрудник-автор")] = None,
    actor: Annotated[
        str | None, Query(max_length=MAX_ACTOR_LENGTH, description="user, customer, system")
    ] = None,
    request_id: Annotated[str | None, Query(max_length=MAX_REQUEST_ID_LENGTH)] = None,
    created_from: Annotated[datetime | None, Query(description="Не раньше (включительно)")] = None,
    created_to: Annotated[datetime | None, Query(description="Раньше (исключительно)")] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[AuditLogRead]:
    """Новые записи сверху. Журнал доступен только для чтения."""
    created_from = _as_utc(created_from)
    created_to = _as_utc(created_to)
    if created_from is not None and created_to is not None and created_from >= created_to:
        raise InvalidDateRangeError
    filters = AuditFilters(
        action=action or None,
        entity_type=entity_type or None,
        entity_id=entity_id,
        user_uuid=user_uuid,
        actor=actor or None,
        request_id=request_id or None,
        created_from=created_from,
        created_to=created_to,
    )
    return await AdminAuditService(session).list_entries(
        filters=filters, params=PageParams(page=page, page_size=page_size)
    )
