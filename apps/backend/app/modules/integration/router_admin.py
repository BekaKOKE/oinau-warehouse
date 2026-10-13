"""Состояние интеграций для админки — /api/v1/admin/integration.

Только безопасные операционные сведения: включён ли канал, когда был
последний обмен и чем он закончился. Ни токена бота, ни пароля SMTP,
ни ключей интеграции здесь нет и быть не может — наружу отдаются
факты «настроено / не настроено», а не значения.

Право — существующее `settings.write` (ADMIN и SUPERADMIN): это
эксплуатационная настройка системы, а не бизнес-данные.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep, require_permissions
from app.modules.integration.schemas_admin import IntegrationStatus
from app.modules.integration.service_admin import IntegrationStatusService
from app.modules.users.models import User
from app.modules.users.permissions import SETTINGS_WRITE

SettingsManager = Annotated[User, Depends(require_permissions(SETTINGS_WRITE))]

router = APIRouter(prefix="/integration", tags=["admin:integration"])


@router.get("/status", response_model=IntegrationStatus, summary="Состояние интеграций")
async def get_status(session: SessionDep, _: SettingsManager) -> IntegrationStatus:
    """Что включено и как прошёл последний обмен. Без реквизитов."""
    return await IntegrationStatusService(session).get_status()
