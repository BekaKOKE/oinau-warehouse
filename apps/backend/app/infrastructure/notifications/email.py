"""Отправка писем по SMTP.

Используется стандартный `smtplib` в отдельном потоке, а не асинхронная
библиотека. Причина практическая: письма отправляет воркер, где блокировка
одного потока никого не задерживает, а лишняя зависимость в проекте,
который уже держит SMTP-пароль в настройках, — лишняя поверхность
обновлений. Таймаут задаётся явно, поэтому «повисший» SMTP не держит
задачу вечно.

Пароль SMTP не логируется ни при каких условиях: в журнал попадают
только хост, порт и класс ошибки.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import settings
from app.core.logging import get_logger
from app.infrastructure.notifications.base import (
    DeliveryOutcome,
    DeliveryResult,
    NotificationMessage,
)

logger = get_logger(__name__)

EMAIL_CHANNEL = "email"


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    use_starttls: bool
    use_ssl: bool
    sender: str
    sender_name: str
    timeout: float

    @classmethod
    def from_settings(cls) -> SmtpConfig:
        return cls(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            user=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_starttls=settings.SMTP_TLS,
            use_ssl=settings.SMTP_SSL,
            sender=settings.SMTP_FROM,
            sender_name=settings.SMTP_FROM_NAME,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
        )


def build_message(message: NotificationMessage, config: SmtpConfig) -> EmailMessage:
    """Письмо с текстовой и HTML-частью.

    Текстовая часть обязательна: часть корпоративных клиентов режет
    HTML, и письмо без текстовой альтернативы у них выглядит пустым.
    """
    email = EmailMessage()
    email["Subject"] = message.subject
    email["From"] = formataddr((config.sender_name, config.sender))
    email["To"] = message.recipient
    email.set_content(message.text or "")
    if message.html:
        email.add_alternative(message.html, subtype="html")
    return email


class SmtpEmailProvider:
    name = EMAIL_CHANNEL

    def __init__(self, config: SmtpConfig | None = None) -> None:
        self._config = config or SmtpConfig.from_settings()

    @property
    def enabled(self) -> bool:
        """Хост и адрес отправителя — необходимый минимум.
        Логин и пароль не обязательны: локальный mailpit их не требует."""
        return bool(self._config.host and self._config.sender)

    async def send(self, message: NotificationMessage) -> DeliveryResult:
        if not self.enabled:
            return DeliveryResult(DeliveryOutcome.SKIPPED, "smtp_not_configured")
        if not message.recipient:
            return DeliveryResult(DeliveryOutcome.FAILED, "empty_recipient")

        email = build_message(message, self._config)
        try:
            await asyncio.to_thread(self._send_blocking, email)
        except smtplib.SMTPRecipientsRefused:
            # Адрес не существует: повторы только сожгут репутацию отправителя.
            logger.warning("smtp_recipient_refused", host=self._config.host)
            return DeliveryResult(DeliveryOutcome.FAILED, "recipient_refused")
        except smtplib.SMTPAuthenticationError:
            # Неверный логин/пароль — это конфигурация, а не сбой сети.
            logger.error("smtp_auth_failed", host=self._config.host, port=self._config.port)
            return DeliveryResult(DeliveryOutcome.FAILED, "auth_failed")
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning(
                "smtp_send_retry",
                host=self._config.host,
                port=self._config.port,
                error=type(exc).__name__,
            )
            return DeliveryResult(DeliveryOutcome.RETRY, f"smtp:{type(exc).__name__}")

        return DeliveryResult(DeliveryOutcome.SENT)

    def _send_blocking(self, email: EmailMessage) -> None:
        config = self._config
        if config.use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                config.host, config.port, timeout=config.timeout, context=context
            ) as smtp:
                self._authenticate(smtp)
                smtp.send_message(email)
            return

        with smtplib.SMTP(config.host, config.port, timeout=config.timeout) as smtp:
            if config.use_starttls:
                smtp.starttls(context=ssl.create_default_context())
            self._authenticate(smtp)
            smtp.send_message(email)

    def _authenticate(self, smtp: smtplib.SMTP) -> None:
        if self._config.user and self._config.password:
            smtp.login(self._config.user, self._config.password)


def build_email_provider() -> SmtpEmailProvider:
    return SmtpEmailProvider()
