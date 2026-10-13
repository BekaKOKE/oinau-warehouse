"""Admin API сотрудников: список, заведение, изменение, права и аудит.

Проверяется в первую очередь безопасность: пароль наружу не уходит,
отключение действует немедленно, администратор не поднимает себе права
и не запирает сам себя.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.users.enums import UserRole
from app.modules.users.models import RefreshToken, User
from app.modules.users.permissions import ROLE_PERMISSIONS
from app.modules.users.service_admin import UserAdminAction
from tests.conftest import DEFAULT_PASSWORD, Headers

USERS_URL = "/api/v1/admin/users"
ROLES_URL = "/api/v1/admin/users/roles"
LOGIN_URL = "/api/v1/admin/auth/login"
ME_URL = "/api/v1/admin/auth/me"

NEW_PASSWORD = "another-strong-passphrase"

MakeUser = Callable[..., Awaitable[User]]


def auth_header(token: str) -> Headers:
    return {"Authorization": f"Bearer {token}"}


async def token_for(api: AsyncClient, user: User, password: str = DEFAULT_PASSWORD) -> str:
    response = await api.post(LOGIN_URL, json={"email": user.email, "password": password})
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def headers_for(api: AsyncClient, user: User) -> Headers:
    return auth_header(await token_for(api, user))


def payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "email": "new.manager@oinau-pro.kz",
        "full_name": "Айгерим Серикова",
        "password": NEW_PASSWORD,
        "role": UserRole.MANAGER.value,
    }
    body.update(overrides)
    return body


# ------------------------------------------------------------------ доступ
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
async def test_list_requires_user_manage(
    api: AsyncClient, make_user: MakeUser, role: UserRole, expected: int
) -> None:
    user = await make_user(role=role)
    response = await api.get(USERS_URL, headers=await headers_for(api, user))
    assert response.status_code == expected


@pytest.mark.parametrize(
    ("role", "expected"),
    [(UserRole.ADMIN, 201), (UserRole.MANAGER, 403), (UserRole.CONTENT_MANAGER, 403)],
)
async def test_create_requires_user_manage(
    api: AsyncClient, make_user: MakeUser, role: UserRole, expected: int
) -> None:
    actor = await make_user(role=role)
    response = await api.post(USERS_URL, json=payload(), headers=await headers_for(api, actor))
    assert response.status_code == expected


async def test_anonymous_cannot_read_or_write(api: AsyncClient) -> None:
    assert (await api.get(USERS_URL)).status_code == 401
    assert (await api.post(USERS_URL, json=payload())).status_code == 401
    assert (await api.get(ROLES_URL)).status_code == 401


# ------------------------------------------------------------------ список
async def test_list_returns_page_without_password(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    await make_user(role=UserRole.MANAGER, full_name="Бекзат Оспанов")

    response = await api.get(USERS_URL, headers=admin)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2
    assert body["page"] == 1
    item = body["items"][0]
    assert set(item) == {
        "uuid",
        "email",
        "full_name",
        "phone",
        "role",
        "is_active",
        "last_login_at",
        "created_at",
        "updated_at",
    }
    assert "password" not in response.text
    assert "password_hash" not in response.text


async def test_list_filters_by_search_role_and_status(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    await make_user(role=UserRole.MANAGER, full_name="Жанна Ахметова", email="zhanna@oinau-pro.kz")
    await make_user(role=UserRole.VIEWER, full_name="Пётр Кузнецов", is_active=False)

    by_name = await api.get(USERS_URL, params={"search": "Ахметова"}, headers=admin)
    assert [item["full_name"] for item in by_name.json()["items"]] == ["Жанна Ахметова"]

    by_email = await api.get(USERS_URL, params={"search": "zhanna@"}, headers=admin)
    assert by_email.json()["total"] == 1

    by_role = await api.get(USERS_URL, params={"role": "VIEWER"}, headers=admin)
    assert {item["role"] for item in by_role.json()["items"]} == {"VIEWER"}

    disabled = await api.get(USERS_URL, params={"is_active": "false"}, headers=admin)
    assert [item["is_active"] for item in disabled.json()["items"]] == [False]


async def test_list_puts_disabled_users_last(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    await make_user(role=UserRole.VIEWER, full_name="Аида Нурлан", is_active=False)
    await make_user(role=UserRole.VIEWER, full_name="Ярослав Ким", is_active=True)

    items = (await api.get(USERS_URL, headers=admin)).json()["items"]

    assert items[-1]["full_name"] == "Аида Нурлан"


async def test_list_paginates(api: AsyncClient, make_user: MakeUser, admin: Headers) -> None:
    for index in range(3):
        await make_user(role=UserRole.VIEWER, full_name=f"Сотрудник {index}")

    response = await api.get(USERS_URL, params={"page": 2, "page_size": 2}, headers=admin)

    body = response.json()
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert len(body["items"]) == 2


async def test_roles_endpoint_matches_backend_matrix(api: AsyncClient, admin: Headers) -> None:
    response = await api.get(ROLES_URL, headers=admin)

    assert response.status_code == 200
    got = {item["role"]: item["permissions"] for item in response.json()}
    assert got == {
        role.value: sorted(permissions) for role, permissions in ROLE_PERMISSIONS.items()
    }


# --------------------------------------------------------------- создание
async def test_create_returns_user_and_allows_login(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    response = await api.post(USERS_URL, json=payload(phone="+7 701 000 11 22"), headers=admin)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.manager@oinau-pro.kz"
    assert body["role"] == "MANAGER"
    assert body["is_active"] is True
    assert "password" not in body

    created = (
        await committed_session.execute(select(User).where(User.email == body["email"]))
    ).scalar_one()
    assert created.password_hash.startswith("$argon2id$")
    assert NEW_PASSWORD not in created.password_hash

    login = await api.post(LOGIN_URL, json={"email": body["email"], "password": NEW_PASSWORD})
    assert login.status_code == 200


async def test_create_rejects_duplicate_email(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    existing = await make_user(role=UserRole.VIEWER)

    response = await api.post(USERS_URL, json=payload(email=existing.email), headers=admin)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_exists"


async def test_create_rejects_duplicate_email_ignoring_case(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    existing = await make_user(role=UserRole.VIEWER, email="Case.Test@oinau-pro.kz")

    response = await api.post(USERS_URL, json=payload(email=existing.email.upper()), headers=admin)

    assert response.status_code == 409


@pytest.mark.parametrize(
    "bad",
    [
        {"password": "short"},
        {"email": "not-an-email"},
        {"full_name": ""},
        {"full_name": "<b>Иван</b>"},
        {"role": "OWNER"},
    ],
)
async def test_create_validates_payload(
    api: AsyncClient, admin: Headers, bad: dict[str, object]
) -> None:
    response = await api.post(USERS_URL, json=payload(**bad), headers=admin)
    assert response.status_code == 422


async def test_admin_cannot_create_superadmin(api: AsyncClient, admin: Headers) -> None:
    response = await api.post(USERS_URL, json=payload(role="SUPERADMIN"), headers=admin)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "superadmin_required"


async def test_superadmin_can_create_superadmin(api: AsyncClient, make_user: MakeUser) -> None:
    actor = await make_user(role=UserRole.SUPERADMIN)

    response = await api.post(
        USERS_URL, json=payload(role="SUPERADMIN"), headers=await headers_for(api, actor)
    )

    assert response.status_code == 201
    assert response.json()["role"] == "SUPERADMIN"


# ------------------------------------------------------------- изменение
async def test_get_user_and_unknown_uuid(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    user = await make_user(role=UserRole.VIEWER)

    found = await api.get(f"{USERS_URL}/{user.uuid}", headers=admin)
    assert found.status_code == 200
    assert found.json()["uuid"] == str(user.uuid)

    missing = await api.get(f"{USERS_URL}/0b0f5c7e-6d7b-4d4e-9d3f-3d7c1c7a9a11", headers=admin)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "user_not_found"


async def test_update_profile_and_role(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    user = await make_user(role=UserRole.VIEWER, full_name="Старое Имя")

    response = await api.patch(
        f"{USERS_URL}/{user.uuid}",
        json={"full_name": "Новое Имя", "phone": "+7 707 111 22 33", "role": "MANAGER"},
        headers=admin,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Новое Имя"
    assert body["phone"] == "+7 707 111 22 33"
    assert body["role"] == "MANAGER"


async def test_role_change_applies_to_next_request(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    """Права читаются из БД на каждый запрос, а не из клейма в токене."""
    user = await make_user(role=UserRole.VIEWER)
    token = await token_for(api, user)
    assert (await api.get(USERS_URL, headers=auth_header(token))).status_code == 403

    await api.patch(f"{USERS_URL}/{user.uuid}", json={"role": "ADMIN"}, headers=admin)

    assert (await api.get(USERS_URL, headers=auth_header(token))).status_code == 200


async def test_email_cannot_be_changed(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    user = await make_user(role=UserRole.VIEWER)

    response = await api.patch(
        f"{USERS_URL}/{user.uuid}", json={"email": "other@oinau-pro.kz"}, headers=admin
    )

    assert response.status_code == 422


async def test_deactivation_blocks_access_immediately(
    api: AsyncClient, make_user: MakeUser, admin: Headers, committed_session: AsyncSession
) -> None:
    user = await make_user(role=UserRole.MANAGER)
    token = await token_for(api, user)
    assert (await api.get(ME_URL, headers=auth_header(token))).status_code == 200

    response = await api.patch(f"{USERS_URL}/{user.uuid}", json={"is_active": False}, headers=admin)
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    # Выданный access-токен больше не принимается
    assert (await api.get(ME_URL, headers=auth_header(token))).status_code == 401
    # Повторный вход невозможен
    assert (
        await api.post(LOGIN_URL, json={"email": user.email, "password": DEFAULT_PASSWORD})
    ).status_code == 401
    # Refresh-токены отозваны: обновить сессию тоже нельзя
    stored = (
        (
            await committed_session.execute(
                select(RefreshToken).where(RefreshToken.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert stored and all(item.revoked_at is not None for item in stored)


async def test_reactivation_restores_login(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    user = await make_user(role=UserRole.MANAGER, is_active=False)

    await api.patch(f"{USERS_URL}/{user.uuid}", json={"is_active": True}, headers=admin)

    assert (
        await api.post(LOGIN_URL, json={"email": user.email, "password": DEFAULT_PASSWORD})
    ).status_code == 200


async def test_cannot_disable_self(api: AsyncClient, make_user: MakeUser) -> None:
    actor = await make_user(role=UserRole.ADMIN)

    response = await api.patch(
        f"{USERS_URL}/{actor.uuid}",
        json={"is_active": False},
        headers=await headers_for(api, actor),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "self_deactivation"


async def test_cannot_change_own_role(api: AsyncClient, make_user: MakeUser) -> None:
    actor = await make_user(role=UserRole.ADMIN)

    response = await api.patch(
        f"{USERS_URL}/{actor.uuid}", json={"role": "VIEWER"}, headers=await headers_for(api, actor)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "self_role_change"


async def test_own_profile_fields_are_editable(api: AsyncClient, make_user: MakeUser) -> None:
    actor = await make_user(role=UserRole.ADMIN)

    response = await api.patch(
        f"{USERS_URL}/{actor.uuid}",
        json={"full_name": "Данияр Ахметов", "is_active": True},
        headers=await headers_for(api, actor),
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Данияр Ахметов"


async def test_admin_cannot_touch_superadmin(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    target = await make_user(role=UserRole.SUPERADMIN)

    response = await api.patch(
        f"{USERS_URL}/{target.uuid}", json={"is_active": False}, headers=admin
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "superadmin_required"


async def test_admin_cannot_promote_to_superadmin(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    target = await make_user(role=UserRole.VIEWER)

    response = await api.patch(
        f"{USERS_URL}/{target.uuid}", json={"role": "SUPERADMIN"}, headers=admin
    )

    assert response.status_code == 403


# ------------------------------------------------------------ сброс пароля
async def test_password_reset_revokes_sessions_and_sets_new_password(
    api: AsyncClient, make_user: MakeUser, admin: Headers, committed_session: AsyncSession
) -> None:
    user = await make_user(role=UserRole.MANAGER)
    token = await token_for(api, user)

    response = await api.patch(
        f"{USERS_URL}/{user.uuid}", json={"password": NEW_PASSWORD}, headers=admin
    )

    assert response.status_code == 200
    assert "password" not in response.json()
    # Старый access-токен обесценен отметкой password_changed_at
    assert (await api.get(ME_URL, headers=auth_header(token))).status_code == 401
    # Старый пароль не работает, новый работает
    assert (
        await api.post(LOGIN_URL, json={"email": user.email, "password": DEFAULT_PASSWORD})
    ).status_code == 401
    assert (
        await api.post(LOGIN_URL, json={"email": user.email, "password": NEW_PASSWORD})
    ).status_code == 200

    refreshed = (
        await committed_session.execute(select(User).where(User.id == user.id))
    ).scalar_one()
    assert NEW_PASSWORD not in refreshed.password_hash


async def test_password_reset_requires_strong_password(
    api: AsyncClient, make_user: MakeUser, admin: Headers
) -> None:
    user = await make_user(role=UserRole.MANAGER)

    response = await api.patch(f"{USERS_URL}/{user.uuid}", json={"password": "123"}, headers=admin)

    assert response.status_code == 422


# ------------------------------------------------------------------ аудит
async def _actions_for(session: AsyncSession, user_id: int) -> set[str]:
    entries = (
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "user", AuditLog.entity_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    return {entry.action for entry in entries}


async def test_mutations_are_audited(
    api: AsyncClient, make_user: MakeUser, admin: Headers, committed_session: AsyncSession
) -> None:
    created = (await api.post(USERS_URL, json=payload(), headers=admin)).json()
    user = (
        await committed_session.execute(select(User).where(User.uuid == created["uuid"]))
    ).scalar_one()

    await api.patch(
        f"{USERS_URL}/{user.uuid}",
        json={"role": "VIEWER", "is_active": False, "password": NEW_PASSWORD},
        headers=admin,
    )

    actions = await _actions_for(committed_session, user.id)
    assert UserAdminAction.CREATED in actions
    assert UserAdminAction.UPDATED in actions
    assert UserAdminAction.PASSWORD_RESET in actions

    entries = (
        (
            await committed_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_id == user.id, AuditLog.action == UserAdminAction.UPDATED
                )
            )
        )
        .scalars()
        .all()
    )
    changes = entries[0].changes
    assert changes["role"] == {"old": "MANAGER", "new": "VIEWER"}
    assert changes["is_active"] == {"old": True, "new": False}
    # Ни пароля, ни хеша в журнале нет
    assert NEW_PASSWORD not in str(changes)
    assert "password" not in changes


async def test_unchanged_patch_writes_nothing_to_audit(
    api: AsyncClient, make_user: MakeUser, admin: Headers, committed_session: AsyncSession
) -> None:
    user = await make_user(role=UserRole.VIEWER, full_name="Без Изменений")

    response = await api.patch(
        f"{USERS_URL}/{user.uuid}",
        json={"full_name": "Без Изменений", "role": "VIEWER"},
        headers=admin,
    )

    assert response.status_code == 200
    assert await _actions_for(committed_session, user.id) == set()
