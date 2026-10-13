"""Безопасность интеграционного API: ключ, scope, IP, размер, частота.

Проверяется главное свойство: без действующего ключа наружу не
открыт ни один эндпоинт записи.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.integration.models import ApiKey
from app.modules.integration.security import (
    IntegrationScope,
    generate_api_key,
    hash_api_key,
    key_prefix,
)
from tests.integration_helpers import (
    HEALTH_URL,
    INVENTORY_URL,
    PRICING_URL,
    PRODUCTS_URL,
    REQUESTS_URL,
    TEST_API_KEY,
    auth_headers,
    make_api_key,
)

pytestmark = pytest.mark.asyncio

WRITE_ENDPOINTS = [PRODUCTS_URL, PRICING_URL, INVENTORY_URL]


@pytest.fixture(autouse=True)
def integration_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обмен включён: иначе все эндпоинты отвечают 503."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ONE_C_INTEGRATION_ENABLED", True)
    monkeypatch.setattr(settings, "INTEGRATION_IP_ALLOWLIST", [])


class TestKeyGeneration:
    def test_ключ_случаен_и_хранится_только_хешем(self) -> None:
        first, second = generate_api_key(), generate_api_key()

        assert first != second
        assert first.startswith("oik_")
        # В базу идёт SHA-256, не сам ключ.
        assert hash_api_key(first) != first
        assert len(hash_api_key(first)) == 64
        assert key_prefix(first) == first[:12]

    async def test_в_базе_нет_самого_ключа(self, committed_session: AsyncSession) -> None:
        key = generate_api_key()
        await make_api_key(committed_session, key=key)

        stored = (await committed_session.execute(select(ApiKey))).scalar_one()
        assert stored.key_hash == hash_api_key(key)
        assert key not in stored.key_hash
        # Префикс — для опознания в журнале, он не даёт войти.
        assert stored.key_prefix == key[:12]


class TestAuthentication:
    @pytest.mark.parametrize("url", WRITE_ENDPOINTS)
    async def test_без_ключа_запись_запрещена(self, api: AsyncClient, url: str) -> None:
        response = await api.post(url, json={"items": [{"sku": "X", "quantity": "1"}]})

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "integration_unauthenticated"

    async def test_неизвестный_ключ_отклоняется(
        self, api: AsyncClient, committed_session: AsyncSession
    ) -> None:
        await make_api_key(committed_session)

        response = await api.get(HEALTH_URL, headers=auth_headers("oik_wrong-key-value"))

        assert response.status_code == 401

    async def test_отозванный_ключ_отклоняется(
        self, api: AsyncClient, committed_session: AsyncSession
    ) -> None:
        await make_api_key(committed_session, is_active=False)

        response = await api.get(HEALTH_URL, headers=auth_headers())

        assert response.status_code == 401

    async def test_просроченный_ключ_отклоняется(
        self, api: AsyncClient, committed_session: AsyncSession
    ) -> None:
        await make_api_key(committed_session, expires_at=datetime.now(UTC) - timedelta(minutes=1))

        response = await api.get(HEALTH_URL, headers=auth_headers())

        assert response.status_code == 401

    async def test_ответ_не_подсказывает_причину_отказа(
        self, api: AsyncClient, committed_session: AsyncSession
    ) -> None:
        """Иначе эндпоинт превращается в оракул для проверки ключей."""
        await make_api_key(committed_session, is_active=False)

        revoked = await api.get(HEALTH_URL, headers=auth_headers())
        unknown = await api.get(HEALTH_URL, headers=auth_headers("oik_nonexistent"))

        def reason(response) -> tuple[str, str]:
            error = response.json()["error"]
            # request_id у каждого ответа свой — он не часть причины.
            return error["code"], error["message"]

        assert reason(revoked) == reason(unknown)

    async def test_действующий_ключ_проходит(
        self, api: AsyncClient, committed_session: AsyncSession
    ) -> None:
        await make_api_key(committed_session)

        response = await api.get(HEALTH_URL, headers=auth_headers())

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["key_name"] == "1С обмен (тест)"
        # Ни ключа, ни хеша в ответе нет.
        assert TEST_API_KEY not in response.text

    async def test_jwt_сотрудника_не_годится_для_обмена(
        self, api: AsyncClient, committed_session: AsyncSession, admin: dict[str, str]
    ) -> None:
        """Разные субъекты — разные схемы аутентификации."""
        await make_api_key(committed_session)

        response = await api.post(PRODUCTS_URL, json={"items": []}, headers=admin)

        assert response.status_code == 401


class TestScopes:
    async def test_ключ_без_нужного_scope_получает_403(
        self, api: AsyncClient, committed_session: AsyncSession
    ) -> None:
        """Обмен остатками не должен уметь переписывать каталог."""
        await make_api_key(committed_session, scopes=[IntegrationScope.INVENTORY_WRITE])

        response = await api.post(
            PRODUCTS_URL, json={"items": [{"sku": "X"}]}, headers=auth_headers()
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "integration_scope_denied"

    async def test_свой_scope_работает(
        self, api: AsyncClient, committed_session: AsyncSession, catalog
    ) -> None:
        await make_api_key(committed_session, scopes=[IntegrationScope.INVENTORY_WRITE])

        response = await api.post(
            INVENTORY_URL,
            json={"items": [{"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "5"}]},
            headers=auth_headers(),
        )

        assert response.status_code == 200

    async def test_заявки_требуют_отдельного_права(
        self, api: AsyncClient, committed_session: AsyncSession
    ) -> None:
        await make_api_key(committed_session, scopes=[IntegrationScope.CATALOG_WRITE])

        response = await api.get(REQUESTS_URL, headers=auth_headers())

        assert response.status_code == 403


class TestIpAllowlist:
    async def test_адрес_вне_списка_отклоняется(
        self, api: AsyncClient, committed_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.config import settings

        await make_api_key(committed_session)
        monkeypatch.setattr(settings, "INTEGRATION_IP_ALLOWLIST", ["10.0.0.1"])

        response = await api.get(HEALTH_URL, headers=auth_headers())

        assert response.status_code == 401
        # Тот же код, что у неизвестного ключа: перебор адресов не
        # должен подсказывать, что ключ верен.
        assert response.json()["error"]["code"] == "integration_unauthenticated"

    async def test_пустой_список_означает_проверку_выключенной(
        self, api: AsyncClient, committed_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.config import settings

        await make_api_key(committed_session)
        monkeypatch.setattr(settings, "INTEGRATION_IP_ALLOWLIST", [])

        assert (await api.get(HEALTH_URL, headers=auth_headers())).status_code == 200


class TestDisabledIntegration:
    async def test_выключенный_обмен_отвечает_503_даже_с_верным_ключом(
        self, api: AsyncClient, committed_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ключ можно завести заранее, а обмен — включить позже."""
        from app.core.config import settings

        await make_api_key(committed_session)
        monkeypatch.setattr(settings, "ONE_C_INTEGRATION_ENABLED", False)

        response = await api.get(HEALTH_URL, headers=auth_headers())

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "integration_disabled"


class TestLimits:
    async def test_слишком_большое_тело_отклоняется_до_разбора(
        self, api: AsyncClient, committed_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.config import settings

        await make_api_key(committed_session)
        monkeypatch.setattr(settings, "INTEGRATION_MAX_BODY_BYTES", 100)

        response = await api.post(
            INVENTORY_URL,
            json={
                "items": [
                    {"sku": f"SKU-{i}", "warehouse_code": "main", "quantity": "1"}
                    for i in range(50)
                ]
            },
            headers=auth_headers(),
        )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"

    async def test_слишком_много_позиций_в_пакете(
        self, api: AsyncClient, committed_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.config import settings

        await make_api_key(committed_session)
        monkeypatch.setattr(settings, "INTEGRATION_MAX_BATCH_ITEMS", 2)

        response = await api.post(
            INVENTORY_URL,
            json={
                "items": [
                    {"sku": f"SKU-{i}", "warehouse_code": "main", "quantity": "1"} for i in range(3)
                ]
            },
            headers=auth_headers(),
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "batch_too_large"

    async def test_норма_частоты_считается_на_ключ(
        self, api: AsyncClient, committed_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """1С обычно за общим NAT: лимит по IP ограничивал бы весь офис."""
        from app.core.config import settings

        await make_api_key(committed_session)
        monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
        monkeypatch.setattr(settings, "RATE_LIMIT_INTEGRATION", "2/minute")

        body = {"items": [{"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "1"}]}
        statuses = [
            (await api.post(INVENTORY_URL, json=body, headers=auth_headers())).status_code
            for _ in range(4)
        ]

        assert 429 in statuses
        assert statuses.count(429) >= 1
