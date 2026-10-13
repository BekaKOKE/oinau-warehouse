"""Общие помощники тестов кабинета клиента."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from httpx import AsyncClient

AUTH = "/api/v1/public/auth"
REGISTER_URL = f"{AUTH}/register"
VERIFY_URL = f"{AUTH}/verify-email"
RESEND_URL = f"{AUTH}/verify-email/resend"
LOGIN_URL = f"{AUTH}/login"
REFRESH_URL = f"{AUTH}/refresh"
LOGOUT_URL = f"{AUTH}/logout"
RESET_URL = f"{AUTH}/password-reset"
RESET_CONFIRM_URL = f"{AUTH}/password-reset/confirm"

CUSTOMER = "/api/v1/customer"
PROFILE_URL = f"{CUSTOMER}/profile"
FAVORITES_URL = f"{CUSTOMER}/favorites"
REQUESTS_URL = f"{CUSTOMER}/requests"
PROJECTS_URL = f"{CUSTOMER}/projects"
NOTIFICATIONS_URL = f"{CUSTOMER}/notifications"

CUSTOMER_PASSWORD = "customer-strong-password"
REFRESH_COOKIE = "oinau_customer_refresh"


@dataclass
class SentMail:
    kind: str
    email: str
    token: str


@dataclass
class CapturingMailer:
    """Отправитель, который запоминает письма вместо отправки."""

    sent: list[SentMail] = field(default_factory=list)

    async def send_email_verification(self, *, email: str, token: str) -> None:
        self.sent.append(SentMail("verification", email, token))

    async def send_password_reset(self, *, email: str, token: str) -> None:
        self.sent.append(SentMail("reset", email, token))

    def last(self, kind: str, email: str | None = None) -> SentMail:
        matches = [
            mail
            for mail in self.sent
            if mail.kind == kind and (email is None or mail.email.lower() == email.lower())
        ]
        assert matches, f"письмо {kind} для {email} не отправлено"
        return matches[-1]

    def count(self, kind: str, email: str | None = None) -> int:
        return len(
            [
                mail
                for mail in self.sent
                if mail.kind == kind and (email is None or mail.email.lower() == email.lower())
            ]
        )


def registration(region_id: int, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "email": "buyer@example.kz",
        "password": CUSTOMER_PASSWORD,
        "contact_name": "Айгерим Сапарова",
        "company_name": "ТОО Площадки Алматы",
        "phone": "+7 (701) 555-44-33",
        "region_id": region_id,
    }
    body.update(overrides)
    return body


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def login_customer(
    api: AsyncClient, email: str, password: str = CUSTOMER_PASSWORD
) -> dict[str, Any]:
    response = await api.post(LOGIN_URL, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()
