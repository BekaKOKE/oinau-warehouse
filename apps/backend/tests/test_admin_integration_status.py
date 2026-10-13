"""Состояние интеграций в админке.

Главное свойство раздела: он показывает «настроено / не настроено»
и итоги обменов — и ни одного реквизита.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.enums import UserRole
from tests.integration_helpers import (
    ADMIN_STATUS_URL,
    INVENTORY_URL,
    TEST_API_KEY,
    auth_headers,
    make_api_key,
)

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "7777777:AAH-real-looking-bot-token"
SMTP_PASSWORD = "very-secret-smtp-password"


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", ["-1001", "-1002"])
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", SMTP_PASSWORD)
    monkeypatch.setattr(settings, "NOTIFY_EMAILS", ["sales@oinau-pro.kz"])
    monkeypatch.setattr(settings, "ONE_C_INTEGRATION_ENABLED", True)
    monkeypatch.setattr(settings, "INTEGRATION_IP_ALLOWLIST", [])


class TestAccess:
    async def test_требует_права_настроек(
        self, api: AsyncClient, login_as, configured: None
    ) -> None:
        for role in (UserRole.MANAGER, UserRole.CONTENT_MANAGER, UserRole.VIEWER):
            headers = await login_as(role)
            response = await api.get(ADMIN_STATUS_URL, headers=headers)
            assert response.status_code == 403, role

    async def test_администратор_видит_состояние(
        self, api: AsyncClient, admin: dict[str, str], configured: None
    ) -> None:
        response = await api.get(ADMIN_STATUS_URL, headers=admin)

        assert response.status_code == 200
        body = response.json()
        assert {channel["channel"] for channel in body["channels"]} == {"telegram", "email"}
        assert body["one_c_enabled"] is True

    async def test_анонимный_доступ_закрыт(self, api: AsyncClient) -> None:
        assert (await api.get(ADMIN_STATUS_URL)).status_code == 401


class TestSafety:
    async def test_реквизиты_наружу_не_отдаются(
        self, api: AsyncClient, admin: dict[str, str], configured: None, committed_session
    ) -> None:
        """Ни токена бота, ни пароля SMTP, ни ключа интеграции."""
        await make_api_key(committed_session)

        body = (await api.get(ADMIN_STATUS_URL, headers=admin)).text

        assert BOT_TOKEN not in body
        assert SMTP_PASSWORD not in body
        assert TEST_API_KEY not in body
        assert "smtp.test" not in body
        # Адреса получателей — тоже данные: показывается только их число.
        assert "sales@oinau-pro.kz" not in body
        assert "-1001" not in body

    async def test_количество_получателей_показывается_числом(
        self, api: AsyncClient, admin: dict[str, str], configured: None
    ) -> None:
        body = (await api.get(ADMIN_STATUS_URL, headers=admin)).json()

        telegram = next(c for c in body["channels"] if c["channel"] == "telegram")
        assert telegram["enabled"] is True
        assert telegram["recipients"] == 2

    async def test_активные_ключи_считаются_но_не_раскрываются(
        self, api: AsyncClient, admin: dict[str, str], configured: None, committed_session
    ) -> None:
        await make_api_key(committed_session)

        body = (await api.get(ADMIN_STATUS_URL, headers=admin)).json()

        assert body["api_keys_active"] == 1


class TestChannelState:
    async def test_ненастроенный_канал_объясняет_причину(
        self, api: AsyncClient, admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
        monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")

        body = (await api.get(ADMIN_STATUS_URL, headers=admin)).json()

        telegram = next(c for c in body["channels"] if c["channel"] == "telegram")
        assert telegram["enabled"] is False
        assert telegram["reason"] == "not_configured"

    async def test_общий_выключатель_виден_отдельно(
        self, api: AsyncClient, admin: dict[str, str], configured: None, monkeypatch
    ) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)

        body = (await api.get(ADMIN_STATUS_URL, headers=admin)).json()

        assert all(channel["reason"] == "disabled_globally" for channel in body["channels"])


class TestSyncHistory:
    async def test_последний_обмен_и_последний_сбой_видны(
        self,
        api: AsyncClient,
        admin: dict[str, str],
        committed_session: AsyncSession,
        catalog,
        configured: None,
    ) -> None:
        await make_api_key(committed_session)
        # Успешный обмен.
        await api.post(
            INVENTORY_URL,
            json={"items": [{"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "5"}]},
            headers=auth_headers(),
        )
        # Обмен со сбоем строки.
        await api.post(
            INVENTORY_URL,
            json={"items": [{"sku": "KAN-16-PP", "warehouse_code": "нет", "quantity": "5"}]},
            headers=auth_headers(),
        )

        body = (await api.get(ADMIN_STATUS_URL, headers=admin)).json()

        assert body["last_syncs"]
        assert body["last_syncs"][0]["entity"] == "stock"
        assert body["last_failure"] is not None
        assert body["last_failure"]["failed"] == 1

    async def test_очередь_уведомлений_показывается_счётчиками(
        self, api: AsyncClient, admin: dict[str, str], committed_session: AsyncSession, configured
    ) -> None:
        from app.modules.notifications.enums import NotificationChannel, NotificationEvent
        from app.modules.notifications.service import NotificationService

        NotificationService(committed_session).enqueue(
            event=NotificationEvent.REQUEST_CREATED,
            channel=NotificationChannel.TELEGRAM,
            recipient="-1001",
            payload={"number": "R-1"},
        )
        await committed_session.commit()

        body = (await api.get(ADMIN_STATUS_URL, headers=admin)).json()

        assert body["outbox"]["pending"] == 1
        assert body["outbox"]["sent"] == 0
