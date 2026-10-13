"""Аутентификация клиентов кабинета: регистрация, подтверждение email,
вход и выход, ротация сессий, сброс пароля, ограничение частоты.

Проверяется через HTTP и реальную БД, как и аутентификация админки.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.audit.models import AuditLog
from app.modules.customers.audit import CustomerAuditAction
from app.modules.customers.models import Customer, CustomerActionToken, CustomerRefreshToken
from tests.catalog_fixtures import CatalogFixture
from tests.customer_helpers import (
    CUSTOMER_PASSWORD,
    LOGIN_URL,
    LOGOUT_URL,
    PROFILE_URL,
    REFRESH_COOKIE,
    REFRESH_URL,
    REGISTER_URL,
    RESEND_URL,
    RESET_CONFIRM_URL,
    RESET_URL,
    VERIFY_URL,
    CapturingMailer,
    bearer,
    login_customer,
    registration,
)

NEW_PASSWORD = "brand-new-long-password"


async def load_customer(session: AsyncSession, email: str) -> Customer:
    query = (
        select(Customer).where(Customer.email == email).execution_options(populate_existing=True)
    )
    return (await session.execute(query)).scalar_one()


async def register_and_verify(
    api: AsyncClient, catalog: CatalogFixture, mailer: CapturingMailer, email: str
) -> None:
    response = await api.post(REGISTER_URL, json=registration(catalog.region.id, email=email))
    assert response.status_code == 202, response.text
    token = mailer.last("verification", email).token
    assert (await api.post(VERIFY_URL, json={"token": token})).status_code == 204


async def post_with_refresh(api: AsyncClient, url: str, token: str):
    """Запрос с конкретным refresh-токеном вместо того, что лежит в cookie клиента."""
    api.cookies.clear()
    api.cookies.set(REFRESH_COOKIE, token)
    try:
        return await api.post(url)
    finally:
        api.cookies.clear()


def refresh_cookie(response) -> str:
    value = response.cookies.get(REFRESH_COOKIE)
    assert value, "refresh-cookie не выставлена"
    return value


# ---------------------------------------------------------------- регистрация
async def test_registration_creates_unverified_customer_and_sends_link(
    api: AsyncClient,
    catalog: CatalogFixture,
    account_mailer: CapturingMailer,
    committed_session: AsyncSession,
) -> None:
    response = await api.post(REGISTER_URL, json=registration(catalog.region.id))

    assert response.status_code == 202
    assert "Проверьте почту" in response.json()["detail"]

    customer = await load_customer(committed_session, "buyer@example.kz")
    assert customer.email_verified_at is None
    assert customer.phone == "+77015554433"  # нормализован
    assert customer.region_id == catalog.region.id
    # Пароль не хранится в открытом виде
    assert CUSTOMER_PASSWORD not in customer.password_hash
    assert customer.password_hash.startswith("$argon2id$")

    mail = account_mailer.last("verification", "buyer@example.kz")
    stored = (
        await committed_session.execute(
            select(CustomerActionToken).where(CustomerActionToken.customer_id == customer.id)
        )
    ).scalar_one()
    # В БД хеш, а не сам токен из письма
    assert stored.token_hash != mail.token
    assert mail.token not in stored.token_hash


async def test_registration_does_not_reveal_existing_email(
    api: AsyncClient,
    catalog: CatalogFixture,
    account_mailer: CapturingMailer,
    make_customer,
    committed_session: AsyncSession,
) -> None:
    verified = await make_customer(email="taken@example.kz")

    new = await api.post(
        REGISTER_URL, json=registration(catalog.region.id, email="fresh@example.kz")
    )
    taken = await api.post(
        REGISTER_URL, json=registration(catalog.region.id, email="TAKEN@example.kz")
    )

    assert new.status_code == taken.status_code == 202
    assert new.json() == taken.json()
    # Второй аккаунт не создан, письмо подтверждённому клиенту не ушло
    total = (
        await committed_session.execute(
            select(func.count(Customer.id)).where(Customer.email == verified.email)
        )
    ).scalar_one()
    assert total == 1
    assert account_mailer.count("verification", "taken@example.kz") == 0


async def test_repeated_registration_of_unverified_account_resends_link(
    api: AsyncClient, catalog: CatalogFixture, account_mailer: CapturingMailer
) -> None:
    await api.post(REGISTER_URL, json=registration(catalog.region.id))
    first = account_mailer.last("verification").token
    await api.post(REGISTER_URL, json=registration(catalog.region.id))
    second = account_mailer.last("verification").token

    assert first != second
    # Действует только ссылка из последнего письма
    assert (await api.post(VERIFY_URL, json={"token": first})).status_code == 422
    assert (await api.post(VERIFY_URL, json={"token": second})).status_code == 204


@pytest.mark.parametrize(
    "overrides",
    [
        {"password": "short"},
        {"email": "not-an-email"},
        {"phone": "abc"},
        {"contact_name": ""},
        {"email_verified_at": "2026-01-01T00:00:00Z"},
        {"is_active": True},
    ],
)
async def test_registration_validation(
    api: AsyncClient, catalog: CatalogFixture, overrides: dict
) -> None:
    response = await api.post(REGISTER_URL, json=registration(catalog.region.id, **overrides))
    assert response.status_code == 422


async def test_registration_rejects_unknown_region(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    response = await api.post(REGISTER_URL, json=registration(999_999))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "region_not_found"


async def test_registration_works_without_region(
    api: AsyncClient,
    catalog: CatalogFixture,
    account_mailer: CapturingMailer,
    committed_session: AsyncSession,
) -> None:
    """На форме регистрации региона нет — без него аккаунт всё равно создаётся."""
    body = registration(catalog.region.id)
    del body["region_id"]

    response = await api.post(REGISTER_URL, json=body)

    assert response.status_code == 202
    customer = await load_customer(committed_session, "buyer@example.kz")
    assert customer.region_id is None
    assert account_mailer.last("verification", "buyer@example.kz") is not None


# ------------------------------------------------------------- подтверждение
async def test_login_before_verification_is_refused(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    await api.post(REGISTER_URL, json=registration(catalog.region.id))

    correct = await api.post(
        LOGIN_URL, json={"email": "buyer@example.kz", "password": CUSTOMER_PASSWORD}
    )
    wrong = await api.post(
        LOGIN_URL, json={"email": "buyer@example.kz", "password": "wrong-password-123"}
    )

    assert correct.status_code == 403
    assert correct.json()["error"]["code"] == "email_not_verified"
    # С неверным паролем — тот же ответ, что для несуществующего адреса
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_credentials"
    assert REFRESH_COOKIE not in correct.cookies


async def test_email_verification_activates_account(
    api: AsyncClient,
    catalog: CatalogFixture,
    account_mailer: CapturingMailer,
    committed_session: AsyncSession,
) -> None:
    await register_and_verify(api, catalog, account_mailer, "buyer@example.kz")

    customer = await load_customer(committed_session, "buyer@example.kz")
    assert customer.email_verified_at is not None
    body = await login_customer(api, "buyer@example.kz")
    profile = await api.get(PROFILE_URL, headers=bearer(body["access_token"]))
    assert profile.status_code == 200
    assert profile.json()["email"] == "buyer@example.kz"

    audit = (
        (
            await committed_session.execute(
                select(AuditLog.action).where(
                    AuditLog.entity_type == "customer", AuditLog.entity_id == customer.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert CustomerAuditAction.REGISTERED in audit
    assert CustomerAuditAction.EMAIL_VERIFIED in audit


async def test_verification_token_is_single_use(
    api: AsyncClient, catalog: CatalogFixture, account_mailer: CapturingMailer
) -> None:
    await register_and_verify(api, catalog, account_mailer, "buyer@example.kz")
    token = account_mailer.last("verification").token

    again = await api.post(VERIFY_URL, json={"token": token})
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "invalid_token"


async def test_expired_verification_token_is_rejected(
    api: AsyncClient,
    catalog: CatalogFixture,
    account_mailer: CapturingMailer,
    committed_session: AsyncSession,
) -> None:
    await api.post(REGISTER_URL, json=registration(catalog.region.id))
    token = account_mailer.last("verification").token
    stored = (await committed_session.execute(select(CustomerActionToken))).scalar_one()
    stored.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await committed_session.commit()

    response = await api.post(VERIFY_URL, json={"token": token})
    assert response.status_code == 422


async def test_unknown_and_malformed_tokens(api: AsyncClient) -> None:
    unknown = await api.post(VERIFY_URL, json={"token": "a" * 43})
    malformed = await api.post(VERIFY_URL, json={"token": "<script>"})
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "invalid_token"
    assert malformed.status_code == 422


async def test_resend_verification_answers_the_same_for_any_address(
    api: AsyncClient,
    catalog: CatalogFixture,
    account_mailer: CapturingMailer,
    make_customer,
) -> None:
    await api.post(REGISTER_URL, json=registration(catalog.region.id))
    verified = await make_customer()
    before = account_mailer.count("verification")

    responses = [
        await api.post(RESEND_URL, json={"email": email})
        for email in ("buyer@example.kz", verified.email, "nobody@example.kz")
    ]

    assert {response.status_code for response in responses} == {202}
    assert len({response.text for response in responses}) == 1
    # Письмо ушло только неподтверждённому аккаунту
    assert account_mailer.count("verification") == before + 1


# ------------------------------------------------------------- вход и выход
async def test_login_sets_httponly_refresh_cookie_only(api: AsyncClient, make_customer) -> None:
    customer = await make_customer()
    response = await api.post(
        LOGIN_URL, json={"email": customer.email, "password": CUSTOMER_PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.ACCESS_TOKEN_TTL_MINUTES * 60
    assert "refresh_token" not in body

    header = response.headers["set-cookie"]
    assert REFRESH_COOKIE in header
    assert "HttpOnly" in header
    assert "Path=/api/v1/public/auth" in header
    # Cookie админки не трогается
    assert settings.REFRESH_COOKIE_NAME + "=" not in header


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("unknown@example.kz", CUSTOMER_PASSWORD),
        (None, "wrong-password-123"),
    ],
)
async def test_invalid_credentials_are_indistinguishable(
    api: AsyncClient, make_customer, email: str | None, password: str
) -> None:
    customer = await make_customer()
    response = await api.post(
        LOGIN_URL, json={"email": email or customer.email, "password": password}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_inactive_customer_cannot_log_in(api: AsyncClient, make_customer) -> None:
    customer = await make_customer(is_active=False)
    response = await api.post(
        LOGIN_URL, json={"email": customer.email, "password": CUSTOMER_PASSWORD}
    )
    assert response.status_code == 401


async def test_account_locks_after_failed_attempts(api: AsyncClient, make_customer) -> None:
    customer = await make_customer()
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        await api.post(LOGIN_URL, json={"email": customer.email, "password": "wrong-password-1"})

    locked = await api.post(
        LOGIN_URL, json={"email": customer.email, "password": CUSTOMER_PASSWORD}
    )
    assert locked.status_code == 403
    assert locked.json()["error"]["code"] == "account_locked"


async def test_logout_revokes_session(api: AsyncClient, make_customer) -> None:
    customer = await make_customer()
    login = await api.post(LOGIN_URL, json={"email": customer.email, "password": CUSTOMER_PASSWORD})
    cookie = refresh_cookie(login)

    logout = await post_with_refresh(api, LOGOUT_URL, cookie)
    assert logout.status_code == 204
    assert (
        "Max-Age=0" in logout.headers["set-cookie"]
        or "expires" in logout.headers["set-cookie"].lower()
    )

    api.cookies.clear()
    refreshed = await post_with_refresh(api, REFRESH_URL, cookie)
    assert refreshed.status_code == 401


async def test_logout_without_session_is_not_an_error(api: AsyncClient) -> None:
    assert (await api.post(LOGOUT_URL)).status_code == 204


# ---------------------------------------------------------- ротация сессий
async def test_refresh_rotates_token(
    api: AsyncClient, make_customer, committed_session: AsyncSession
) -> None:
    customer = await make_customer()
    login = await api.post(LOGIN_URL, json={"email": customer.email, "password": CUSTOMER_PASSWORD})
    first = refresh_cookie(login)
    api.cookies.clear()

    refreshed = await post_with_refresh(api, REFRESH_URL, first)
    assert refreshed.status_code == 200
    second = refresh_cookie(refreshed)
    assert second != first
    assert refreshed.json()["access_token"]

    tokens = (
        (
            await committed_session.execute(
                select(CustomerRefreshToken)
                .where(CustomerRefreshToken.customer_id == customer.id)
                .order_by(CustomerRefreshToken.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(tokens) == 2
    assert tokens[0].revoked_at is not None
    assert tokens[1].revoked_at is None
    assert tokens[0].family_id == tokens[1].family_id


async def test_refresh_token_reuse_revokes_whole_family(
    api: AsyncClient, make_customer, committed_session: AsyncSession
) -> None:
    customer = await make_customer()
    login = await api.post(LOGIN_URL, json={"email": customer.email, "password": CUSTOMER_PASSWORD})
    stolen = refresh_cookie(login)
    api.cookies.clear()
    rotated = refresh_cookie(await post_with_refresh(api, REFRESH_URL, stolen))
    api.cookies.clear()

    # Злоумышленник предъявляет уже использованный токен
    reuse = await post_with_refresh(api, REFRESH_URL, stolen)
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "invalid_refresh_token"

    api.cookies.clear()
    # Легитимная ветка цепочки тоже отозвана
    after = await post_with_refresh(api, REFRESH_URL, rotated)
    assert after.status_code == 401

    alerts = (
        await committed_session.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.action == CustomerAuditAction.TOKEN_REUSE_DETECTED,
                AuditLog.entity_id == customer.id,
            )
        )
    ).scalar_one()
    # Каждое предъявление отозванного токена цепочки — отдельный сигнал
    assert alerts >= 1


async def test_refresh_without_cookie_and_with_admin_cookie(api: AsyncClient, make_user) -> None:
    assert (await api.post(REFRESH_URL)).status_code == 401

    user = await make_user()
    admin_login = await api.post(
        "/api/v1/admin/auth/login",
        json={"email": user.email, "password": "correct-horse-battery-staple"},
    )
    admin_refresh = admin_login.cookies.get(settings.REFRESH_COOKIE_NAME)
    api.cookies.clear()
    # Refresh-токен сотрудника не открывает сессию клиента
    response = await post_with_refresh(api, REFRESH_URL, admin_refresh)
    assert response.status_code == 401


async def test_expired_refresh_token_is_rejected(
    api: AsyncClient, make_customer, committed_session: AsyncSession
) -> None:
    customer = await make_customer()
    cookie = refresh_cookie(
        await api.post(LOGIN_URL, json={"email": customer.email, "password": CUSTOMER_PASSWORD})
    )
    token = (await committed_session.execute(select(CustomerRefreshToken))).scalar_one()
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await committed_session.commit()
    api.cookies.clear()

    assert (await post_with_refresh(api, REFRESH_URL, cookie)).status_code == 401


# ------------------------------------------------------------ сброс пароля
async def test_password_reset_does_not_reveal_accounts(
    api: AsyncClient, make_customer, account_mailer: CapturingMailer
) -> None:
    customer = await make_customer()

    known = await api.post(RESET_URL, json={"email": customer.email})
    unknown = await api.post(RESET_URL, json={"email": "nobody@example.kz"})

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert account_mailer.count("reset", customer.email) == 1
    assert account_mailer.count("reset", "nobody@example.kz") == 0


async def test_password_reset_changes_password_and_revokes_sessions(
    api: AsyncClient,
    make_customer,
    account_mailer: CapturingMailer,
    committed_session: AsyncSession,
) -> None:
    customer = await make_customer()
    login = await api.post(LOGIN_URL, json={"email": customer.email, "password": CUSTOMER_PASSWORD})
    old_access = login.json()["access_token"]
    old_refresh = refresh_cookie(login)
    api.cookies.clear()

    await api.post(RESET_URL, json={"email": customer.email})
    token = account_mailer.last("reset", customer.email).token
    confirm = await api.post(RESET_CONFIRM_URL, json={"token": token, "new_password": NEW_PASSWORD})
    assert confirm.status_code == 204

    # Старые сессии больше не работают
    assert (await post_with_refresh(api, REFRESH_URL, old_refresh)).status_code == 401
    assert (await api.get(PROFILE_URL, headers=bearer(old_access))).status_code == 401
    active = (
        await committed_session.execute(
            select(func.count(CustomerRefreshToken.id)).where(
                CustomerRefreshToken.customer_id == customer.id,
                CustomerRefreshToken.revoked_at.is_(None),
            )
        )
    ).scalar_one()
    assert active == 0

    api.cookies.clear()
    # Старый пароль не подходит, новый — подходит, и новый токен работает
    old = await api.post(LOGIN_URL, json={"email": customer.email, "password": CUSTOMER_PASSWORD})
    assert old.status_code == 401
    fresh = await login_customer(api, customer.email, NEW_PASSWORD)
    assert (await api.get(PROFILE_URL, headers=bearer(fresh["access_token"]))).status_code == 200


async def test_password_reset_token_is_single_use_and_expires(
    api: AsyncClient,
    make_customer,
    account_mailer: CapturingMailer,
    committed_session: AsyncSession,
) -> None:
    customer = await make_customer()
    await api.post(RESET_URL, json={"email": customer.email})
    token = account_mailer.last("reset").token

    assert (
        await api.post(RESET_CONFIRM_URL, json={"token": token, "new_password": NEW_PASSWORD})
    ).status_code == 204
    reused = await api.post(
        RESET_CONFIRM_URL, json={"token": token, "new_password": "another-long-password"}
    )
    assert reused.status_code == 422

    await api.post(RESET_URL, json={"email": customer.email})
    expiring = account_mailer.last("reset").token
    rows = (
        (
            await committed_session.execute(
                select(CustomerActionToken).where(CustomerActionToken.used_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await committed_session.commit()
    expired = await api.post(
        RESET_CONFIRM_URL, json={"token": expiring, "new_password": "another-long-password"}
    )
    assert expired.status_code == 422


async def test_verification_token_cannot_reset_password(
    api: AsyncClient, catalog: CatalogFixture, account_mailer: CapturingMailer
) -> None:
    await api.post(REGISTER_URL, json=registration(catalog.region.id))
    verification = account_mailer.last("verification").token

    response = await api.post(
        RESET_CONFIRM_URL, json={"token": verification, "new_password": NEW_PASSWORD}
    )
    assert response.status_code == 422


async def test_password_reset_confirms_unverified_email(
    api: AsyncClient,
    catalog: CatalogFixture,
    account_mailer: CapturingMailer,
    committed_session: AsyncSession,
) -> None:
    """Переход по ссылке из письма доказывает владение адресом."""
    await api.post(REGISTER_URL, json=registration(catalog.region.id))
    await api.post(RESET_URL, json={"email": "buyer@example.kz"})
    token = account_mailer.last("reset").token

    await api.post(RESET_CONFIRM_URL, json={"token": token, "new_password": NEW_PASSWORD})

    customer = await load_customer(committed_session, "buyer@example.kz")
    assert customer.email_verified_at is not None
    await login_customer(api, "buyer@example.kz", NEW_PASSWORD)


async def test_weak_new_password_is_rejected(api: AsyncClient) -> None:
    response = await api.post(RESET_CONFIRM_URL, json={"token": "a" * 43, "new_password": "short"})
    assert response.status_code == 422


# ------------------------------------------------------ ограничение частоты
def _client_ip() -> str:
    return f"203.0.113.{uuid.uuid4().int % 250}"


async def test_customer_login_is_rate_limited(
    api: AsyncClient, make_customer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_CUSTOMER_LOGIN", "3/minute")
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
    customer = await make_customer()
    ip = _client_ip()

    statuses = [
        (
            await api.post(
                LOGIN_URL,
                json={"email": customer.email, "password": "wrong-password-1"},
                headers={"X-Forwarded-For": ip},
            )
        ).status_code
        for _ in range(5)
    ]
    assert statuses[:3] == [401, 401, 401]
    assert statuses[3:] == [429, 429]


async def test_registration_is_rate_limited_per_ip(
    api: AsyncClient, catalog: CatalogFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_CUSTOMER_REGISTER", "2/hour")
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
    ip = _client_ip()

    statuses = [
        (
            await api.post(
                REGISTER_URL,
                json=registration(
                    catalog.region.id, email=f"r{index}-{uuid.uuid4().hex[:6]}@ex.kz"
                ),
                headers={"X-Forwarded-For": ip},
            )
        ).status_code
        for index in range(3)
    ]
    assert statuses == [202, 202, 429]


async def test_password_reset_is_rate_limited_per_address(
    api: AsyncClient,
    make_customer,
    account_mailer: CapturingMailer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Смена IP не помогает засыпать письмами один ящик."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_CUSTOMER_EMAIL_PER_ADDRESS", "2/hour")
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
    customer = await make_customer()

    statuses = [
        (
            await api.post(
                RESET_URL,
                json={"email": customer.email},
                headers={"X-Forwarded-For": _client_ip()},
            )
        ).status_code
        for _ in range(3)
    ]
    assert statuses == [202, 202, 429]
    assert account_mailer.count("reset", customer.email) == 2
