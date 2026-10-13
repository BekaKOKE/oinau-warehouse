"""Доставка уведомлений из outbox. Исполняется воркером.

Запись забирается атомарно: UPDATE ... WHERE status IN (pending,
sending) AND available_at <= now() RETURNING. Два воркера не отправят
одно письмо дважды, даже если оба проснулись одновременно.

Внешний вызов делается ВНЕ транзакции записи результата: сначала
запись помечается «в отправке» и транзакция закрывается, затем идёт
сеть, затем отдельной транзакцией фиксируется исход. Иначе соединение
с базой висело бы на время сетевого таймаута SMTP.

Зависшая в SENDING запись не теряется: `available_at` при захвате
сдвигается вперёд, поэтому следующий проход подберёт её как обычную
просроченную.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.infrastructure.notifications.base import DeliveryOutcome, DeliveryResult
from app.infrastructure.notifications.registry import ProviderRegistry, get_provider_registry
from app.modules.notifications.enums import OutboxStatus
from app.modules.notifications.messages import build_message
from app.modules.notifications.models import LEN_ERROR, NotificationOutbox

logger = get_logger(__name__)

# Сколько записей забирает один проход. Ограничение защищает воркер
# от попытки разослать накопившуюся за сутки очередь одним заходом.
DISPATCH_BATCH = 50

# Потолок паузы между попытками: дальше расти бессмысленно, проблема
# либо решится, либо потребует человека.
MAX_BACKOFF = timedelta(hours=6)

# Запись, «зависшая» в SENDING (воркер убит между захватом и отчётом),
# снова становится доступной через это время.
STUCK_TIMEOUT = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now(UTC)


def retry_delay(attempts: int) -> timedelta:
    """Экспоненциальный откат: base, 2·base, 4·base… но не дольше MAX_BACKOFF."""
    base = max(settings.NOTIFY_RETRY_BASE_SECONDS, 1)
    # 2**(attempts-1) при attempts до 20 — обычное целое, переполнения нет.
    factor = 2 ** max(attempts - 1, 0)
    return min(timedelta(seconds=base * factor), MAX_BACKOFF)


class NotificationDispatcher:
    """Отправка записей outbox.

    Реестр провайдеров передаётся снаружи: тесты подставляют свой
    и ни разу не касаются ни SMTP, ни Telegram.
    """

    def __init__(self, session: AsyncSession, registry: ProviderRegistry | None = None) -> None:
        self.session = session
        self.registry = registry or get_provider_registry()

    # ------------------------------------------------------------- захват

    async def _claim(self, entry_id: int | None) -> list[NotificationOutbox]:
        """Переводит готовые записи в SENDING и возвращает их.

        Один UPDATE вместо SELECT + UPDATE: между двумя запросами
        конкурент успел бы забрать ту же запись.
        """
        now = _now()
        due = select(NotificationOutbox.id).where(
            NotificationOutbox.available_at <= now,
            NotificationOutbox.status.in_([OutboxStatus.PENDING.value, OutboxStatus.SENDING.value]),
        )
        if entry_id is not None:
            due = due.where(NotificationOutbox.id == entry_id)
        due = due.order_by(NotificationOutbox.available_at).limit(DISPATCH_BATCH)
        # SKIP LOCKED: параллельные воркеры разбирают очередь, а не ждут
        # друг друга на первой же строке.
        due = due.with_for_update(skip_locked=True)

        ids = list((await self.session.execute(due)).scalars().all())
        if not ids:
            return []

        claimed = await self.session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.id.in_(ids))
            .values(
                status=OutboxStatus.SENDING.value,
                # Сдвиг вперёд: если воркер умрёт после захвата,
                # запись вернётся в работу сама.
                available_at=now + STUCK_TIMEOUT,
            )
            .returning(NotificationOutbox)
        )
        entries = list(claimed.scalars().all())
        await self.session.commit()
        return entries

    # ----------------------------------------------------------- отправка

    async def dispatch(self, entry_id: int | None = None) -> dict[str, int]:
        """Отправляет готовые записи. `entry_id` — конкретное событие.

        Возвращает счётчики исходов: их пишет воркер в структурированный
        журнал, а тесты по ним проверяют поведение.
        """
        counters = {"sent": 0, "skipped": 0, "retry": 0, "failed": 0}
        for entry in await self._claim(entry_id):
            outcome = await self._deliver(entry)
            counters[outcome.value] = counters.get(outcome.value, 0) + 1
        return counters

    async def _deliver(self, entry: NotificationOutbox) -> DeliveryOutcome:
        provider = self.registry.get(entry.channel)
        try:
            message = build_message(
                event=entry.event,
                channel=entry.channel,
                recipient=entry.recipient,
                payload=entry.payload or {},
            )
        except ValueError as exc:
            # Нет шаблона — это дефект кода, повторы не помогут.
            result = DeliveryResult(DeliveryOutcome.FAILED, str(exc)[:LEN_ERROR])
        else:
            result = await provider.send(message)

        await self._record(entry, result)
        return result.outcome

    async def _record(self, entry: NotificationOutbox, result: DeliveryResult) -> None:
        now = _now()
        entry.attempts += 1
        entry.last_error = result.detail[:LEN_ERROR] or None

        if result.outcome is DeliveryOutcome.SENT:
            entry.status = OutboxStatus.SENT.value
            entry.sent_at = now
            entry.last_error = None
        elif result.outcome is DeliveryOutcome.SKIPPED:
            # Канал выключен: это конечное состояние, а не ошибка.
            entry.status = OutboxStatus.SKIPPED.value
        elif result.outcome is DeliveryOutcome.RETRY and entry.attempts < entry.max_attempts:
            entry.status = OutboxStatus.PENDING.value
            entry.available_at = now + retry_delay(entry.attempts)
        else:
            entry.status = OutboxStatus.FAILED.value

        await self.session.merge(entry)
        await self.session.commit()

        logger.info(
            "notification_dispatched",
            outbox_id=entry.id,
            # Не `event`: это имя занято самим structlog под название события.
            notification=entry.event,
            channel=entry.channel,
            status=entry.status,
            attempts=entry.attempts,
            # Ни адреса, ни chat_id, ни текста сообщения: в журнале
            # только то, по чему разбирают инцидент.
            detail=result.detail or None,
        )
