"""Интеграционные тесты аутентификации и RBAC.

Проверяются через реальные HTTP-запросы к приложению и реальную БД:
именно эта цепочка работает в проде.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.audit.models import AuditLog
from app.modules.audit.service import AuditAction
from app.modules.users.enums import UserRole
from app.modules.users.models import RefreshToken, User
from tests.conftest import DEFAULT_PASSWORD

LOGIN_URL = "/api/v1/admin/auth/login"
REFRESH_URL = "/api/v1/admin/auth/refresh"
LOGOUT_URL = "/api/v1/admin/auth/logout"
ME_URL = "/api/v1/admin/auth/me"
CHANGE_PASSWORD_URL = "/api/v1/admin/auth/change-password"
USERS_URL = "/api/v1/admin/users"

MakeUser = Callable[..., Awaitable[User]]


async def login(api: AsyncClient, email: str, password: str = DEFAULT_PASSWORD):
    return await api.post(LOGIN_URL, json={"email": email, "password": password})


def auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


# ------------------------------------------------------------------- вход
async def test_login_returns_access_token(api: AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    response = await login(api, user.email)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.ACCESS_TOKEN_TTL_MINUTES * 60
    assert body["access_token"]


async def test_refresh_token_goes_only_to_httponly_cookie(
    api: AsyncClient, make_user: MakeUser
) -> None:
    """Refresh не должен попадать в тело ответа: иначе он окажется
    в памяти JS и станет добычей XSS."""
    user = await make_user()
    response = await login(api, user.email)

    assert "refresh_token" not in response.json()
    cookie = response.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert cookie

    raw_header = response.headers["set-cookie"].lower()
    assert "httponly" in raw_header
    assert "samesite=strict" in raw_header
    assert "path=/api/v1/admin/auth" in raw_header


async def test_login_with_wrong_password_fails(api: AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    response = await login(api, user.email, "definitely-wrong-password")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_unknown_email_gives_identical_error(api: AsyncClient, make_user: MakeUser) -> None:
    """Ответ для несуществующего email неотличим от неверного пароля.

    Иначе форма входа превращается в инструмент перебора адресов
    сотрудников.
    """
    user = await make_user()
    wrong_password = await login(api, user.email, "definitely-wrong-password")
    unknown_email = await login(api, "nobody@oinau-pro.kz")

    assert wrong_password.status_code == unknown_email.status_code == 401
    # request_id у ответов разный — сравниваем содержательную часть
    assert wrong_password.json()["error"]["code"] == unknown_email.json()["error"]["code"]
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]


async def test_inactive_user_cannot_login(api: AsyncClient, make_user: MakeUser) -> None:
    user = await make_user(is_active=False)
    response = await login(api, user.email)
    assert response.status_code == 401


async def test_email_is_case_insensitive_on_login(api: AsyncClient, make_user: MakeUser) -> None:
    await make_user(email="Manager@Oinau-Pro.kz")
    response = await login(api, "manager@oinau-pro.kz")
    assert response.status_code == 200


async def test_account_locks_after_failed_attempts(
    api: AsyncClient, make_user: MakeUser, committed_session: AsyncSession
) -> None:
    user = await make_user()

    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        assert (await login(api, user.email, "wrong-password-value")).status_code == 401

    # Даже верный пароль теперь не проходит
    blocked = await login(api, user.email)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "account_locked"

    await committed_session.refresh(user)
    assert user.locked_until is not None


async def test_successful_login_resets_failure_counter(
    api: AsyncClient, make_user: MakeUser, committed_session: AsyncSession
) -> None:
    user = await make_user()
    await login(api, user.email, "wrong-password-value")
    await login(api, user.email, "wrong-password-value")
    await login(api, user.email)

    await committed_session.refresh(user)
    assert user.failed_login_count == 0
    assert user.last_login_at is not None


# ---------------------------------------------------------------- профиль
async def test_me_requires_token(api: AsyncClient) -> None:
    response = await api.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_me_returns_profile_and_permissions(api: AsyncClient, make_user: MakeUser) -> None:
    user = await make_user(role=UserRole.MANAGER)
    token = (await login(api, user.email)).json()["access_token"]

    response = await api.get(ME_URL, headers=auth_header(token))
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == user.email
    assert body["role"] == UserRole.MANAGER.value
    assert "request.read" in body["permissions"]
    assert "catalog.write" not in body["permissions"]
    assert "password_hash" not in body


async def test_garbage_token_is_rejected(api: AsyncClient) -> None:
    response = await api.get(ME_URL, headers=auth_header("not-a-jwt"))
    assert response.status_code == 401


async def test_deactivated_user_loses_access_immediately(
    api: AsyncClient, make_user: MakeUser, committed_session: AsyncSession
) -> None:
    """Токен ещё не истёк, но сотрудника отключили — доступа нет.

    Ради этого пользователь и загружается из БД на каждом запросе.
    """
    user = await make_user()
    token = (await login(api, user.email)).json()["access_token"]
    assert (await api.get(ME_URL, headers=auth_header(token))).status_code == 200

    user.is_active = False
    await committed_session.commit()

    assert (await api.get(ME_URL, headers=auth_header(token))).status_code == 401


async def test_soft_deleted_user_loses_access(
    api: AsyncClient, make_user: MakeUser, committed_session: AsyncSession
) -> None:
    from datetime import UTC, datetime

    user = await make_user()
    token = (await login(api, user.email)).json()["access_token"]

    user.deleted_at = datetime.now(UTC)
    await committed_session.commit()

    assert (await api.get(ME_URL, headers=auth_header(token))).status_code == 401


# --------------------------------------------------------------- ротация
async def test_refresh_issues_new_pair(api: AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    first = await login(api, user.email)
    first_cookie = api.cookies.get(settings.REFRESH_COOKIE_NAME)

    second = await api.post(REFRESH_URL)
    assert second.status_code == 200
    assert second.json()["access_token"]

    second_cookie = api.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert second_cookie != first_cookie  # токен ротирован
    assert second.json()["access_token"] != first.json()["access_token"]


async def test_refresh_without_cookie_fails(api: AsyncClient) -> None:
    response = await api.post(REFRESH_URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"


async def test_reused_refresh_token_revokes_whole_family(
    api: AsyncClient, make_user: MakeUser, committed_session: AsyncSession
) -> None:
    """Ключевая проверка защиты от кражи токена.

    Старый refresh всплыл повторно — значит, его копия у кого-то ещё.
    Отзывается вся цепочка, а не только предъявленный токен.
    """
    user = await make_user()
    await login(api, user.email)
    stolen = api.cookies.get(settings.REFRESH_COOKIE_NAME)

    # Легитимное обновление: старый токен отозван, выдан новый
    assert (await api.post(REFRESH_URL)).status_code == 200
    fresh = api.cookies.get(settings.REFRESH_COOKIE_NAME)

    # Атакующий предъявляет украденную копию старого токена
    api.cookies.set(settings.REFRESH_COOKIE_NAME, stolen, path="/api/v1/admin/auth")
    assert (await api.post(REFRESH_URL)).status_code == 401

    # И новый токен законного пользователя тоже перестал работать
    api.cookies.set(settings.REFRESH_COOKIE_NAME, fresh, path="/api/v1/admin/auth")
    assert (await api.post(REFRESH_URL)).status_code == 401

    tokens = (
        (
            await committed_session.execute(
                select(RefreshToken).where(RefreshToken.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert tokens
    assert all(token.revoked_at is not None for token in tokens)


async def test_logout_revokes_session(api: AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    await login(api, user.email)

    assert (await api.post(LOGOUT_URL)).status_code == 204
    api.cookies.clear()
    assert (await api.post(REFRESH_URL)).status_code == 401


async def test_logout_without_session_is_not_an_error(api: AsyncClient) -> None:
    assert (await api.post(LOGOUT_URL)).status_code == 204


# ----------------------------------------------------------- смена пароля
async def test_change_password_requires_current_one(api: AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    token = (await login(api, user.email)).json()["access_token"]

    response = await api.post(
        CHANGE_PASSWORD_URL,
        headers=auth_header(token),
        json={"current_password": "wrong-password-value", "new_password": "brand-new-passphrase"},
    )
    assert response.status_code == 401


async def test_short_password_is_rejected(api: AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    token = (await login(api, user.email)).json()["access_token"]

    response = await api.post(
        CHANGE_PASSWORD_URL,
        headers=auth_header(token),
        json={"current_password": DEFAULT_PASSWORD, "new_password": "short"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_change_password_invalidates_everything(
    api: AsyncClient, make_user: MakeUser
) -> None:
    """После смены пароля старый access-токен и все сессии мертвы."""
    user = await make_user()
    token = (await login(api, user.email)).json()["access_token"]

    response = await api.post(
        CHANGE_PASSWORD_URL,
        headers=auth_header(token),
        json={"current_password": DEFAULT_PASSWORD, "new_password": "brand-new-passphrase"},
    )
    assert response.status_code == 204

    # Старый access-токен обесценен, хотя формально ещё не истёк
    assert (await api.get(ME_URL, headers=auth_header(token))).status_code == 401
    # Refresh-сессии отозваны
    assert (await api.post(REFRESH_URL)).status_code == 401
    # Старый пароль больше не подходит, новый работает
    assert (await login(api, user.email, DEFAULT_PASSWORD)).status_code == 401
    assert (await login(api, user.email, "brand-new-passphrase")).status_code == 200


# ------------------------------------------------------------------- RBAC
@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (UserRole.SUPERADMIN, 200),
        (UserRole.ADMIN, 200),
        (UserRole.MANAGER, 403),
        (UserRole.CONTENT_MANAGER, 403),
        (UserRole.VIEWER, 403),
    ],
)
async def test_user_management_requires_permission(
    api: AsyncClient, make_user: MakeUser, role: UserRole, expected_status: int
) -> None:
    user = await make_user(role=role)
    token = (await login(api, user.email)).json()["access_token"]

    response = await api.get(USERS_URL, headers=auth_header(token))
    assert response.status_code == expected_status


async def test_permission_denied_names_required_permission(
    api: AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user(role=UserRole.VIEWER)
    token = (await login(api, user.email)).json()["access_token"]

    response = await api.get(USERS_URL, headers=auth_header(token))
    body = response.json()["error"]
    assert body["code"] == "permission_denied"
    assert body["details"]["required"] == ["user.manage"]


async def test_protected_endpoint_rejects_anonymous(api: AsyncClient) -> None:
    assert (await api.get(USERS_URL)).status_code == 401


# ------------------------------------------------------------------ аудит
async def test_login_events_are_audited(
    api: AsyncClient, make_user: MakeUser, committed_session: AsyncSession
) -> None:
    user = await make_user()
    await login(api, user.email, "wrong-password-value")
    await login(api, user.email)

    entries = (
        (await committed_session.execute(select(AuditLog).where(AuditLog.user_id == user.id)))
        .scalars()
        .all()
    )
    actions = {entry.action for entry in entries}

    assert AuditAction.LOGIN_FAILED in actions
    assert AuditAction.LOGIN_SUCCESS in actions
    # IP сохраняется только в виде хеша
    assert all(entry.ip_hash is None or len(entry.ip_hash) == 64 for entry in entries)


async def test_token_reuse_is_audited(
    api: AsyncClient, make_user: MakeUser, committed_session: AsyncSession
) -> None:
    user = await make_user()
    await login(api, user.email)
    stolen = api.cookies.get(settings.REFRESH_COOKIE_NAME)
    await api.post(REFRESH_URL)

    api.cookies.set(settings.REFRESH_COOKIE_NAME, stolen, path="/api/v1/admin/auth")
    await api.post(REFRESH_URL)

    entries = (
        (
            await committed_session.execute(
                select(AuditLog).where(AuditLog.action == AuditAction.TOKEN_REUSE_DETECTED)
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 1
    assert entries[0].changes["revoked_tokens"] >= 1


# ------------------------------------------------- этап 4.1: hardening
async def test_locked_account_does_not_leak_existence(
    api: AsyncClient, make_user: MakeUser
) -> None:
    """403 «заблокировано» показывается только тому, кто знает пароль.

    Иначе форму входа можно использовать как детектор существующих
    учётных записей: пять ошибок — и ответ меняется с 401 на 403.
    """
    user = await make_user()
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        await login(api, user.email, "wrong-password-value")

    with_wrong_password = await login(api, user.email, "still-wrong-password")
    with_correct_password = await login(api, user.email)
    unknown_email = await login(api, "nobody@oinau-pro.kz", "still-wrong-password")

    assert with_wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert with_wrong_password.json()["error"]["code"] == unknown_email.json()["error"]["code"]
    # Владелец учётной записи узнаёт настоящую причину
    assert with_correct_password.status_code == 403


async def test_refresh_cookie_alone_does_not_authenticate(
    api: AsyncClient, make_user: MakeUser
) -> None:
    """Граница аутентификации: прикладные эндпоинты принимают только
    Bearer-токен. Cookie работает исключительно на /auth/refresh."""
    user = await make_user()
    await login(api, user.email)
    assert api.cookies.get(settings.REFRESH_COOKIE_NAME)

    # Заголовка Authorization нет — только cookie
    assert (await api.get(ME_URL)).status_code == 401
    assert (await api.get(USERS_URL)).status_code == 401
    # При этом сама cookie исправна
    assert (await api.post(REFRESH_URL)).status_code == 200


async def test_role_change_takes_effect_immediately(
    api: AsyncClient, make_user: MakeUser, committed_session: AsyncSession
) -> None:
    """Права выводятся из роли в БД, а не из клейма в токене."""
    user = await make_user(role=UserRole.ADMIN)
    token = (await login(api, user.email)).json()["access_token"]
    assert (await api.get(USERS_URL, headers=auth_header(token))).status_code == 200

    user.role = UserRole.MANAGER.value
    await committed_session.commit()

    assert (await api.get(USERS_URL, headers=auth_header(token))).status_code == 403
    me = await api.get(ME_URL, headers=auth_header(token))
    assert me.json()["role"] == UserRole.MANAGER.value


async def test_admin_responses_are_not_cacheable(api: AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    response = await login(api, user.email)
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/users",
        "/api/v1/customer/profile",
        "/api/v1/public/auth/login",
    ],
)
async def test_private_surfaces_are_never_cached(api: AsyncClient, path: str) -> None:
    """Ответ без авторизации тоже не должен попадать в кеш.

    Заголовок ставится независимо от кода ответа: за витриной стоит CDN,
    и закешированный 401 одного посетителя не должен достаться другому.
    Кабинет и вход проверяются наравне с админкой — в их ответах тоже
    токены и персональные данные.
    """
    response = await api.get(path)
    assert response.headers["cache-control"] == "no-store", path


async def test_public_catalog_stays_cacheable(api: AsyncClient) -> None:
    """Обратная сторона правила: каталог кешировать нужно."""
    response = await api.get("/api/v1/public/categories")
    assert response.headers.get("cache-control") != "no-store"


async def test_security_headers_present_on_api(api: AsyncClient) -> None:
    response = await api.get(ME_URL)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


async def test_concurrent_refresh_allows_only_one_winner(test_engine, make_user: MakeUser) -> None:
    """Один refresh-токен нельзя обменять дважды одновременно.

    Без SELECT ... FOR UPDATE оба запроса читают revoked_at IS NULL
    и оба выдают действующую пару — то есть кража токена перестаёт
    обнаруживаться. Проигравший запрос попадает в штатную ветку
    обнаружения переиспользования и отзывает всю цепочку.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.modules.users.exceptions import InvalidRefreshTokenError
    from app.modules.users.service import AuthService, RequestContext

    user = await make_user()
    context = RequestContext(ip_hash=None, user_agent=None, request_id=None)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async with session_factory() as session:
        _, issued = await AuthService(session).authenticate(user.email, DEFAULT_PASSWORD, context)
    raw_token = issued.refresh_token

    async def attempt() -> str:
        async with session_factory() as session:
            try:
                await AuthService(session).refresh(raw_token, context)
            except InvalidRefreshTokenError:
                return "rejected"
            return "accepted"

    results = sorted(await asyncio.gather(attempt(), attempt()))
    assert results == ["accepted", "rejected"]

    # Проигравший запустил отзыв цепочки: живых токенов не осталось
    async with session_factory() as session:
        tokens = (
            (await session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id)))
            .scalars()
            .all()
        )
    assert tokens
    assert all(token.revoked_at is not None for token in tokens)
