"""Чтение и запись журнала обменов."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.repository import BaseRepository
from app.modules.notifications.models import SyncLog

# Сколько живёт защита от повторного пакета. Дольше держать вредно:
# «те же остатки через неделю» — это новая правда, а не дубль.
DUPLICATE_WINDOW = timedelta(hours=6)


class SyncLogRepository(BaseRepository[SyncLog]):
    model = SyncLog

    def record(self, **fields: Any) -> SyncLog:
        """Новая запись журнала. Имя не `add`: у базового репозитория
        оно занято под «добавить готовую сущность»."""
        entry = SyncLog(**fields)
        self.session.add(entry)
        return entry

    async def find_successful(self, entity: str, payload_hash: str) -> SyncLog | None:
        """Недавний успешный обмен с тем же содержимым пакета.

        Только success: частично применённый пакет обязан примениться
        ещё раз, иначе отбракованные строки никогда не догонят.
        """
        since = datetime.now(UTC) - DUPLICATE_WINDOW
        query = (
            select(SyncLog)
            .where(
                SyncLog.entity == entity,
                SyncLog.payload_hash == payload_hash,
                SyncLog.status == "success",
                SyncLog.created_at >= since,
            )
            .order_by(SyncLog.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(query)).scalar_one_or_none()

    async def last_by_entity(self) -> list[SyncLog]:
        """Последний обмен по каждой сущности — для статуса в админке."""
        rows = (
            await self.session.execute(
                select(SyncLog).order_by(SyncLog.created_at.desc()).limit(50)
            )
        ).scalars()
        seen: dict[str, SyncLog] = {}
        for entry in rows:
            seen.setdefault(entry.entity, entry)
        return list(seen.values())

    async def last_failure(self) -> SyncLog | None:
        query = (
            select(SyncLog)
            .where(SyncLog.status.in_(["partial", "failed"]))
            .order_by(SyncLog.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(query)).scalar_one_or_none()
