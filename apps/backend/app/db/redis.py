"""Подключение к Redis: очереди задач, rate limiting, кэш."""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from app.core.config import settings

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = from_url(  # type: ignore[no-untyped-call]
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
