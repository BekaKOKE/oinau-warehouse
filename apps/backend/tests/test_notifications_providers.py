"""Провайдеры доставки: Telegram и SMTP.

Ни один тест не делает настоящего сетевого вызова: Telegram работает
через MockTransport httpx, SMTP — через подменённую отправку.
"""

from __future__ import annotations

import json
import smtplib
from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.infrastructure.notifications.base import DeliveryOutcome, NotificationMessage
from app.infrastructure.notifications.email import SmtpConfig, SmtpEmailProvider, build_message
from app.infrastructure.notifications.registry import ProviderRegistry
from app.infrastructure.notifications.telegram import MAX_MESSAGE_LENGTH, TelegramProvider

pytestmark = pytest.mark.asyncio

TOKEN = "1234567890:AAH-super-secret-bot-token-value"
CHAT = "-1001234567890"


def _message(text: str = "Новая заявка R-1") -> NotificationMessage:
    return NotificationMessage(recipient=CHAT, text=text)


def _provider(
    handler: Any, token: str = TOKEN, message_thread_id: int | None = None
) -> TelegramProvider:
    return TelegramProvider(
        token=token,
        api_base_url="https://api.telegram.test",
        timeout=1.0,
        message_thread_id=message_thread_id,
        transport=httpx.MockTransport(handler),
    )


class TestTelegram:
    async def test_успешная_отправка_уходит_в_send_message(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"ok": True})

        result = await _provider(handler).send(_message())

        assert result.outcome is DeliveryOutcome.SENT
        assert seen[0].url.path.endswith("/sendMessage")
        body = json.loads(seen[0].content)
        assert body["chat_id"] == CHAT
        assert body["text"] == "Новая заявка R-1"
        # Предпросмотр ссылок отключён: карточка админки не должна
        # разворачиваться в чат.
        assert body["disable_web_page_preview"] is True

    async def test_ненастроенный_канал_пропускает_без_запроса(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"ok": True})

        provider = _provider(handler, token="")
        result = await provider.send(_message())

        assert provider.enabled is False
        assert result.outcome is DeliveryOutcome.SKIPPED
        assert result.detail == "telegram_not_configured"
        assert calls == []

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    async def test_перегрузка_телеграма_даёт_повтор(self, status: int) -> None:
        result = await _provider(
            lambda request: httpx.Response(status, json={"description": "Too Many Requests"})
        ).send(_message())

        assert result.outcome is DeliveryOutcome.RETRY

    @pytest.mark.parametrize("status", [400, 401, 403])
    async def test_отказ_телеграма_не_повторяется(self, status: int) -> None:
        """Чат удалён, бот заблокирован, токен отозван — повтор бесполезен."""
        result = await _provider(
            lambda request: httpx.Response(status, json={"description": "chat not found"})
        ).send(_message())

        assert result.outcome is DeliveryOutcome.FAILED
        assert "chat not found" in result.detail

    async def test_таймаут_даёт_повтор(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout", request=request)

        result = await _provider(handler).send(_message())

        assert result.outcome is DeliveryOutcome.RETRY
        assert result.detail == "timeout"

    async def test_сетевой_сбой_даёт_повтор(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        result = await _provider(handler).send(_message())

        assert result.outcome is DeliveryOutcome.RETRY

    async def test_длинное_сообщение_обрезается_до_лимита(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"ok": True})

        await _provider(handler).send(_message("я" * (MAX_MESSAGE_LENGTH + 500)))

        assert len(json.loads(seen[0].content)["text"]) == MAX_MESSAGE_LENGTH

    async def test_тема_форума_уходит_в_message_thread_id(self) -> None:
        """Заявки идут в отдельную тему супергруппы, а не в общий поток."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"ok": True})

        result = await _provider(handler, message_thread_id=42).send(_message())

        assert result.outcome is DeliveryOutcome.SENT
        body = json.loads(seen[0].content)
        assert body["message_thread_id"] == 42
        # Чат остаётся прежним: тема уточняет место внутри него.
        assert body["chat_id"] == CHAT

    async def test_без_темы_поле_не_отправляется(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Обычный чат не форум: лишнее поле вернуло бы 400 от Bot API."""
        monkeypatch.setattr(settings, "TELEGRAM_MESSAGE_THREAD_ID", None)
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"ok": True})

        result = await _provider(handler).send(_message())

        assert result.outcome is DeliveryOutcome.SENT
        assert "message_thread_id" not in json.loads(seen[0].content)

    async def test_тема_берётся_из_настроек(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Провайдер собирается без аргументов — значение приходит из .env."""
        monkeypatch.setattr(settings, "TELEGRAM_MESSAGE_THREAD_ID", 777)
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"ok": True})

        await _provider(handler).send(_message())

        assert json.loads(seen[0].content)["message_thread_id"] == 777

    async def test_несуществующая_тема_не_повторяется(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Опечатка в id темы не лечится повтором — только правкой .env.

        Ответ Telegram попадает в detail записи outbox, чтобы причина
        была видна в админке без чтения журналов.
        """
        monkeypatch.setattr(settings, "TELEGRAM_MESSAGE_THREAD_ID", 999_999)
        result = await _provider(
            lambda request: httpx.Response(
                400, json={"ok": False, "description": "Bad Request: message thread not found"}
            )
        ).send(_message())

        assert result.outcome is DeliveryOutcome.FAILED
        assert "message thread not found" in result.detail

    async def test_пустой_чат_это_окончательная_ошибка(self) -> None:
        result = await _provider(lambda request: httpx.Response(200, json={"ok": True})).send(
            NotificationMessage(recipient="", text="x")
        )

        assert result.outcome is DeliveryOutcome.FAILED

    async def test_токен_не_попадает_в_журнал(self, caplog: pytest.LogCaptureFixture) -> None:
        """Токен стоит в пути URL — ни URL, ни токен не логируются."""
        with caplog.at_level("DEBUG"):
            await _provider(
                lambda request: httpx.Response(403, json={"description": "bot was blocked"})
            ).send(_message())

        assert TOKEN not in caplog.text
        assert "AAH-super-secret" not in caplog.text
        # И идентификатор чата целиком тоже не пишется.
        assert CHAT not in caplog.text


class TestEmail:
    @staticmethod
    def _config(**overrides: Any) -> SmtpConfig:
        base = {
            "host": "smtp.test",
            "port": 587,
            "user": "sender",
            "password": "smtp-secret-password",
            "use_starttls": True,
            "use_ssl": False,
            "sender": "noreply@oinau-pro.kz",
            "sender_name": "OINAU PRO",
            "timeout": 5.0,
        }
        base.update(overrides)
        return SmtpConfig(**base)  # type: ignore[arg-type]

    def test_письмо_содержит_текст_и_html(self) -> None:
        """Текстовая часть обязательна: часть клиентов режет HTML."""
        message = NotificationMessage(
            recipient="client@example.kz",
            subject="Тема",
            text="Простой текст",
            html="<p>Разметка</p>",
        )

        email = build_message(message, self._config())

        assert email["Subject"] == "Тема"
        assert email["To"] == "client@example.kz"
        assert email["From"] == "OINAU PRO <noreply@oinau-pro.kz>"
        assert email.get_body(("plain",)).get_content().strip() == "Простой текст"
        assert "Разметка" in email.get_body(("html",)).get_content()

    async def test_ненастроенный_smtp_пропускает(self) -> None:
        provider = SmtpEmailProvider(self._config(host=""))

        result = await provider.send(NotificationMessage(recipient="a@b.kz", subject="x"))

        assert provider.enabled is False
        assert result.outcome is DeliveryOutcome.SKIPPED

    async def test_успешная_отправка(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sent: list[Any] = []
        provider = SmtpEmailProvider(self._config())
        monkeypatch.setattr(provider, "_send_blocking", sent.append)

        result = await provider.send(
            NotificationMessage(recipient="a@b.kz", subject="Тема", text="Текст")
        )

        assert result.outcome is DeliveryOutcome.SENT
        assert len(sent) == 1

    async def test_временный_сбой_smtp_даёт_повтор(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = SmtpEmailProvider(self._config())

        def boom(_email: Any) -> None:
            raise smtplib.SMTPServerDisconnected("connection lost")

        monkeypatch.setattr(provider, "_send_blocking", boom)
        result = await provider.send(NotificationMessage(recipient="a@b.kz", subject="x"))

        assert result.outcome is DeliveryOutcome.RETRY

    async def test_несуществующий_адрес_не_повторяется(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = SmtpEmailProvider(self._config())

        def boom(_email: Any) -> None:
            raise smtplib.SMTPRecipientsRefused({})

        monkeypatch.setattr(provider, "_send_blocking", boom)
        result = await provider.send(NotificationMessage(recipient="a@b.kz", subject="x"))

        assert result.outcome is DeliveryOutcome.FAILED

    async def test_неверный_пароль_не_повторяется(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Это конфигурация, а не сбой сети: повторы её не исправят."""
        provider = SmtpEmailProvider(self._config())

        def boom(_email: Any) -> None:
            raise smtplib.SMTPAuthenticationError(535, b"auth failed")

        monkeypatch.setattr(provider, "_send_blocking", boom)
        result = await provider.send(NotificationMessage(recipient="a@b.kz", subject="x"))

        assert result.outcome is DeliveryOutcome.FAILED

    async def test_пароль_не_попадает_в_журнал(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = SmtpEmailProvider(self._config())

        def boom(_email: Any) -> None:
            raise smtplib.SMTPAuthenticationError(535, b"auth failed")

        monkeypatch.setattr(provider, "_send_blocking", boom)
        with caplog.at_level("DEBUG"):
            await provider.send(NotificationMessage(recipient="a@b.kz", subject="x"))

        assert "smtp-secret-password" not in caplog.text


class TestRegistry:
    async def test_общий_выключатель_гасит_все_каналы(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """staging с боевыми реквизитами не должен рассылать письма."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
        registry = ProviderRegistry()

        for channel in ("telegram", "email"):
            provider = registry.get(channel)
            assert provider.enabled is False
            result = await provider.send(NotificationMessage(recipient="x", text="y"))
            assert result.outcome is DeliveryOutcome.SKIPPED
            assert result.detail == "notifications_disabled"

    async def test_неизвестный_канал_не_роняет_доставку(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
        provider = ProviderRegistry().get("carrier-pigeon")

        result = await provider.send(NotificationMessage(recipient="x", text="y"))

        assert result.outcome is DeliveryOutcome.SKIPPED
        assert result.detail == "unknown_channel"
