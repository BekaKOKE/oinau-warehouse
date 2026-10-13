"""Бизнес-события → уведомления: заявки, статусы, комментарии, письма кабинета.

Проверяется весь путь: HTTP-запрос → строка в notification_outbox →
доставка подменённым провайдером → содержимое сообщения.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.dispatcher import NotificationDispatcher
from app.modules.notifications.enums import (
    NotificationChannel,
    NotificationEvent,
    OutboxStatus,
)
from app.modules.notifications.models import NotificationOutbox
from app.modules.requests.models import Request
from tests.catalog_fixtures import CatalogFixture
from tests.integration_helpers import FakeNotificationQueue, FakeRegistry
from tests.request_helpers import PUBLIC_REQUESTS, request_payload

pytestmark = pytest.mark.asyncio

TELEGRAM_CHATS = ["-1001", "-1002"]
BUSINESS_EMAILS = ["sales@oinau-pro.kz"]


@pytest.fixture
def business_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    """Деловые получатели заданы: иначе уведомлений не будет вовсе."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", TELEGRAM_CHATS)
    monkeypatch.setattr(settings, "NOTIFY_EMAILS", BUSINESS_EMAILS)


async def outbox_rows(
    session: AsyncSession, event: NotificationEvent | None = None
) -> list[NotificationOutbox]:
    session.expire_all()
    query = select(NotificationOutbox).order_by(NotificationOutbox.id)
    if event is not None:
        query = query.where(NotificationOutbox.event == event.value)
    return list((await session.execute(query)).scalars().all())


class TestRequestCreated:
    async def test_новая_заявка_ставит_уведомления_всем_деловым_получателям(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        catalog: CatalogFixture,
        business_channels: None,
    ) -> None:
        response = await api.post(
            PUBLIC_REQUESTS, json=request_payload(catalog, [{"sku": "KAN-16-PP", "quantity": "50"}])
        )
        assert response.status_code == 201

        rows = await outbox_rows(committed_session, NotificationEvent.REQUEST_CREATED)
        assert [row.recipient for row in rows] == [*TELEGRAM_CHATS, *BUSINESS_EMAILS]
        assert {row.channel for row in rows} == {
            NotificationChannel.TELEGRAM.value,
            NotificationChannel.EMAIL.value,
        }
        assert all(row.status == OutboxStatus.PENDING.value for row in rows)

    async def test_уведомление_ставится_в_той_же_транзакции_и_будит_воркера_после_коммита(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        catalog: CatalogFixture,
        business_channels: None,
        notification_queue: FakeNotificationQueue,
    ) -> None:
        await api.post(
            PUBLIC_REQUESTS, json=request_payload(catalog, [{"sku": "KAN-16-PP", "quantity": "10"}])
        )

        rows = await outbox_rows(committed_session, NotificationEvent.REQUEST_CREATED)
        # Разбужены ровно те записи, что созданы транзакцией заявки.
        assert sorted(notification_queue.woken) == sorted(row.id for row in rows)

    async def test_недоступная_очередь_не_ломает_создание_заявки(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        catalog: CatalogFixture,
        business_channels: None,
        notification_queue: FakeNotificationQueue,
    ) -> None:
        """Redis лежит — заявка всё равно принята, событие ждёт в базе."""
        notification_queue.fail = True

        response = await api.post(
            PUBLIC_REQUESTS, json=request_payload(catalog, [{"sku": "KAN-16-PP", "quantity": "10"}])
        )

        assert response.status_code == 201
        assert (await committed_session.execute(select(Request))).scalars().first() is not None
        assert await outbox_rows(committed_session, NotificationEvent.REQUEST_CREATED)

    async def test_без_настроенных_каналов_уведомлений_нет_а_заявка_есть(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture
    ) -> None:
        """Локальная установка без реквизитов — рабочее состояние."""
        response = await api.post(
            PUBLIC_REQUESTS, json=request_payload(catalog, [{"sku": "KAN-16-PP", "quantity": "10"}])
        )

        assert response.status_code == 201
        assert await outbox_rows(committed_session) == []

    async def test_повторная_заявка_по_ключу_идемпотентности_не_шлёт_второе_уведомление(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        catalog: CatalogFixture,
        business_channels: None,
    ) -> None:
        payload = request_payload(catalog, [{"sku": "KAN-16-PP", "quantity": "10"}])
        headers = {"Idempotency-Key": "form-session-0001"}

        first = await api.post(PUBLIC_REQUESTS, json=payload, headers=headers)
        second = await api.post(PUBLIC_REQUESTS, json=payload, headers=headers)

        assert first.status_code == second.status_code == 201
        rows = await outbox_rows(committed_session, NotificationEvent.REQUEST_CREATED)
        assert len(rows) == len(TELEGRAM_CHATS) + len(BUSINESS_EMAILS)

    async def test_сообщение_в_telegram_содержит_деловую_суть_заявки(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        catalog: CatalogFixture,
        business_channels: None,
    ) -> None:
        await api.post(
            PUBLIC_REQUESTS,
            json=request_payload(
                catalog,
                [
                    {"sku": "KAN-16-PP", "quantity": "50"},
                    {"sku": "KRP-M10", "quantity": "4"},
                ],
            ),
        )
        registry = FakeRegistry()

        await NotificationDispatcher(committed_session, registry).dispatch()

        text = registry.telegram.sent[0].text
        assert "Новая заявка" in text
        assert "R-2026-" in text
        assert "KAN-16-PP" in text  # артикул
        assert "50" in text  # количество
        assert "Алматы" in text  # регион
        assert "Позиции (2)" in text
        # Ссылка на карточку в админке — то, ради чего сообщение и читают.
        assert "/requests/" in text

    async def test_в_уведомлении_нет_секретов(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        catalog: CatalogFixture,
        business_channels: None,
    ) -> None:
        await api.post(
            PUBLIC_REQUESTS, json=request_payload(catalog, [{"sku": "KAN-16-PP", "quantity": "10"}])
        )
        registry = FakeRegistry()

        await NotificationDispatcher(committed_session, registry).dispatch()

        for sent in registry.all_sent():
            blob = f"{sent.message.subject}{sent.message.text}{sent.message.html or ''}"
            for secret in ("password", "token", "secret", "ip_hash", "idempotency"):
                assert secret not in blob.lower()

    async def test_деловое_письмо_имеет_текст_и_html(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        catalog: CatalogFixture,
        business_channels: None,
    ) -> None:
        await api.post(
            PUBLIC_REQUESTS, json=request_payload(catalog, [{"sku": "KAN-16-PP", "quantity": "10"}])
        )
        registry = FakeRegistry()

        await NotificationDispatcher(committed_session, registry).dispatch()

        message = registry.email.sent[0]
        assert message.subject.startswith("[OINAU PRO] Новая заявка")
        assert message.text
        assert message.html and "OINAU PRO" in message.html


class TestCustomerEmails:
    """Письма клиенту: только на подтверждённый адрес."""

    async def test_смена_статуса_шлёт_письмо_клиенту(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        verified_customer_request,
        admin: dict[str, str],
    ) -> None:
        request_id, email = verified_customer_request

        response = await api.patch(
            f"/api/v1/admin/requests/{request_id}/status",
            json={"status": "IN_PROGRESS"},
            headers=admin,
        )
        assert response.status_code == 200

        rows = await outbox_rows(committed_session, NotificationEvent.REQUEST_STATUS_CHANGED)
        assert [row.recipient for row in rows] == [email]

        registry = FakeRegistry()
        await NotificationDispatcher(committed_session, registry).dispatch()
        message = registry.email.sent[0]
        assert "в работе" in message.subject
        assert "в работе" in message.text

    async def test_повтор_того_же_статуса_не_шлёт_второе_письмо(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        verified_customer_request,
        admin: dict[str, str],
    ) -> None:
        request_id, _ = verified_customer_request
        url = f"/api/v1/admin/requests/{request_id}/status"

        await api.patch(url, json={"status": "IN_PROGRESS"}, headers=admin)
        await api.patch(url, json={"status": "IN_PROGRESS"}, headers=admin)

        rows = await outbox_rows(committed_session, NotificationEvent.REQUEST_STATUS_CHANGED)
        assert len(rows) == 1

    async def test_видимый_комментарий_шлёт_письмо(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        verified_customer_request,
        admin: dict[str, str],
    ) -> None:
        request_id, email = verified_customer_request

        response = await api.post(
            f"/api/v1/admin/requests/{request_id}/comments",
            json={"body": "Счёт отправлен на почту", "visible_to_customer": True},
            headers=admin,
        )
        assert response.status_code == 201

        rows = await outbox_rows(committed_session, NotificationEvent.REQUEST_COMMENT_ADDED)
        assert [row.recipient for row in rows] == [email]

    async def test_внутренний_комментарий_клиенту_не_уходит(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        verified_customer_request,
        admin: dict[str, str],
    ) -> None:
        """Менеджеры пишут туда суммы и договорённости — это не для клиента."""
        request_id, _ = verified_customer_request

        await api.post(
            f"/api/v1/admin/requests/{request_id}/comments",
            json={"body": "Клиент торгуется, можем дать -7%", "visible_to_customer": False},
            headers=admin,
        )

        assert await outbox_rows(committed_session, NotificationEvent.REQUEST_COMMENT_ADDED) == []

    async def test_текст_комментария_в_письмо_не_копируется(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        verified_customer_request,
        admin: dict[str, str],
    ) -> None:
        """Почтовый ящик — не место для переписки по сделке."""
        request_id, _ = verified_customer_request
        secret_text = "Договорились по 2900 за метр"

        await api.post(
            f"/api/v1/admin/requests/{request_id}/comments",
            json={"body": secret_text, "visible_to_customer": True},
            headers=admin,
        )
        registry = FakeRegistry()
        await NotificationDispatcher(committed_session, registry).dispatch()

        message = registry.email.sent[0]
        assert secret_text not in message.text
        assert secret_text not in (message.html or "")

    async def test_неподтверждённому_адресу_письма_не_уходят(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        unverified_customer_request,
        admin: dict[str, str],
    ) -> None:
        """Адрес не доказан — рассылать по нему нельзя."""
        request_id = unverified_customer_request

        await api.patch(
            f"/api/v1/admin/requests/{request_id}/status",
            json={"status": "IN_PROGRESS"},
            headers=admin,
        )

        assert await outbox_rows(committed_session, NotificationEvent.REQUEST_STATUS_CHANGED) == []

    async def test_анонимной_заявке_письма_не_шлются(
        self,
        api: AsyncClient,
        committed_session: AsyncSession,
        catalog: CatalogFixture,
        admin: dict[str, str],
    ) -> None:
        created = await api.post(
            PUBLIC_REQUESTS, json=request_payload(catalog, [{"sku": "KAN-16-PP", "quantity": "10"}])
        )
        assert created.status_code == 201
        request_id = (await committed_session.execute(select(Request.id))).scalars().first()

        await api.patch(
            f"/api/v1/admin/requests/{request_id}/status",
            json={"status": "IN_PROGRESS"},
            headers=admin,
        )

        assert await outbox_rows(committed_session, NotificationEvent.REQUEST_STATUS_CHANGED) == []


class TestAccountEmails:
    """Письма аутентификации кабинета (этап 7) подключены к outbox."""

    async def test_отправитель_кабинета_кладёт_письмо_в_outbox(
        self, committed_session: AsyncSession, notification_queue: FakeNotificationQueue
    ) -> None:
        """Тот же интерфейс этапа 7, новая реализация — через outbox."""
        from app.modules.customers.mailer import OutboxAccountMailer

        mailer = OutboxAccountMailer(committed_session, notification_queue)
        await mailer.send_email_verification(email="buyer@example.kz", token="secret-token")

        rows = await outbox_rows(committed_session, NotificationEvent.CUSTOMER_EMAIL_VERIFICATION)
        assert [row.recipient for row in rows] == ["buyer@example.kz"]
        assert "/account/verify-email?token=secret-token" in rows[0].payload["link"]
        # Воркер разбужен после коммита записи.
        assert notification_queue.woken == [rows[0].id]

    async def test_сброс_пароля_кладёт_письмо_в_outbox(
        self, committed_session: AsyncSession, notification_queue: FakeNotificationQueue
    ) -> None:
        from app.modules.customers.mailer import OutboxAccountMailer

        await OutboxAccountMailer(committed_session, notification_queue).send_password_reset(
            email="buyer@example.kz", token="reset-token"
        )

        rows = await outbox_rows(committed_session, NotificationEvent.CUSTOMER_PASSWORD_RESET)
        assert "/account/reset-password?token=reset-token" in rows[0].payload["link"]

    async def test_зависимость_отдаёт_отправитель_через_outbox(
        self, committed_session: AsyncSession, notification_queue: FakeNotificationQueue
    ) -> None:
        """Проводка: по умолчанию письма идут в очередь, а не в никуда."""
        from app.modules.customers.mailer import OutboxAccountMailer, get_account_mailer

        mailer = get_account_mailer(committed_session, notification_queue)

        assert isinstance(mailer, OutboxAccountMailer)

    async def test_письмо_подтверждения_ведёт_на_настроенный_адрес_витрины(
        self, committed_session: AsyncSession
    ) -> None:
        from app.core.config import settings
        from app.modules.notifications.events import NotificationEvents

        events = NotificationEvents(committed_session)
        events.email_verification(
            email="a@b.kz", link=f"{settings.PUBLIC_SITE_URL}/account/verify-email?token=abc"
        )
        await committed_session.commit()
        registry = FakeRegistry()

        await NotificationDispatcher(committed_session, registry).dispatch()

        message = registry.email.sent[0]
        assert settings.PUBLIC_SITE_URL in message.text
        assert "Подтвердите email" in message.subject

    async def test_письмо_сброса_пароля_собирается(self, committed_session: AsyncSession) -> None:
        from app.modules.notifications.events import NotificationEvents

        events = NotificationEvents(committed_session)
        events.password_reset(email="a@b.kz", link="https://site.test/account/reset?token=xyz")
        await committed_session.commit()
        registry = FakeRegistry()

        await NotificationDispatcher(committed_session, registry).dispatch()

        message = registry.email.sent[0]
        assert "Восстановление пароля" in message.subject
        assert "https://site.test/account/reset?token=xyz" in message.text
        assert message.html and "Задать новый пароль" in message.html

    async def test_повторная_отправка_ссылки_не_подавляется(
        self, committed_session: AsyncSession
    ) -> None:
        """«Отправить ещё раз» — осознанное действие: дедупликации быть не должно."""
        from app.modules.notifications.events import NotificationEvents

        events = NotificationEvents(committed_session)
        events.email_verification(email="a@b.kz", link="https://site.test/1")
        events.email_verification(email="a@b.kz", link="https://site.test/2")
        await committed_session.commit()

        rows = await outbox_rows(committed_session, NotificationEvent.CUSTOMER_EMAIL_VERIFICATION)
        assert len(rows) == 2
