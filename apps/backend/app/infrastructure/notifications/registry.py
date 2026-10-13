"""Выбор провайдера по каналу.

Единственное место, где канал превращается в конкретную реализацию.
Тесты подменяют реестр целиком, поэтому ни один тест не обращается
ни к Telegram, ни к SMTP.
"""

from __future__ import annotations

from app.core.config import settings
from app.infrastructure.notifications.base import DisabledProvider, NotificationProvider
from app.infrastructure.notifications.email import EMAIL_CHANNEL, build_email_provider
from app.infrastructure.notifications.telegram import TELEGRAM_CHANNEL, build_telegram_provider


class ProviderRegistry:
    """Набор каналов доставки.

    Провайдеры создаются лениво и запоминаются: реестр живёт столько же,
    сколько задача воркера, и пересоздавать клиентов на каждое событие
    незачем.
    """

    def __init__(self) -> None:
        self._providers: dict[str, NotificationProvider] = {}

    def get(self, channel: str) -> NotificationProvider:
        provider = self._providers.get(channel)
        if provider is None:
            provider = self._build(channel)
            self._providers[channel] = provider
        return provider

    @staticmethod
    def _build(channel: str) -> NotificationProvider:
        # Общий выключатель важнее настроек канала: staging с боевыми
        # реквизитами не должен рассылать письма живым клиентам.
        if not settings.NOTIFICATIONS_ENABLED:
            return DisabledProvider(channel, "notifications_disabled")
        if channel == TELEGRAM_CHANNEL:
            return build_telegram_provider()
        if channel == EMAIL_CHANNEL:
            return build_email_provider()
        return DisabledProvider(channel, "unknown_channel")


def get_provider_registry() -> ProviderRegistry:
    return ProviderRegistry()
