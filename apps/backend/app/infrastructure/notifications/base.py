"""Канал доставки уведомления.

Провайдер знает только «как отправить». Что именно отправлять и кому —
решает сервис уведомлений; повторы, счётчики попыток и хранение —
задача outbox и воркера. Такое разделение позволяет добавить новый
канал (WhatsApp Business API, SMS), не трогая бизнес-логику.

Провайдер НИКОГДА не поднимает исключение наружу как способ сообщить
о неудаче: он возвращает `DeliveryResult`. Отправка уведомления не
должна уронить задачу, которая её вызвала.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class DeliveryOutcome(StrEnum):
    SENT = "sent"
    # Канал выключен или не настроен: повторять бессмысленно.
    SKIPPED = "skipped"
    # Временная неудача: сеть, 5xx, таймаут. Воркер повторит.
    RETRY = "retry"
    # Постоянная неудача: неверный адрес, 4xx. Повторять бессмысленно.
    FAILED = "failed"


@dataclass(frozen=True)
class DeliveryResult:
    outcome: DeliveryOutcome
    # Короткое человекочитаемое пояснение для журнала и админки.
    # Секретов здесь не бывает: текст собирают сами провайдеры.
    detail: str = ""

    @property
    def is_sent(self) -> bool:
        return self.outcome is DeliveryOutcome.SENT


@dataclass(frozen=True)
class NotificationMessage:
    """Готовое к отправке сообщение.

    Одна структура на все каналы: Telegram использует `text`, письмо —
    `subject`, `text` и `html`. Лишние поля канал просто игнорирует.
    """

    recipient: str
    subject: str = ""
    text: str = ""
    html: str | None = None
    # Служебные пометки для провайдера (например, parse_mode).
    options: dict[str, str] = field(default_factory=dict)


class NotificationProvider(Protocol):
    """Канал доставки.

    `name` совпадает со значением NotificationChannel: по нему outbox
    выбирает провайдера, и оно же попадает в структурированный журнал.
    """

    name: str

    @property
    def enabled(self) -> bool:
        """Настроен ли канал. Ненастроенный канал не ошибка: локальная
        разработка и CI работают без единого реального реквизита."""
        ...

    async def send(self, message: NotificationMessage) -> DeliveryResult: ...


class DisabledProvider:
    """Заглушка для канала без конфигурации.

    Возвращает SKIPPED, а не ошибку: событие фиксируется в outbox как
    пропущенное, и ни одна бизнес-операция от этого не страдает.
    """

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self._reason = reason

    @property
    def enabled(self) -> bool:
        return False

    async def send(self, message: NotificationMessage) -> DeliveryResult:
        return DeliveryResult(DeliveryOutcome.SKIPPED, self._reason)
