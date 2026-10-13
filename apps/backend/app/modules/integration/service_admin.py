"""Сбор состояния интеграций для админки.

Читает настройки и две таблицы. Ничего не меняет и ничего не
отправляет: это страница «что сейчас происходит», а не пульт.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.config import settings
from app.core.service import BaseService
from app.infrastructure.notifications.email import EMAIL_CHANNEL
from app.infrastructure.notifications.telegram import TELEGRAM_CHANNEL
from app.modules.integration.models import ApiKey
from app.modules.integration.repository import SyncLogRepository
from app.modules.integration.schemas_admin import (
    ChannelStatus,
    IntegrationStatus,
    OutboxCounters,
    SyncSummary,
)
from app.modules.notifications.enums import OutboxStatus
from app.modules.notifications.models import NotificationOutbox, SyncLog


class IntegrationStatusService(BaseService):
    async def get_status(self) -> IntegrationStatus:
        sync_log = SyncLogRepository(self.session)
        last = await sync_log.last_by_entity()
        failure = await sync_log.last_failure()
        return IntegrationStatus(
            channels=[self._telegram(), self._email()],
            outbox=await self._outbox(),
            one_c_enabled=settings.ONE_C_INTEGRATION_ENABLED,
            api_keys_active=await self._active_keys(),
            last_syncs=[self._to_summary(entry) for entry in last],
            last_failure=self._to_summary(failure) if failure is not None else None,
        )

    # ------------------------------------------------------------- каналы

    @staticmethod
    def _channel(name: str, configured: bool, recipients: int) -> ChannelStatus:
        """Общий рубильник важнее настроек канала — он и показывается первым."""
        if not settings.NOTIFICATIONS_ENABLED:
            return ChannelStatus(
                channel=name, enabled=False, reason="disabled_globally", recipients=recipients
            )
        if not configured:
            return ChannelStatus(
                channel=name, enabled=False, reason="not_configured", recipients=recipients
            )
        if recipients == 0:
            return ChannelStatus(channel=name, enabled=False, reason="no_recipients", recipients=0)
        return ChannelStatus(channel=name, enabled=True, recipients=recipients)

    def _telegram(self) -> ChannelStatus:
        # bool(токен), а не сам токен: значение не покидает настройки.
        return self._channel(
            TELEGRAM_CHANNEL,
            configured=bool(settings.TELEGRAM_BOT_TOKEN),
            recipients=len(settings.TELEGRAM_CHAT_ID),
        )

    def _email(self) -> ChannelStatus:
        return self._channel(
            EMAIL_CHANNEL,
            configured=bool(settings.SMTP_HOST and settings.SMTP_FROM),
            # Письма клиентам уходят и без делового списка, поэтому канал
            # считается настроенным по SMTP, а получатели показываются
            # отдельно — это адресаты уведомлений о новых заявках.
            recipients=len(settings.NOTIFY_EMAILS),
        )

    # -------------------------------------------------------------- данные

    async def _outbox(self) -> OutboxCounters:
        rows = await self.session.execute(
            select(NotificationOutbox.status, func.count()).group_by(NotificationOutbox.status)
        )
        counts: dict[str, int] = dict(rows.all())  # type: ignore[arg-type]
        return OutboxCounters(
            # SENDING считается ожидающим: для человека это «ещё не ушло».
            pending=counts.get(OutboxStatus.PENDING.value, 0)
            + counts.get(OutboxStatus.SENDING.value, 0),
            sent=counts.get(OutboxStatus.SENT.value, 0),
            skipped=counts.get(OutboxStatus.SKIPPED.value, 0),
            failed=counts.get(OutboxStatus.FAILED.value, 0),
        )

    async def _active_keys(self) -> int:
        return (
            await self.session.execute(
                select(func.count()).select_from(ApiKey).where(ApiKey.is_active.is_(True))
            )
        ).scalar_one()

    @staticmethod
    def _to_summary(entry: SyncLog) -> SyncSummary:
        return SyncSummary(
            entity=entry.entity,
            status=entry.status,
            received=entry.received,
            created=entry.created,
            updated=entry.updated,
            skipped=entry.skipped,
            failed=entry.failed,
            duration_ms=entry.duration_ms,
            created_at=entry.created_at,
        )
