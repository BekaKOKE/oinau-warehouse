"""Схемы Admin API журнала аудита."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditUserRef(BaseModel):
    """Сотрудник, выполнивший действие.

    Идентификатор — uuid, как и во всём API пользователей: внутренний
    числовой id наружу не отдаётся.
    """

    uuid: uuid.UUID
    full_name: str
    email: str


class AuditLogRead(BaseModel):
    """Запись журнала.

    `ip_hash` намеренно не отдаётся: это псевдонимизированный адрес,
    и для чтения журнала человеком он бесполезен, а лишнее персональное
    значение в интерфейсе — лишний риск.
    """

    id: int
    created_at: datetime
    action: str
    # user | customer | system | import — кто выполнил действие.
    actor: str
    entity_type: str
    entity_id: int | None = None
    # null — действие выполнено не сотрудником (клиент, импорт, система)
    # или сотрудник с тех пор удалён.
    user: AuditUserRef | None = None
    # Только изменившиеся поля: {"price": {"old": "3500.00", "new": "3200.00"}}
    changes: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
