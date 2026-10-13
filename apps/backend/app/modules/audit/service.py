"""Запись событий в журнал аудита."""

from __future__ import annotations

from typing import Any

from app.core.service import BaseService
from app.modules.audit.models import AuditLog


class AuditAction:
    LOGIN_SUCCESS = "auth.login_success"
    LOGIN_FAILED = "auth.login_failed"
    LOGIN_BLOCKED = "auth.login_blocked"
    LOGOUT = "auth.logout"
    TOKEN_REFRESHED = "auth.token_refreshed"  # noqa: S105
    TOKEN_REUSE_DETECTED = "auth.token_reuse_detected"  # noqa: S105
    PASSWORD_CHANGED = "auth.password_changed"  # noqa: S105


class AuditService(BaseService):
    def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: int | None = None,
        user_id: int | None = None,
        actor: str = "user",
        changes: dict[str, Any] | None = None,
        ip_hash: str | None = None,
        request_id: str | None = None,
    ) -> AuditLog:
        """Добавляет запись в текущую транзакцию.

        Не коммитит: журнал должен фиксироваться той же транзакцией, что
        и само изменение. Иначе возможна запись "цена изменена" при
        откате изменения цены — или наоборот.
        """
        entry = AuditLog(
            user_id=user_id,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=changes or {},
            ip_hash=ip_hash,
            request_id=request_id,
        )
        self.session.add(entry)
        return entry
