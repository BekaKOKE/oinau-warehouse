"""Задачи воркера: доставка уведомлений из outbox.

Две точки входа с разным назначением.

`deliver_notification` — быстрый путь: приложение разбудило воркер
сразу после коммита события, и письмо уходит за секунды.

`sweep_notifications` — страховка по расписанию. Она подбирает всё,
что быстрый путь потерял: недоступный при постановке Redis, убитый
воркер, событие, ждущее повтора после отказа провайдера. Без неё
outbox был бы таблицей, в которую пишут, но из которой не читают.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.modules.notifications.dispatcher import NotificationDispatcher

logger = get_logger(__name__)


async def deliver_notification(_ctx: dict[str, Any], outbox_id: int) -> dict[str, int]:
    """Доставка одного события."""
    async with SessionFactory() as session:
        result = await NotificationDispatcher(session).dispatch(outbox_id)
    logger.info("notification_task_done", outbox_id=outbox_id, **result)
    return result


async def sweep_notifications(_ctx: dict[str, Any]) -> dict[str, int]:
    """Периодический проход по всем готовым к отправке записям."""
    async with SessionFactory() as session:
        result = await NotificationDispatcher(session).dispatch()
    if any(result.values()):
        logger.info("notification_sweep_done", **result)
    return result
