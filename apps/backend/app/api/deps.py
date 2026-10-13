"""Зависимости FastAPI.

Здесь собрано всё, что эндпоинты получают через Depends: сессия БД,
контекст запроса, текущий пользователь и проверка прав.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError, RateLimitError
from app.core.logging import request_id_ctx
from app.core.rate_limit import RateLimiter
from app.core.security import JWT_CUSTOMER_AUDIENCE, decode_access_token, hash_ip
from app.db.redis import get_redis
from app.db.session import get_session
from app.modules.customers.models import Customer
from app.modules.customers.repository import CustomerRepository
from app.modules.customers.service_auth import password_version
from app.modules.users.enums import UserRole
from app.modules.users.models import User
from app.modules.users.permissions import ROLE_PERMISSIONS
from app.modules.users.repository import UserRepository
from app.modules.users.service import RequestContext

# auto_error=False: при отсутствии заголовка мы хотим вернуть собственный
# формат ошибки, а не стандартный ответ Starlette.
bearer_scheme = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_client_ip(request: Request) -> str | None:
    """IP клиента с учётом доверенных обратных прокси.

    Заголовок X-Forwarded-For учитывается, только если задан
    TRUSTED_PROXY_HOPS > 0. Берётся не первый адрес слева (его пишет
    сам клиент и подделывает как угодно), а тот, что стоит перед
    записями наших собственных прокси: каждый прокси дописывает адрес
    своего peer-а в конец цепочки, поэтому при одном nginx настоящий
    клиент — последняя запись.
    """
    hops = settings.TRUSTED_PROXY_HOPS
    if hops > 0:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            chain = [part.strip() for part in forwarded.split(",") if part.strip()]
            if chain:
                return chain[max(len(chain) - hops, 0)]
    return request.client.host if request.client else None


def get_request_context(request: Request) -> RequestContext:
    return RequestContext(
        ip_hash=hash_ip(get_client_ip(request)),
        user_agent=(request.headers.get("User-Agent") or "")[:255] or None,
        request_id=request_id_ctx.get(),
    )


ContextDep = Annotated[RequestContext, Depends(get_request_context)]


def get_rate_limiter(redis: Annotated[Redis, Depends(get_redis)]) -> RateLimiter:
    return RateLimiter(redis)


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def rate_limit(scope: str, rate_setting: str) -> Callable[..., Awaitable[None]]:
    """Ограничение частоты по IP для конкретного эндпоинта.

    Норма читается из настроек в момент запроса, а не при импорте:
    иначе значение из .env фиксировалось бы в коде на этапе загрузки
    модуля и не поддавалось бы изменению без пересборки.
    """

    async def dependency(
        request: Request,
        limiter: RateLimiterDep,
    ) -> None:
        rate: str = getattr(settings, rate_setting)
        allowed, _ = await limiter.hit(f"{scope}:{get_client_ip(request)}", rate)
        if not allowed:
            raise RateLimitError

    return dependency


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Текущий пользователь по access-токену.

    Пользователь загружается из БД при каждом запросе, а не берётся
    целиком из токена. Это один индексный запрос, зато отключение
    сотрудника, смена роли или мягкое удаление действуют немедленно,
    а не через 15 минут. Для админки с десятками запросов в минуту
    цена нулевая, а безопасность заметно выше.
    """
    if credentials is None or not credentials.credentials:
        raise AuthenticationError

    try:
        payload = decode_access_token(credentials.credentials)
        subject = uuid.UUID(payload["sub"])
        issued_at = datetime.fromtimestamp(payload["iat"], tz=UTC)
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        # Причина не раскрывается: "истёк" и "подделан" для клиента
        # выглядят одинаково.
        raise AuthenticationError from exc

    user = await UserRepository(session).get_by_uuid(subject)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise AuthenticationError

    # Смена пароля обесценивает выданные ранее access-токены немедленно,
    # а не через 15 минут. Refresh-токены отзываются отдельно, в сервисе.
    if user.password_changed_at is not None and issued_at < user.password_changed_at:
        raise AuthenticationError

    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_current_customer(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Customer:
    """Текущий клиент B2B-кабинета.

    Токен проверяется с аудиторией кабинета: токен сотрудника сюда
    не пройдёт, а токен клиента не пройдёт в админку (`get_current_user`
    ждёт аудиторию админки). Клиент загружается из БД на каждый запрос —
    отключение, удаление и сброс пароля действуют сразу.
    """
    if credentials is None or not credentials.credentials:
        raise AuthenticationError

    try:
        payload = decode_access_token(credentials.credentials, audience=JWT_CUSTOMER_AUDIENCE)
        subject = uuid.UUID(payload["sub"])
        token_password_version = int(payload["pwv"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise AuthenticationError from exc

    customer = await CustomerRepository(session).get_by_uuid(subject)
    if (
        customer is None
        or not customer.is_active
        or customer.deleted_at is not None
        or customer.email_verified_at is None
    ):
        raise AuthenticationError

    # Сброс пароля меняет версию: все выданные ранее access-токены
    # перестают приниматься немедленно, а не через 15 минут.
    if token_password_version != password_version(customer):
        raise AuthenticationError

    return customer


CurrentCustomerDep = Annotated[Customer, Depends(get_current_customer)]


def get_permissions(user: User) -> frozenset[str]:
    try:
        role = UserRole(user.role)
    except ValueError:
        # Роль из БД не входит в перечисление — считаем, что прав нет.
        # Такое возможно только при ручной правке базы.
        return frozenset()
    return ROLE_PERMISSIONS.get(role, frozenset())


def require_permissions(*required: str) -> Callable[[User], User]:
    """Проверка прав, а не роли.

    В эндпоинтах пишется require_permissions("catalog.write"), а не
    сравнение с ролью. Благодаря этому состав прав роли можно изменить
    в одном месте, не трогая ни одного роутера.
    """

    def dependency(user: CurrentUserDep) -> User:
        granted = get_permissions(user)
        if not set(required).issubset(granted):
            raise PermissionDeniedError(
                "Недостаточно прав для выполнения операции",
                details={"required": sorted(required)},
            )
        return user

    return dependency
