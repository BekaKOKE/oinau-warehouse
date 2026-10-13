"""Admin API журнала аудита: только чтение.

Журнал пишут сервисы доменов в своих транзакциях; через API он не
изменяется и не удаляется — иначе перестал бы быть журналом.
"""

from __future__ import annotations

from app.core.pagination import Page, PageParams
from app.core.service import BaseService
from app.modules.audit.models import AuditLog
from app.modules.audit.repository import AuditFilters, AuditLogRepository
from app.modules.audit.schemas import AuditLogRead, AuditUserRef
from app.modules.users.models import User


class AdminAuditService(BaseService):
    async def list_entries(
        self, *, filters: AuditFilters, params: PageParams
    ) -> Page[AuditLogRead]:
        rows, total = await AuditLogRepository(self.session).list_entries(
            filters=filters, params=params
        )
        return Page.create([self._to_read(entry, user) for entry, user in rows], total, params)

    @staticmethod
    def _to_read(entry: AuditLog, user: User | None) -> AuditLogRead:
        return AuditLogRead(
            id=entry.id,
            created_at=entry.created_at,
            action=entry.action,
            actor=entry.actor,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            user=(
                AuditUserRef(uuid=user.uuid, full_name=user.full_name, email=user.email)
                if user is not None
                else None
            ),
            changes=entry.changes or {},
            request_id=entry.request_id,
        )
