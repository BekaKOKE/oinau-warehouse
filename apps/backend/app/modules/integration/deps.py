"""Зависимости интеграционного API: ключ, IP, размер тела, частота.

Порядок проверок важен и выбран так, чтобы дешёвое отсекалось первым
и чтобы ответ не подсказывал атакующему, что именно не так:

1. Выключатель обмена — 503 даже с верным ключом.
2. IP-allowlist — 401, неотличимый от неизвестного ключа.
3. Ключ — 401.
4. Scope — 403 (ключ уже доказан, скрывать нечего).

Ключ ищется в заголовке `X-API-Key`, а не в Authorization: Bearer там
уже занят JWT сотрудника, и смешивать две разные схемы в одном
заголовке — верный способ однажды принять токен не того субъекта.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select

from app.api.deps import RateLimiterDep, SessionDep, get_client_ip
from app.core.config import settings
from app.core.exceptions import RateLimitError
from app.core.logging import get_logger
from app.modules.integration.exceptions import (
    IntegrationAuthError,
    IntegrationDisabledError,
    IntegrationIpDeniedError,
    IntegrationScopeError,
    PayloadTooLargeError,
)
from app.modules.integration.models import ApiKey
from app.modules.integration.security import hash_api_key

logger = get_logger(__name__)

API_KEY_HEADER = "X-API-Key"

ApiKeyHeader = Annotated[
    str | None,
    Header(alias=API_KEY_HEADER, max_length=128, description="Ключ интеграции"),
]


def _ip_allowed(request: Request) -> bool:
    """Пустой список = проверка выключена (только для local и CI).

    Сравнение по точному адресу, без масок: подсети здесь не нужны,
    а неверно понятая маска — это открытый наружу эндпоинт записи.
    """
    allowlist = settings.INTEGRATION_IP_ALLOWLIST
    if not allowlist:
        return True
    return get_client_ip(request) in allowlist


async def get_api_key(
    request: Request,
    session: SessionDep,
    api_key: ApiKeyHeader = None,
) -> ApiKey:
    """Проверенный ключ интеграции."""
    if not settings.ONE_C_INTEGRATION_ENABLED:
        raise IntegrationDisabledError

    if not _ip_allowed(request):
        # В журнале только факт: адрес и так есть в логе доступа,
        # а ключ не пишется никогда, даже неверный.
        logger.warning("integration_ip_denied", path=request.url.path)
        raise IntegrationIpDeniedError

    if not api_key:
        raise IntegrationAuthError

    stored = (
        await session.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(api_key)))
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    if stored is None or not stored.is_active:
        logger.warning("integration_key_rejected", path=request.url.path)
        raise IntegrationAuthError
    if stored.expires_at is not None and stored.expires_at <= now:
        logger.warning("integration_key_expired", key=stored.key_prefix)
        raise IntegrationAuthError

    # Отметка использования — полезная операционная информация
    # («ключ жив, обмен идёт»), коммитит её сервис вместе с обменом.
    stored.last_used_at = now
    return stored


ApiKeyDep = Annotated[ApiKey, Depends(get_api_key)]


def require_scope(scope: str) -> Callable[[ApiKey], ApiKey]:
    """Ключ обязан нести нужный scope."""

    def dependency(key: ApiKeyDep) -> ApiKey:
        if not key.has_scope(scope):
            logger.warning("integration_scope_denied", key=key.key_prefix, scope=scope)
            raise IntegrationScopeError(details={"required_scope": scope})
        return key

    return dependency


async def guard_body_size(request: Request) -> None:
    """Потолок размера тела по Content-Length.

    Проверка до чтения тела: разбирать десятимегабайтный JSON, чтобы
    затем его отвергнуть, — это и есть способ положить приложение.
    """
    raw_length = request.headers.get("content-length")
    if raw_length is None:
        return
    try:
        length = int(raw_length)
    except ValueError:
        return
    if length > settings.INTEGRATION_MAX_BODY_BYTES:
        raise PayloadTooLargeError(
            details={"limit_bytes": settings.INTEGRATION_MAX_BODY_BYTES, "size_bytes": length}
        )


async def integration_rate_limit(request: Request, key: ApiKeyDep, limiter: RateLimiterDep) -> None:
    """Норма частоты на ключ, а не на IP.

    1С обычно стоит за общим корпоративным NAT: лимит по адресу
    ограничивал бы весь офис, а не сорвавшуюся обработку.
    """
    allowed, _ = await limiter.hit(f"integration:{key.key_prefix}", settings.RATE_LIMIT_INTEGRATION)
    if not allowed:
        logger.warning("integration_rate_limited", key=key.key_prefix, path=request.url.path)
        raise RateLimitError
