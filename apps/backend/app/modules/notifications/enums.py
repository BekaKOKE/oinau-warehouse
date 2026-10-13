"""Перечисления исходящих уведомлений."""

from __future__ import annotations

from enum import StrEnum


class NotificationChannel(StrEnum):
    """Канал доставки. Значение совпадает с `NotificationProvider.name`."""

    TELEGRAM = "telegram"
    EMAIL = "email"


class OutboxStatus(StrEnum):
    """Состояние записи в outbox.

    SENDING существует ради конкурентных воркеров: запись переводится
    в него атомарно, поэтому два процесса не отправят одно письмо дважды.
    """

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    # Канал выключен или не настроен — это не ошибка.
    SKIPPED = "skipped"
    # Попытки исчерпаны или отказ окончательный.
    FAILED = "failed"


class NotificationEvent(StrEnum):
    """Бизнес-событие, породившее уведомление.

    Значения совпадают с действиями аудита там, где событие уже
    журналируется, — историю проще читать.
    """

    REQUEST_CREATED = "request.created"
    REQUEST_STATUS_CHANGED = "request.status_changed"
    REQUEST_COMMENT_ADDED = "request.comment_added"
    CUSTOMER_EMAIL_VERIFICATION = "customer.email_verification"
    CUSTOMER_PASSWORD_RESET = "customer.password_reset"  # noqa: S105 — событие, не пароль
