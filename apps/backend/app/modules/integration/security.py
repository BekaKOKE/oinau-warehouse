"""Аутентификация внешних систем по API-ключу.

Ключ — не JWT и не сессия: у внешней системы нет входа, срока сессии
и ротации refresh-токена. Ключ живёт до отзыва, проверяется по таблице
`api_keys` и ограничен списком scope.

В базе хранится только SHA-256 ключа. Быстрый хеш здесь уместен ровно
по той же причине, что и у refresh-токенов: ключ содержит 256+ бит
энтропии, перебирать его бессмысленно, а argon2 на каждом запросе
обмена превратил бы выгрузку остатков в нагрузочный тест.
"""

from __future__ import annotations

import hashlib
import secrets

from app.modules.integration.models import KEY_PREFIX_LENGTH

# Осмысленный префикс: в журнале сразу видно, что это ключ OINAU,
# а не случайная строка из чужого сервиса.
KEY_PREFIX = "oik_"
# 32 байта случайности → 43 символа base64url.
KEY_ENTROPY_BYTES = 32


class IntegrationScope:
    """Что ключу разрешено.

    Разделение по сущностям, а не «полный доступ»: обмен остатками
    идёт каждые несколько минут и не должен иметь права переписывать
    каталог, если однажды сломается обработка на стороне 1С.
    """

    CATALOG_WRITE = "catalog:write"
    PRICING_WRITE = "pricing:write"
    INVENTORY_WRITE = "inventory:write"
    REQUESTS_READ = "requests:read"

    ALL = frozenset({CATALOG_WRITE, PRICING_WRITE, INVENTORY_WRITE, REQUESTS_READ})


def generate_api_key() -> str:
    """Новый ключ. Показывается один раз — в базе остаётся только хеш."""
    return f"{KEY_PREFIX}{secrets.token_urlsafe(KEY_ENTROPY_BYTES)}"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def key_prefix(key: str) -> str:
    """Видимая часть для опознания ключа без его раскрытия."""
    return key[:KEY_PREFIX_LENGTH]
