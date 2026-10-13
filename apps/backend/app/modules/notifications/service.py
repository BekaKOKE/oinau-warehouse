"""Постановка уведомлений в outbox.

ЕДИНСТВЕННАЯ точка, из которой бизнес-логика узнаёт об уведомлениях.
Сервис ничего не отправляет и никуда не ходит по сети: он добавляет
строку в текущую транзакцию. Поэтому его вызов безопасен внутри любой
бизнес-операции и не может её замедлить, подвесить или уронить.

Не коммитит намеренно: намерение отправить фиксируется той же
транзакцией, что и само событие. Откат создания заявки откатывает
и уведомление о ней.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.core.service import BaseService
from app.modules.notifications.enums import (
    NotificationChannel,
    NotificationEvent,
    OutboxStatus,
)
from app.modules.notifications.models import LEN_DEDUP_KEY, NotificationOutbox

logger = get_logger(__name__)


def build_dedup_key(event: str, channel: str, recipient: str, subject_id: str) -> str:
    """Ключ «одно событие — одному получателю один раз».

    Обрезается до длины колонки: длинный адрес не должен ломать
    вставку, а вероятность совпадения обрезанных ключей разных
    получателей пренебрежима — в начале стоят событие и объект.
    """
    return f"{event}:{channel}:{subject_id}:{recipient}"[:LEN_DEDUP_KEY]


class NotificationService(BaseService):
    """Запись событий в outbox."""

    def enqueue(
        self,
        *,
        event: NotificationEvent,
        channel: NotificationChannel,
        recipient: str,
        payload: dict[str, Any],
        dedup_key: str | None = None,
    ) -> NotificationOutbox | None:
        """Добавляет одно уведомление. Пустой получатель — просто пропуск.

        Пустой получатель не ошибка: список деловых адресов может быть
        не заполнен, и это нормальное состояние локальной установки.
        """
        recipient = (recipient or "").strip()
        if not recipient:
            return None

        entry = NotificationOutbox(
            event=event.value,
            channel=channel.value,
            recipient=recipient,
            status=OutboxStatus.PENDING.value,
            payload=payload,
            dedup_key=dedup_key,
            max_attempts=settings.NOTIFY_MAX_ATTEMPTS,
        )
        self.session.add(entry)
        return entry

    def enqueue_many(
        self,
        *,
        event: NotificationEvent,
        channel: NotificationChannel,
        recipients: list[str],
        payload: dict[str, Any],
        subject_id: str,
    ) -> list[NotificationOutbox]:
        """Одно событие нескольким получателям — по записи на каждого.

        Отдельные записи, а не одна на всех: чат отдела может быть
        недоступен, а личка руководителя — работать, и повторять нужно
        только неудавшуюся доставку.
        """
        entries: list[NotificationOutbox] = []
        for recipient in dict.fromkeys(recipients):  # без дублей, порядок сохраняется
            entry = self.enqueue(
                event=event,
                channel=channel,
                recipient=recipient,
                payload=payload,
                dedup_key=build_dedup_key(event.value, channel.value, recipient, subject_id),
            )
            if entry is not None:
                entries.append(entry)
        return entries

    async def identify(self, entries: list[NotificationOutbox]) -> list[int]:
        """Присваивает id добавленным записям и возвращает их.

        Нужно вызывающему, чтобы ПОСЛЕ коммита точечно разбудить воркер.
        Берутся именно переданные записи, а не все pending в таблице:
        чужие события этой транзакции не касаются.
        """
        if not entries:
            return []
        await self.session.flush()
        return [entry.id for entry in entries if entry.id is not None]
