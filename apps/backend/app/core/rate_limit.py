"""Ограничение частоты запросов на Redis.

Скользящее окно на сортированном множестве. Точнее фиксированного окна:
фиксированное позволяет сделать двойную норму на стыке двух окон, что
для формы входа означает вдвое больше попыток подбора пароля.

Вся последовательность выполняется Lua-скриптом на стороне Redis.

Прежняя реализация на pipeline с transaction=True тоже исполнялась
атомарно (MULTI/EXEC), то есть чужие команды между шагами не
вклинивались. Проблема была не в этом: внутри MULTI нельзя прочитать
результат предыдущей команды, поэтому решение "пускать или нет"
неизбежно принималось уже ПОСЛЕ добавления записи. Отклонённые попытки
попадали в окно наравне с успешными, и непрерывный перебор сам себе
продлевал блокировку, а размер ключа рос вместе с интенсивностью атаки.

Lua снимает это ограничение: проверка и запись оказываются в одном
атомарном блоке, и отклонённая попытка не сохраняется.
"""

from __future__ import annotations

import time
import uuid
from typing import cast

from redis.asyncio import Redis
from redis.commands.core import AsyncScript

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def parse_rate(rate: str) -> tuple[int, int]:
    """'10/minute' -> (10, 60)."""
    limit_str, _, period_str = rate.partition("/")
    periods = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
    if period_str not in periods:
        raise ValueError(f"Неизвестный период ограничения: {rate}")
    return int(limit_str), periods[period_str]


# KEYS[1] — ключ окна
# ARGV: 1 — текущее время (сек, дробное), 2 — длина окна, 3 — лимит,
#       4 — уникальный идентификатор попытки
#
# Время передаётся клиентом, а не берётся через redis.call('TIME'):
# скрипт обязан быть детерминированным, иначе Redis не сможет корректно
# реплицировать его эффект.
#
# Отклонённая попытка НЕ записывается в множество. Иначе непрерывный
# перебор сам себе продлевал бы окно и бесконечно наращивал размер ключа.
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local used = redis.call('ZCARD', key)

if used >= limit then
  redis.call('PEXPIRE', key, math.ceil(window * 1000))
  return {0, 0}
end

redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, math.ceil(window * 1000))
return {1, limit - used - 1}
"""


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        # register_script кеширует SHA и использует EVALSHA, пересылая
        # тело скрипта только при первом вызове или после FLUSHALL.
        self._script: AsyncScript = redis.register_script(_SLIDING_WINDOW_LUA)

    async def hit(self, key: str, rate: str) -> tuple[bool, int]:
        """Регистрирует попытку. Возвращает (разрешено, осталось попыток).

        При недоступности Redis запрос ПРОПУСКАЕТСЯ (fail-open).
        Обратное решение означало бы, что падение кэша роняет вход
        в админку и приём заявок — лечение хуже болезни. Событие
        логируется, чтобы недоступность не осталась незамеченной.
        """
        if not settings.RATE_LIMIT_ENABLED:
            return True, -1

        limit, period = parse_rate(rate)

        try:
            result = await self._script(
                keys=[f"rl:{key}"],
                args=[time.time(), period, limit, uuid.uuid4().hex],
            )
        except Exception as exc:
            logger.warning("rate_limit_unavailable", key=key, error=type(exc).__name__)
            return True, -1

        allowed, remaining = cast("list[int]", result)
        return bool(allowed), int(remaining)

    async def reset(self, key: str) -> None:
        """Сбрасывает счётчик — например, после успешного входа."""
        try:
            await self.redis.delete(f"rl:{key}")
        except Exception as exc:
            logger.warning("rate_limit_reset_failed", key=key, error=type(exc).__name__)
