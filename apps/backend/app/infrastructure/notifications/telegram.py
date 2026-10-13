"""Отправка в Telegram через Bot API.

Токен бота — секрет уровня пароля: он стоит в пути URL, поэтому в
журнал не попадает ни сам URL, ни тело ошибки Telegram целиком.
Логируется только код ответа и код ошибки API.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.infrastructure.notifications.base import (
    DeliveryOutcome,
    DeliveryResult,
    NotificationMessage,
)

logger = get_logger(__name__)

TELEGRAM_CHANNEL = "telegram"

# Ограничение Bot API на длину sendMessage.
MAX_MESSAGE_LENGTH = 4096

# Коды, при которых повтор осмыслен: перегрузка и сбои самого Telegram.
_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


class TelegramProvider:
    """Канал Telegram.

    HTTP-клиент создаётся на отправку, а не держится глобально: воркер
    отправляет редкими всплесками, а живое соединение между задачами
    пришлось бы закрывать вручную при остановке процесса.
    """

    name = TELEGRAM_CHANNEL

    def __init__(
        self,
        *,
        token: str | None = None,
        api_base_url: str | None = None,
        timeout: float | None = None,
        message_thread_id: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token if token is not None else settings.TELEGRAM_BOT_TOKEN
        self._base_url = (api_base_url or settings.TELEGRAM_API_BASE_URL).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.TELEGRAM_TIMEOUT_SECONDS
        self._thread_id = (
            message_thread_id
            if message_thread_id is not None
            else settings.TELEGRAM_MESSAGE_THREAD_ID
        )
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    async def send(self, message: NotificationMessage) -> DeliveryResult:
        if not self.enabled:
            return DeliveryResult(DeliveryOutcome.SKIPPED, "telegram_not_configured")
        if not message.recipient:
            return DeliveryResult(DeliveryOutcome.FAILED, "empty_chat_id")

        payload: dict[str, Any] = {
            "chat_id": message.recipient,
            "text": message.text[:MAX_MESSAGE_LENGTH],
            "disable_web_page_preview": True,
        }
        # Тема форумной супергруппы. Поле добавляется, только когда она
        # задана: для обычного чата Bot API отвечает на него ошибкой
        # «message thread not found», а не игнорирует.
        if self._thread_id is not None:
            payload["message_thread_id"] = self._thread_id
        parse_mode = message.options.get("parse_mode")
        if parse_mode:
            payload["parse_mode"] = parse_mode

        # URL содержит токен и поэтому НИ РАЗУ не логируется.
        # Логгер httpx, который печатает строку запроса сам, приглушён
        # в app/core/logging.py — иначе токен утёк бы мимо нас.
        url = f"{self._base_url}/bot{self._token}/sendMessage"
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException:
            logger.warning("telegram_timeout", chat_id=_mask_chat(message.recipient))
            return DeliveryResult(DeliveryOutcome.RETRY, "timeout")
        except httpx.HTTPError as exc:
            logger.warning(
                "telegram_transport_error",
                chat_id=_mask_chat(message.recipient),
                error=type(exc).__name__,
            )
            return DeliveryResult(DeliveryOutcome.RETRY, f"transport:{type(exc).__name__}")

        if response.status_code == httpx.codes.OK:
            return DeliveryResult(DeliveryOutcome.SENT)

        description = _describe(response)
        if response.status_code in _RETRYABLE_STATUSES:
            logger.warning(
                "telegram_send_retry",
                status=response.status_code,
                chat_id=_mask_chat(message.recipient),
                description=description,
            )
            return DeliveryResult(DeliveryOutcome.RETRY, f"http_{response.status_code}")

        # 400/401/403: неверный чат, бот заблокирован, токен отозван.
        # Повторы ничего не изменят, а бесконечная очередь скроет проблему.
        logger.error(
            "telegram_send_failed",
            status=response.status_code,
            chat_id=_mask_chat(message.recipient),
            description=description,
        )
        return DeliveryResult(DeliveryOutcome.FAILED, f"http_{response.status_code}:{description}")


def _describe(response: httpx.Response) -> str:
    """Пояснение Telegram без тела ответа целиком.

    Bot API кладёт причину в поле `description`. Оно безопасно: своих
    секретов там нет, а echo нашего запроса в него не попадает.
    """
    try:
        body = response.json()
    except ValueError:
        return ""
    description = body.get("description") if isinstance(body, dict) else None
    return str(description)[:200] if description else ""


def _mask_chat(chat_id: str) -> str:
    """Идентификатор чата не секрет, но и не нужен в журнале целиком."""
    return chat_id[:4] + "…" if len(chat_id) > 4 else chat_id


def build_telegram_provider() -> TelegramProvider:
    return TelegramProvider()
