"""Схемы состояния интеграций для админки.

Правило одно: наружу уходит только «настроено / не настроено» и итог
последнего обмена. Значений реквизитов — токена бота, пароля SMTP,
ключей интеграции — в этих схемах нет ни одного поля, поэтому
показать их случайно невозможно.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ChannelStatus(BaseModel):
    """Канал уведомлений."""

    channel: str
    # Канал настроен и не выключен общим рубильником.
    enabled: bool
    # Почему выключен, если выключен: "not_configured" | "disabled_globally".
    reason: str | None = None
    # Сколько получателей задано. Не сами адреса: список деловой почты
    # и chat_id — это тоже данные, которых в интерфейсе быть не должно.
    recipients: int = 0


class OutboxCounters(BaseModel):
    """Очередь уведомлений по состояниям."""

    pending: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0


class SyncSummary(BaseModel):
    """Итог одного обмена."""

    entity: str
    status: str
    received: int
    created: int
    updated: int
    skipped: int
    failed: int
    duration_ms: int
    created_at: datetime


class IntegrationStatus(BaseModel):
    channels: list[ChannelStatus]
    outbox: OutboxCounters
    # Обмен с 1С разрешён настройкой ONE_C_INTEGRATION_ENABLED.
    one_c_enabled: bool
    # Сколько активных ключей заведено. Ни самих ключей, ни их хешей.
    api_keys_active: int
    # Последний обмен по каждой сущности и последний неуспешный — вместе
    # они отвечают на вопрос «работает ли обмен и когда он ломался».
    last_syncs: list[SyncSummary]
    last_failure: SyncSummary | None = None
