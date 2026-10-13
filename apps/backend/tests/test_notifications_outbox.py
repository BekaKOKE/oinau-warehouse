"""Очередь уведомлений: постановка, доставка, повторы, идемпотентность.

Провайдеры подменены во всех тестах: ни Telegram, ни SMTP не вызываются.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.notifications.base import DeliveryOutcome
from app.modules.notifications.dispatcher import NotificationDispatcher, retry_delay
from app.modules.notifications.enums import (
    NotificationChannel,
    NotificationEvent,
    OutboxStatus,
)
from app.modules.notifications.models import NotificationOutbox
from app.modules.notifications.service import NotificationService, build_dedup_key
from tests.integration_helpers import FakeRegistry, RecordingProvider

pytestmark = pytest.mark.asyncio


async def add_entry(
    session: AsyncSession,
    *,
    event: NotificationEvent = NotificationEvent.REQUEST_CREATED,
    channel: NotificationChannel = NotificationChannel.TELEGRAM,
    recipient: str = "-100500",
    payload: dict | None = None,
    dedup_key: str | None = None,
) -> NotificationOutbox:
    service = NotificationService(session)
    entry = service.enqueue(
        event=event,
        channel=channel,
        recipient=recipient,
        payload=payload if payload is not None else {"number": "R-2026-000001"},
        dedup_key=dedup_key,
    )
    assert entry is not None
    await session.commit()
    await session.refresh(entry)
    return entry


async def reload(session: AsyncSession, entry_id: int) -> NotificationOutbox:
    session.expire_all()
    return (
        await session.execute(select(NotificationOutbox).where(NotificationOutbox.id == entry_id))
    ).scalar_one()


class TestEnqueue:
    async def test_запись_создаётся_в_состоянии_ожидания(
        self, committed_session: AsyncSession
    ) -> None:
        entry = await add_entry(committed_session)

        assert entry.status == OutboxStatus.PENDING.value
        assert entry.attempts == 0
        assert entry.sent_at is None

    async def test_пустой_получатель_не_создаёт_запись(
        self, committed_session: AsyncSession
    ) -> None:
        """Незаполненный список деловых адресов — нормальное состояние."""
        service = NotificationService(committed_session)

        assert (
            service.enqueue(
                event=NotificationEvent.REQUEST_CREATED,
                channel=NotificationChannel.EMAIL,
                recipient="   ",
                payload={},
            )
            is None
        )

    async def test_несколько_получателей_дают_отдельные_записи(
        self, committed_session: AsyncSession
    ) -> None:
        """Недоступность одного чата не должна мешать повтору по другому."""
        service = NotificationService(committed_session)
        entries = service.enqueue_many(
            event=NotificationEvent.REQUEST_CREATED,
            channel=NotificationChannel.TELEGRAM,
            recipients=["-100", "-200", "-100"],  # дубль отбрасывается
            payload={"number": "R-1"},
            subject_id="7",
        )
        await committed_session.commit()

        assert [entry.recipient for entry in entries] == ["-100", "-200"]
        assert len({entry.dedup_key for entry in entries}) == 2

    async def test_повтор_с_тем_же_ключом_не_создаёт_дубль(
        self, committed_session: AsyncSession
    ) -> None:
        key = build_dedup_key("request.created", "telegram", "-100500", "7")
        await add_entry(committed_session, dedup_key=key)

        service = NotificationService(committed_session)
        service.enqueue(
            event=NotificationEvent.REQUEST_CREATED,
            channel=NotificationChannel.TELEGRAM,
            recipient="-100500",
            payload={},
            dedup_key=key,
        )
        with pytest.raises(Exception, match="uq_notification_outbox_dedup_key"):
            await committed_session.commit()
        await committed_session.rollback()


class TestDispatch:
    async def test_успешная_отправка_помечает_запись_и_зовёт_провайдера(
        self, committed_session: AsyncSession
    ) -> None:
        entry = await add_entry(committed_session)
        registry = FakeRegistry()

        result = await NotificationDispatcher(committed_session, registry).dispatch(entry.id)

        assert result["sent"] == 1
        assert len(registry.telegram.sent) == 1
        assert "R-2026-000001" in registry.telegram.sent[0].text
        stored = await reload(committed_session, entry.id)
        assert stored.status == OutboxStatus.SENT.value
        assert stored.attempts == 1
        assert stored.sent_at is not None
        assert stored.last_error is None

    async def test_выключенный_канал_пропускает_запись_без_ошибки(
        self, committed_session: AsyncSession
    ) -> None:
        """Отключённый провайдер — не ошибка: повторять нечего."""
        entry = await add_entry(committed_session)
        registry = FakeRegistry(
            telegram=RecordingProvider(
                name="telegram",
                outcome=DeliveryOutcome.SKIPPED,
                detail="telegram_not_configured",
                enabled_flag=False,
            )
        )

        result = await NotificationDispatcher(committed_session, registry).dispatch(entry.id)

        assert result["skipped"] == 1
        stored = await reload(committed_session, entry.id)
        assert stored.status == OutboxStatus.SKIPPED.value
        assert stored.last_error == "telegram_not_configured"

    async def test_временный_сбой_переносит_отправку_на_потом(
        self, committed_session: AsyncSession
    ) -> None:
        entry = await add_entry(committed_session)
        registry = FakeRegistry(
            telegram=RecordingProvider(
                name="telegram", outcome=DeliveryOutcome.RETRY, detail="http_503"
            )
        )
        before = datetime.now(UTC)

        result = await NotificationDispatcher(committed_session, registry).dispatch(entry.id)

        assert result["retry"] == 1
        stored = await reload(committed_session, entry.id)
        assert stored.status == OutboxStatus.PENDING.value
        assert stored.attempts == 1
        assert stored.last_error == "http_503"
        assert stored.available_at > before

    async def test_попытки_исчерпаны_запись_становится_неудачной(
        self, committed_session: AsyncSession
    ) -> None:
        entry = await add_entry(committed_session)
        entry.max_attempts = 2
        await committed_session.commit()
        registry = FakeRegistry(
            telegram=RecordingProvider(name="telegram", outcome=DeliveryOutcome.RETRY)
        )
        dispatcher = NotificationDispatcher(committed_session, registry)

        await dispatcher.dispatch(entry.id)
        # Вторая попытка возможна только когда подошёл срок.
        stored = await reload(committed_session, entry.id)
        stored.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await committed_session.commit()
        await dispatcher.dispatch(entry.id)

        stored = await reload(committed_session, entry.id)
        assert stored.status == OutboxStatus.FAILED.value
        assert stored.attempts == 2

    async def test_окончательный_отказ_не_повторяется(
        self, committed_session: AsyncSession
    ) -> None:
        """4xx от провайдера: чат удалён, адрес не существует."""
        entry = await add_entry(committed_session)
        registry = FakeRegistry(
            telegram=RecordingProvider(
                name="telegram", outcome=DeliveryOutcome.FAILED, detail="http_400:chat not found"
            )
        )

        await NotificationDispatcher(committed_session, registry).dispatch(entry.id)

        stored = await reload(committed_session, entry.id)
        assert stored.status == OutboxStatus.FAILED.value
        assert stored.attempts == 1

    async def test_запись_не_отправляется_дважды(self, committed_session: AsyncSession) -> None:
        """Повторный проход по уже отправленной записи ничего не делает."""
        entry = await add_entry(committed_session)
        registry = FakeRegistry()
        dispatcher = NotificationDispatcher(committed_session, registry)

        await dispatcher.dispatch(entry.id)
        await dispatcher.dispatch(entry.id)

        assert len(registry.telegram.sent) == 1

    async def test_проход_без_идентификатора_забирает_всё_готовое(
        self, committed_session: AsyncSession
    ) -> None:
        await add_entry(committed_session, recipient="-1")
        await add_entry(committed_session, recipient="-2")
        registry = FakeRegistry()

        result = await NotificationDispatcher(committed_session, registry).dispatch()

        assert result["sent"] == 2

    async def test_запись_ожидающая_повтора_не_берётся_раньше_срока(
        self, committed_session: AsyncSession
    ) -> None:
        entry = await add_entry(committed_session)
        entry.available_at = datetime.now(UTC) + timedelta(hours=1)
        await committed_session.commit()
        registry = FakeRegistry()

        result = await NotificationDispatcher(committed_session, registry).dispatch()

        assert result == {"sent": 0, "skipped": 0, "retry": 0, "failed": 0}
        assert registry.telegram.sent == []

    async def test_неизвестное_событие_не_зацикливается(
        self, committed_session: AsyncSession
    ) -> None:
        """Нет шаблона — дефект кода: повторы не помогут, ставим failed."""
        entry = await add_entry(committed_session)
        entry.event = "unknown.event"
        await committed_session.commit()
        registry = FakeRegistry()

        await NotificationDispatcher(committed_session, registry).dispatch(entry.id)

        stored = await reload(committed_session, entry.id)
        assert stored.status == OutboxStatus.FAILED.value
        assert registry.telegram.sent == []


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
class TestRetryDelay:
    def test_пауза_растёт_экспоненциально_и_упирается_в_потолок(self) -> None:
        assert retry_delay(1) < retry_delay(2) < retry_delay(3)
        # Потолок: дальше расти бессмысленно.
        assert retry_delay(20) == retry_delay(30)
