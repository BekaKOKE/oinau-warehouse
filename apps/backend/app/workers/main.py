"""ARQ-воркер.

Отдельный процесс: уведомления, обработка изображений, импорты.
Ничего необратимого не выполняется в HTTP-обработчике — только через очередь.
"""

from __future__ import annotations

from typing import Any, ClassVar, cast

from arq import cron, func
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.workers.tasks.imports import (
    apply_catalog_bundle,
    check_catalog_bundle,
    cleanup_catalog_bundles,
)
from app.workers.tasks.media import process_media
from app.workers.tasks.notifications import deliver_notification, sweep_notifications

logger = get_logger(__name__)

BUNDLE_JOB_TIMEOUT = 3600


async def ping(_ctx: dict[str, Any]) -> str:
    """Тестовая задача: подтверждает, что очередь работает end-to-end."""
    logger.info("worker_ping")
    return "pong"


async def startup(_ctx: dict[str, Any]) -> None:
    configure_logging()
    logger.info("worker_startup", env=settings.ENV)


async def shutdown(_ctx: dict[str, Any]) -> None:
    logger.info("worker_shutdown")


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        ping,
        process_media,
        deliver_notification,
        sweep_notifications,
        # Архив с сотнями фотографий проверяется и применяется минутами:
        # общий job_timeout (5 минут) для этих задач мал.
        func(cast("Any", check_catalog_bundle), timeout=BUNDLE_JOB_TIMEOUT),
        func(cast("Any", apply_catalog_bundle), timeout=BUNDLE_JOB_TIMEOUT),
        cleanup_catalog_bundles,
    ]
    # Страховка для outbox: приложение будит воркер сразу после коммита,
    # но событие не должно зависеть от доступности Redis в тот момент.
    # Раз в минуту проход подбирает всё пропущенное и всё, что ждёт повтора.
    # arq объявляет WorkerCoroutine как Protocol с атрибутами, которых
    # у обычной корутины нет, поэтому здесь нужен явный cast.
    cron_jobs: ClassVar[list[Any]] = [
        cron(cast("Any", sweep_notifications), second=0, run_at_startup=True),
        # Просроченные архивы импорта не должны копиться в хранилище.
        cron(cast("Any", cleanup_catalog_bundles), minute=17, second=0),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        database=settings.REDIS_DB,
    )
    max_jobs = 10
    job_timeout = 300
    keep_result = 3600
    # Воркер раз в 30 секунд обновляет ключ здоровья в Redis, а
    # `arq --check app.workers.main.WorkerSettings` его читает — на этом
    # построен HEALTHCHECK контейнера. Значение по умолчанию (час)
    # означало бы, что зависший воркер час считается живым.
    health_check_interval = 30
    # Осталось на будущее: уборка "осиротевших" media_files в статусе pending.
