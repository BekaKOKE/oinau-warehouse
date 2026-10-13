"""Границы доступа между кабинетом клиента и остальными поверхностями API.

Клиент не должен попадать в админку, к остаткам, журналу аудита
и служебным интеграциям; сотрудник — в кабинет клиента. Проверяется
на уровне HTTP, как это увидел бы атакующий.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import JWT_AUDIENCE, JWT_CUSTOMER_AUDIENCE, JWT_ISSUER
from tests.catalog_fixtures import CatalogFixture
from tests.customer_helpers import (
    FAVORITES_URL,
    NOTIFICATIONS_URL,
    PROFILE_URL,
    PROJECTS_URL,
    REQUESTS_URL,
)

Headers = dict[str, str]

ADMIN_ENDPOINTS = [
    ("GET", "/api/v1/admin/auth/me"),
    ("GET", "/api/v1/admin/users"),
    ("GET", "/api/v1/admin/requests"),
    ("GET", "/api/v1/admin/requests/1"),
    ("POST", "/api/v1/admin/requests/1/comments"),
    ("GET", "/api/v1/admin/warehouses"),
    ("GET", "/api/v1/admin/products"),
    ("GET", "/api/v1/admin/content/home"),
    ("GET", "/api/v1/admin/catalog/imports"),
]

CUSTOMER_ENDPOINTS = [
    ("GET", PROFILE_URL),
    ("GET", FAVORITES_URL),
    ("GET", REQUESTS_URL),
    ("GET", PROJECTS_URL),
    ("GET", NOTIFICATIONS_URL),
    ("GET", f"{NOTIFICATIONS_URL}/unread-count"),
]


@pytest.mark.parametrize(("method", "path"), ADMIN_ENDPOINTS)
async def test_customer_token_is_rejected_by_admin_api(
    api: AsyncClient, customer_headers, method: str, path: str
) -> None:
    _, headers = await customer_headers()
    response = await api.request(method, path, headers=headers, json={"body": "x"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize(("method", "path"), CUSTOMER_ENDPOINTS)
async def test_admin_token_is_rejected_by_customer_api(
    api: AsyncClient, admin: Headers, method: str, path: str
) -> None:
    response = await api.request(method, path, headers=admin)
    assert response.status_code == 401


@pytest.mark.parametrize(("method", "path"), CUSTOMER_ENDPOINTS)
async def test_customer_api_requires_token(api: AsyncClient, method: str, path: str) -> None:
    assert (await api.request(method, path)).status_code == 401
    garbage = await api.request(method, path, headers={"Authorization": "Bearer not-a-jwt"})
    assert garbage.status_code == 401


def _forge(subject: uuid.UUID, *, audience: str, secret: str, pwv: int = 0) -> Headers:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(subject),
            "typ": "access",
            "role": "CUSTOMER",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
            "iss": JWT_ISSUER,
            "aud": audience,
            "pwv": pwv,
        },
        secret,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_forged_tokens_are_rejected(api: AsyncClient, make_customer) -> None:
    customer = await make_customer()

    wrong_secret = _forge(customer.uuid, audience=JWT_CUSTOMER_AUDIENCE, secret="x" * 64)
    admin_audience = _forge(customer.uuid, audience=JWT_AUDIENCE, secret=settings.SECRET_KEY)
    valid = _forge(customer.uuid, audience=JWT_CUSTOMER_AUDIENCE, secret=settings.SECRET_KEY)

    assert (await api.get(PROFILE_URL, headers=wrong_secret)).status_code == 401
    assert (await api.get(PROFILE_URL, headers=admin_audience)).status_code == 401
    # Контроль: правильно подписанный токен кабинета принимается
    assert (await api.get(PROFILE_URL, headers=valid)).status_code == 200


async def test_customer_token_cannot_impersonate_staff(
    api: AsyncClient, make_customer, make_user
) -> None:
    """Даже если uuid клиента совпал бы с uuid сотрудника, аудитории разные."""
    user = await make_user()
    forged = _forge(user.uuid, audience=JWT_CUSTOMER_AUDIENCE, secret=settings.SECRET_KEY)
    assert (await api.get("/api/v1/admin/auth/me", headers=forged)).status_code == 401
    assert (await api.get(PROFILE_URL, headers=forged)).status_code == 401


async def test_deactivated_or_deleted_customer_loses_access_immediately(
    api: AsyncClient, customer_headers, committed_session: AsyncSession
) -> None:
    alice, alice_headers = await customer_headers()
    bob, bob_headers = await customer_headers()

    alice.is_active = False
    committed_session.add(alice)
    bob.deleted_at = datetime.now(UTC)
    committed_session.add(bob)
    await committed_session.commit()

    assert (await api.get(PROFILE_URL, headers=alice_headers)).status_code == 401
    assert (await api.get(PROFILE_URL, headers=bob_headers)).status_code == 401


async def test_customer_cannot_reach_stock_or_integration(
    api: AsyncClient, catalog: CatalogFixture, customer_headers
) -> None:
    _, headers = await customer_headers()
    stock_paths = [
        "/api/v1/admin/warehouses",
        f"/api/v1/admin/products/{catalog.products['rope'].id}/stock",
        f"/api/v1/admin/products/{catalog.products['rope'].id}/pricing",
    ]
    for path in stock_paths:
        assert (await api.get(path, headers=headers)).status_code == 401

    # Интеграционная поверхность не содержит клиентских маршрутов.
    # 503 — обмен выключен настройкой: этот выключатель намеренно стоит
    # ПЕРЕД аутентификацией, поэтому выключенный обмен закрыт для всех,
    # включая клиента с действующим токеном кабинета.
    for path in ("/api/v1/integration/requests", "/api/v1/integration/catalog"):
        response = await api.get(path, headers=headers)
        assert response.status_code in {401, 404, 503}
        assert "items" not in response.json()


async def test_customer_api_does_not_expose_internal_ids(
    api: AsyncClient, catalog: CatalogFixture, customer_headers
) -> None:
    _, headers = await customer_headers()
    project = (await api.post(PROJECTS_URL, headers=headers, json={"name": "Проект"})).json()
    profile = (await api.get(PROFILE_URL, headers=headers)).json()

    assert "id" not in project
    assert "customer_id" not in project
    assert "id" not in profile
    assert "password_hash" not in profile
