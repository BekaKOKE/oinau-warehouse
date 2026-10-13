"""Побудка воркера после коммита события.

Протокол, а не прямой вызов arq — по той же причине, что и в медиатеке:
HTTP-слой не должен знать, чем исполняются фоновые задачи, а тесты
подменяют очередь и ничего не отправляют.

Очередь здесь — УСКОРИТЕЛЬ, а не носитель правды. Событие уже лежит
в notification_outbox и будет отправлено периодическим проходом, даже
если Redis недоступен. Поэтому ошибка постановки в очередь гасится:
уронить создание заявки из-за недоступного Redis недопустимо.
"""

from __future__ import annotations

from typing import Protocol

from app.core.logging import get_logger
from app.workers.queue import enqueue

logger = get_logger(__name__)

DELIVER_NOTIFICATION_TASK = "deliver_notification"


class NotificationQueue(Protocol):
    async def enqueue_delivery(self, outbox_ids: list[int]) -> None: ...


class ArqNotificationQueue:
    async def enqueue_delivery(self, outbox_ids: list[int]) -> None:
        for outbox_id in outbox_ids:
            try:
                await enqueue(DELIVER_NOTIFICATION_TASK, outbox_id)
            except Exception as exc:
                # Событие сохранено в базе: периодический проход его подберёт.
                logger.warning(
                    "notification_enqueue_failed",
                    outbox_id=outbox_id,
                    error=type(exc).__name__,
                )


class NullNotificationQueue:
    """Ничего не делает: события заберёт периодический проход."""

    async def enqueue_delivery(self, outbox_ids: list[int]) -> None:
        return None


async def wake_worker(queue: NotificationQueue, outbox_ids: list[int]) -> None:
    """Побудка воркера, которая НЕ МОЖЕТ уронить бизнес-операцию.

    Вызывается после коммита. К этому моменту заявка уже создана,
    и любое исключение отсюда означало бы 500 на успешно принятой
    заявке — ровно то, ради чего и заведён outbox. Событие останется
    в базе, и периодический проход его отправит.

    Гашение стоит здесь, а не только внутри реализации очереди:
    защита не должна зависеть от вежливости конкретного провайдера.
    """
    if not outbox_ids:
        return
    try:
        await queue.enqueue_delivery(outbox_ids)
    except Exception as exc:
        logger.warning(
            "notification_wake_failed",
            count=len(outbox_ids),
            error=type(exc).__name__,
        )


def get_notification_queue() -> NotificationQueue:
    """Зависимость FastAPI; тесты подменяют её через dependency_overrides."""
    return ArqNotificationQueue()
