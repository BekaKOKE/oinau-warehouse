"""Письма клиентского кабинета: подтверждение email и сброс пароля.

Интерфейс тот же, что был заложен на этапе 7: сервис аутентификации
вызывает `send_email_verification` / `send_password_reset` и ничего не
знает ни про SMTP, ни про очередь. Изменилась только реализация по
умолчанию — теперь она кладёт письмо в notification_outbox, откуда его
забирает воркер. Второй системы аутентификации не появилось: токены
по-прежнему выпускает `CustomerAuthService`.

Ссылки собираются здесь, а не в сервисе: формат URL — забота канала
доставки, а не правил аутентификации.

Сам токен НИКОГДА не логируется. При ENV=local в журнал пишется ссылка
целиком — это единственный способ пройти сценарий без почтового
сервера; на staging и production пишется только факт события.
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlencode

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_session
from app.modules.notifications.events import NotificationEvents
from app.modules.notifications.queue import (
    NotificationQueue,
    NullNotificationQueue,
    get_notification_queue,
    wake_worker,
)

logger = get_logger(__name__)


class AccountMailer(Protocol):
    async def send_email_verification(self, *, email: str, token: str) -> None: ...

    async def send_password_reset(self, *, email: str, token: str) -> None: ...


def verification_link(token: str) -> str:
    return f"{settings.PUBLIC_SITE_URL}/account/verify-email?{urlencode({'token': token})}"


def password_reset_link(token: str) -> str:
    return f"{settings.PUBLIC_SITE_URL}/account/reset-password?{urlencode({'token': token})}"


class OutboxAccountMailer:
    """Кладёт письмо в outbox и будит воркера.

    Вызывается ПОСЛЕ коммита выпуска токена — так было и раньше, чтобы
    транзакция не ждала внешнюю систему. Теперь «внешняя система» — это
    строка в своей же базе, поэтому запись надёжна: потерять её можно
    только вместе с самим токеном.
    """

    def __init__(self, session: AsyncSession, delivery: NotificationQueue | None = None) -> None:
        self._session = session
        self._delivery = delivery or NullNotificationQueue()

    async def send_email_verification(self, *, email: str, token: str) -> None:
        await self._queue(
            "customer_email_verification_queued",
            verification_link(token),
            lambda events, link: events.email_verification(email=email, link=link),
        )

    async def send_password_reset(self, *, email: str, token: str) -> None:
        await self._queue(
            "customer_password_reset_queued",
            password_reset_link(token),
            lambda events, link: events.password_reset(email=email, link=link),
        )

    async def _queue(self, event_name: str, link: str, build) -> None:  # type: ignore[no-untyped-def]
        events = NotificationEvents(self._session)
        entries = build(events, link)
        outbox_ids = await events.outbox.identify(entries)
        await self._session.commit()
        await wake_worker(self._delivery, outbox_ids)
        # Ссылка содержит одноразовый токен: в журнал она попадает
        # только локально, где почтового сервера может не быть вовсе.
        if settings.ENV == "local":
            logger.info(event_name, link=link)
        else:
            logger.info(event_name)


class PendingAccountMailer:
    """Отправитель-заглушка: ничего не ставит в очередь.

    Остаётся для сценариев, где сессии нет вовсе (скрипты, отладка).
    """

    async def send_email_verification(self, *, email: str, token: str) -> None:
        self._log("customer_email_verification_pending", verification_link(token))

    async def send_password_reset(self, *, email: str, token: str) -> None:
        self._log("customer_password_reset_pending", password_reset_link(token))

    def _log(self, event: str, link: str) -> None:
        if settings.ENV == "local":
            logger.info(event, link=link)
        else:
            logger.info(event)


def get_account_mailer(
    session: AsyncSession = Depends(get_session),
    delivery: NotificationQueue = Depends(get_notification_queue),
) -> AccountMailer:
    """Зависимость FastAPI; тесты подменяют её через dependency_overrides."""
    return OutboxAccountMailer(session, delivery)
