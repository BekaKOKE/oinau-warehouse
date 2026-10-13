"""Постановка задач в очередь из приложения."""

from __future__ import annotations

from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings

_pool: ArqRedis | None = None


async def get_queue() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(
            RedisSettings(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                database=settings.REDIS_DB,
            )
        )
    return _pool


async def enqueue(task_name: str, *args: Any, **kwargs: Any) -> None:
    queue = await get_queue()
    await queue.enqueue_job(task_name, *args, **kwargs)
