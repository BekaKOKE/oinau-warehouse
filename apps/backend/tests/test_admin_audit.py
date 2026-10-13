"""Admin API журнала аудита: чтение, фильтры, права."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.users.enums import UserRole
from app.modules.users.models import User
from tests.conftest import DEFAULT_PASSWORD, Headers
from tests.helpers import count_queries

AUDIT = "/api/v1/admin/audit"
WAREHOUSES = "/api/v1/admin/warehouses"
LOGIN = "/api/v1/admin/auth/login"


async def _login(api: AsyncClient, email: str, request_id: str | None = None) -> Headers:
    headers = {"X-Request-ID": request_id} if request_id else {}
    response = await api.post(
        LOGIN, json={"email": email, "password": DEFAULT_PASSWORD}, headers=headers
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def staff(api: AsyncClient, make_user) -> tuple[Headers, User]:
    """Администратор, вошедший с известным request id."""
    user = await make_user(role=UserRole.ADMIN, full_name="Айгерим Серикова")
    headers = await _login(api, user.email, request_id="req-audit-login")
    return headers, user


# ================================================================ чтение
async def test_lists_real_entries_newest_first_with_actor(
    api: AsyncClient, staff: tuple[Headers, User]
) -> None:
    headers, user = staff
    created = await api.post(WAREHOUSES, headers=headers, json={"code": "main", "name": "Склад"})
    assert created.status_code == 201

    response = await api.get(AUDIT, headers=headers)
    assert response.status_code == 200
    body = response.json()

    actions = [item["action"] for item in body["items"]]
    # Создание склада случилось после входа — и стоит выше.
    assert actions.index("inventory.warehouse_created") < actions.index("auth.login_success")

    entry = next(i for i in body["items"] if i["action"] == "inventory.warehouse_created")
    assert entry["entity_type"] == "warehouse"
    assert entry["entity_id"] == created.json()["id"]
    assert entry["actor"] == "user"
    assert entry["user"] == {
        "uuid": str(user.uuid),
        "full_name": "Айгерим Серикова",
        "email": user.email,
    }
    assert entry["changes"] == {"code": {"old": None, "new": "main"}}


async def test_does_not_expose_ip_hash_or_internal_user_id(
    api: AsyncClient, staff: tuple[Headers, User]
) -> None:
    headers, _ = staff
    body = (await api.get(AUDIT, headers=headers)).json()
    login = next(i for i in body["items"] if i["action"] == "auth.login_success")
    assert "ip_hash" not in login
    assert "user_id" not in login
    assert set(login) == {
        "id",
        "created_at",
        "action",
        "actor",
        "entity_type",
        "entity_id",
        "user",
        "changes",
        "request_id",
    }


async def test_entries_without_staff_user_have_null_user(
    api: AsyncClient, staff: tuple[Headers, User], committed_session: AsyncSession
) -> None:
    """Импорт, клиент, система: user пуст, actor объясняет, кто это был."""
    headers, _ = staff
    committed_session.add(
        AuditLog(actor="system", action="media.processed", entity_type="media_file", entity_id=7)
    )
    await committed_session.commit()

    body = (await api.get(AUDIT, headers=headers, params={"actor": "system"})).json()
    assert body["total"] == 1
    assert body["items"][0]["user"] is None
    assert body["items"][0]["entity_id"] == 7


# =============================================================== фильтры
async def test_filters_by_action_entity_and_request_id(
    api: AsyncClient, staff: tuple[Headers, User]
) -> None:
    headers, _ = staff
    first = (await api.post(WAREHOUSES, headers=headers, json={"code": "a", "name": "A"})).json()
    await api.post(WAREHOUSES, headers=headers, json={"code": "b", "name": "B"})

    by_action = (
        await api.get(AUDIT, headers=headers, params={"action": "inventory.warehouse_created"})
    ).json()
    assert by_action["total"] == 2

    by_entity = (
        await api.get(
            AUDIT, headers=headers, params={"entity_type": "warehouse", "entity_id": first["id"]}
        )
    ).json()
    assert by_entity["total"] == 1
    assert by_entity["items"][0]["entity_id"] == first["id"]

    by_request = (
        await api.get(AUDIT, headers=headers, params={"request_id": "req-audit-login"})
    ).json()
    assert by_request["total"] == 1
    assert by_request["items"][0]["action"] == "auth.login_success"


async def test_filters_by_staff_user(
    api: AsyncClient, staff: tuple[Headers, User], make_user
) -> None:
    headers, user = staff
    other = await make_user(role=UserRole.MANAGER)
    await _login(api, other.email)

    mine = (
        await api.get(
            AUDIT,
            headers=headers,
            params={"user_uuid": str(user.uuid)},
        )
    ).json()
    theirs = (await api.get(AUDIT, headers=headers, params={"user_uuid": str(other.uuid)})).json()

    assert mine["total"] >= 1
    assert all(item["user"]["uuid"] == str(user.uuid) for item in mine["items"])
    assert theirs["total"] == 1
    assert theirs["items"][0]["user"]["uuid"] == str(other.uuid)


async def test_filters_by_date_range(api: AsyncClient, staff: tuple[Headers, User]) -> None:
    headers, _ = staff
    now = datetime.now(UTC)

    past = (
        await api.get(
            AUDIT,
            headers=headers,
            params={"created_from": (now - timedelta(hours=1)).isoformat()},
        )
    ).json()
    future = (
        await api.get(
            AUDIT,
            headers=headers,
            params={"created_from": (now + timedelta(hours=1)).isoformat()},
        )
    ).json()
    assert past["total"] >= 1
    assert future["total"] == 0

    inverted = await api.get(
        AUDIT,
        headers=headers,
        params={"created_from": now.isoformat(), "created_to": now.isoformat()},
    )
    assert inverted.status_code == 422
    assert inverted.json()["error"]["code"] == "invalid_date_range"


async def test_pagination(
    api: AsyncClient, staff: tuple[Headers, User], committed_session: AsyncSession
) -> None:
    headers, _ = staff
    committed_session.add_all(
        AuditLog(actor="system", action="test.bulk", entity_type="thing", entity_id=index)
        for index in range(1, 8)
    )
    await committed_session.commit()

    first = (
        await api.get(AUDIT, headers=headers, params={"action": "test.bulk", "page_size": 5})
    ).json()
    second = (
        await api.get(
            AUDIT, headers=headers, params={"action": "test.bulk", "page_size": 5, "page": 2}
        )
    ).json()

    assert first["total"] == 7
    assert first["pages"] == 2
    assert len(first["items"]) == 5
    assert len(second["items"]) == 2
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert len(set(ids)) == 7


async def test_rejects_invalid_filters(api: AsyncClient, staff: tuple[Headers, User]) -> None:
    headers, _ = staff
    for params in (
        {"user_uuid": "not-a-uuid"},
        {"entity_id": 0},
        {"page_size": 1000},
        {"action": "x" * 65},
    ):
        response = await api.get(AUDIT, headers=headers, params=params)
        assert response.status_code == 422, params


async def test_journal_is_read_only(api: AsyncClient, staff: tuple[Headers, User]) -> None:
    headers, _ = staff
    assert (await api.post(AUDIT, headers=headers, json={})).status_code == 405
    assert (await api.delete(AUDIT, headers=headers)).status_code == 405


async def test_query_count_does_not_grow_with_page(
    api: AsyncClient,
    staff: tuple[Headers, User],
    committed_session: AsyncSession,
    test_engine: AsyncEngine,
) -> None:
    """Автор подтягивается JOIN-ом, а не запросом на каждую запись."""
    headers, _ = staff
    with count_queries(test_engine) as few:
        await api.get(AUDIT, headers=headers)

    committed_session.add_all(
        AuditLog(actor="system", action="test.bulk", entity_type="thing", entity_id=index)
        for index in range(1, 30)
    )
    await committed_session.commit()

    with count_queries(test_engine) as many:
        body = (await api.get(AUDIT, headers=headers)).json()

    assert len(body["items"]) == 24
    assert len(many) == len(few)


# ================================================================== права
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (UserRole.SUPERADMIN, 200),
        (UserRole.ADMIN, 200),
        (UserRole.MANAGER, 403),
        (UserRole.CONTENT_MANAGER, 403),
        (UserRole.VIEWER, 403),
    ],
)
async def test_audit_requires_audit_read(
    api: AsyncClient, login_as, role: UserRole, expected: int
) -> None:
    headers = await login_as(role)
    response = await api.get(AUDIT, headers=headers)
    assert response.status_code == expected
    if expected == 403:
        assert response.json()["error"]["details"] == {"required": ["audit.read"]}


async def test_audit_requires_authentication(api: AsyncClient) -> None:
    assert (await api.get(AUDIT)).status_code == 401


async def test_customer_token_is_rejected(api: AsyncClient, customer_headers) -> None:
    """Токен кабинета клиента в админку не проходит (другая аудитория)."""
    _, headers = await customer_headers()
    assert (await api.get(AUDIT, headers=headers)).status_code == 401
