"""Чтение журнала аудита."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select

from app.core.pagination import PageParams
from app.core.repository import BaseRepository
from app.db.types import LEN_CODE, LEN_STATUS
from app.modules.audit.models import AuditLog
from app.modules.users.models import User

# Пределы длины совпадают с колонками audit_log: длиннее значения
# в таблице быть не может, и такой фильтр заведомо ничего не найдёт.
MAX_ACTION_LENGTH = LEN_CODE
MAX_ENTITY_TYPE_LENGTH = LEN_CODE
MAX_ACTOR_LENGTH = LEN_STATUS
MAX_REQUEST_ID_LENGTH = 64


@dataclass(frozen=True)
class AuditFilters:
    action: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    user_uuid: uuid.UUID | None = None
    actor: str | None = None
    request_id: str | None = None
    # Полуинтервал [created_from, created_to), как у списка заявок.
    created_from: datetime | None = None
    created_to: datetime | None = None


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    def _filtered(self, filters: AuditFilters) -> Select[tuple[AuditLog, User]]:
        # LEFT JOIN: запись переживает удаление сотрудника (FK SET NULL),
        # а действия клиента и импорта сотрудника не имеют вовсе.
        # Тип строки — (AuditLog, User): SQLAlchemy не выражает в типах, что
        # после outerjoin пользователь может быть None; это учтено ниже.
        query = select(AuditLog, User).outerjoin(User, User.id == AuditLog.user_id)
        if filters.action is not None:
            query = query.where(AuditLog.action == filters.action)
        if filters.entity_type is not None:
            query = query.where(AuditLog.entity_type == filters.entity_type)
        if filters.entity_id is not None:
            query = query.where(AuditLog.entity_id == filters.entity_id)
        if filters.user_uuid is not None:
            query = query.where(User.uuid == filters.user_uuid)
        if filters.actor is not None:
            query = query.where(AuditLog.actor == filters.actor)
        if filters.request_id is not None:
            query = query.where(AuditLog.request_id == filters.request_id)
        if filters.created_from is not None:
            query = query.where(AuditLog.created_at >= filters.created_from)
        if filters.created_to is not None:
            query = query.where(AuditLog.created_at < filters.created_to)
        return query

    async def list_entries(
        self, *, filters: AuditFilters, params: PageParams
    ) -> tuple[Sequence[tuple[AuditLog, User | None]], int]:
        query = self._filtered(filters)
        total = (
            await self.session.execute(
                select(func.count()).select_from(query.with_only_columns(AuditLog.id).subquery())
            )
        ).scalar_one()
        # Порядок совпадает с индексом ix_audit_log_created_at; id —
        # тай-брейкер для записей одной транзакции с равным временем.
        rows = await self.session.execute(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
        return [(row[0], row[1]) for row in rows.all()], total
