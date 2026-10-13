"""Помощники тестов интеграций: ключи, провайдеры, очередь уведомлений.

Ни один тест не обращается к настоящему Telegram или SMTP: провайдеры
подменяются целиком, а HTTP Telegram — транспортом httpx.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.notifications.base import (
    DeliveryOutcome,
    DeliveryResult,
    NotificationMessage,
)
from app.modules.integration.models import ApiKey
from app.modules.integration.security import IntegrationScope, hash_api_key, key_prefix

INTEGRATION = "/api/v1/integration"
HEALTH_URL = f"{INTEGRATION}/health"
PRODUCTS_URL = f"{INTEGRATION}/catalog/products/bulk-upsert"
PRICING_URL = f"{INTEGRATION}/pricing/bulk-upsert"
INVENTORY_URL = f"{INTEGRATION}/inventory/bulk-upsert"
REQUESTS_URL = f"{INTEGRATION}/requests"
ADMIN_STATUS_URL = "/api/v1/admin/integration/status"

# Ключ фиксирован: тесты не должны зависеть от случайности.
TEST_API_KEY = "oik_test-key-for-integration-suite-0001"


async def make_api_key(
    session: AsyncSession,
    *,
    key: str = TEST_API_KEY,
    name: str = "1С обмен (тест)",
    scopes: list[str] | None = None,
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> ApiKey:
    api_key = ApiKey(
        name=name,
        key_hash=hash_api_key(key),
        key_prefix=key_prefix(key),
        scopes=scopes if scopes is not None else sorted(IntegrationScope.ALL),
        is_active=is_active,
        expires_at=expires_at,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    return api_key


def auth_headers(key: str = TEST_API_KEY) -> dict[str, str]:
    return {"X-API-Key": key}


# ---------------------------------------------------------------- провайдеры


@dataclass
class SentNotification:
    channel: str
    message: NotificationMessage


@dataclass
class RecordingProvider:
    """Провайдер, который запоминает сообщения вместо отправки."""

    name: str
    outcome: DeliveryOutcome = DeliveryOutcome.SENT
    detail: str = ""
    enabled_flag: bool = True
    sent: list[NotificationMessage] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return self.enabled_flag

    async def send(self, message: NotificationMessage) -> DeliveryResult:
        self.sent.append(message)
        return DeliveryResult(self.outcome, self.detail)


class FakeRegistry:
    """Реестр провайдеров для тестов."""

    def __init__(self, **providers: RecordingProvider) -> None:
        self._providers = providers

    def get(self, channel: str) -> RecordingProvider:
        if channel not in self._providers:
            self._providers[channel] = RecordingProvider(name=channel)
        return self._providers[channel]

    @property
    def telegram(self) -> RecordingProvider:
        return self.get("telegram")

    @property
    def email(self) -> RecordingProvider:
        return self.get("email")

    def all_sent(self) -> list[SentNotification]:
        return [
            SentNotification(channel=name, message=message)
            for name, provider in self._providers.items()
            for message in provider.sent
        ]


@dataclass
class FakeNotificationQueue:
    """Очередь, которая только запоминает разбуженные события."""

    woken: list[int] = field(default_factory=list)
    fail: bool = False

    async def enqueue_delivery(self, outbox_ids: list[int]) -> None:
        if self.fail:
            raise RuntimeError("Redis недоступен")
        self.woken.extend(outbox_ids)


def telegram_transport(
    handler: object = None, *, status_code: int = 200, body: dict | None = None
) -> httpx.MockTransport:
    """Транспорт httpx вместо настоящего api.telegram.org."""
    calls: list[httpx.Request] = []

    def _handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if callable(handler):
            return handler(request)  # type: ignore[operator]
        return httpx.Response(status_code, json=body if body is not None else {"ok": True})

    transport = httpx.MockTransport(_handle)
    transport.calls = calls  # type: ignore[attr-defined]
    return transport
