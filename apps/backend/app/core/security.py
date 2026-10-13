"""Криптографический слой: пароли и токены.

Единственное место в проекте, где выполняются операции с секретами.
Ни сервисы, ни роутеры не работают с хешами и подписями напрямую.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type

from app.core.config import settings

TokenType = Literal["access"]

JWT_ISSUER = "oinau-pro"
JWT_AUDIENCE = "oinau-admin"
# Клиенты B2B-кабинета получают токены с другой аудиторией. Проверка `aud`
# при разборе делает токены взаимно непригодными: токен клиента не пройдёт
# в админку, токен сотрудника — в кабинет, даже при общем SECRET_KEY.
JWT_CUSTOMER_AUDIENCE = "oinau-customer"

# Параметры argon2id. Значения выше дефолтных argon2-cffi по времени,
# но осознанно: вход в админку происходит редко, а ~100 мс на проверку
# делают перебор украденной базы непрактичным.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 МБ
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,  # argon2id: устойчив и к GPU, и к side-channel атакам
)

# Хеш заведомо несуществующего пароля. Нужен, чтобы проверка пароля
# несуществующего пользователя занимала столько же времени, сколько
# проверка существующего: иначе по времени ответа можно перебрать,
# какие email заведены в системе.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-equalization")


# ---------------------------------------------------------------- пароли
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Проверка пароля с защитой от перебора email по времени ответа."""
    target = password_hash or _DUMMY_HASH
    try:
        _hasher.verify(target, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return password_hash is not None


def password_needs_rehash(password_hash: str) -> bool:
    """True, если хеш создан со старыми параметрами.

    Позволяет незаметно усилить параметры argon2 в будущем: при первом
    успешном входе хеш будет перезаписан новыми.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# ------------------------------------------------------------ access token
def create_access_token(
    *,
    subject: uuid.UUID,
    role: str,
    expires_in: timedelta | None = None,
    audience: str = JWT_AUDIENCE,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, int]:
    """Возвращает (токен, срок жизни в секундах).

    Права в токен НЕ кладутся: они выводятся из роли при каждом запросе.
    Иначе изменение состава прав роли не подействовало бы на уже выданные
    токены, и понижение доступа откладывалось бы до их истечения.
    """
    lifetime = expires_in or timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": "access",
        "role": role,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime,
        "iss": JWT_ISSUER,
        "aud": audience,
        **(extra_claims or {}),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str, *, audience: str = JWT_AUDIENCE) -> dict[str, Any]:
    """Разбирает и проверяет access-токен.

    Бросает jwt.PyJWTError при любой проблеме: истёк, подделан, чужой
    издатель, не тот тип. Вызывающий код не должен различать причины —
    наружу уходит одинаковый 401, иначе сообщение об ошибке становится
    подсказкой атакующему.
    """
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],  # список фиксирован: защита от alg=none
        audience=audience,
        issuer=JWT_ISSUER,
        options={"require": ["exp", "iat", "sub", "typ"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("unexpected token type")
    return payload


# ----------------------------------------------------------- refresh token
def generate_refresh_token() -> str:
    """Непрозрачный случайный токен.

    JWT здесь не нужен и вреден: refresh-токен должен быть отзываемым,
    а самодостаточный JWT отозвать нельзя без списка отзыва — то есть
    без того же обращения к БД, только с лишней криптографией.
    """
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """SHA-256 от токена.

    В БД хранится только хеш: утечка дампа не даёт войти в админку.
    Argon2 здесь избыточен — токен и так содержит 384 бита энтропии,
    перебирать его бессмысленно, а быстрый хеш нужен для поиска по индексу.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def generate_action_token() -> str:
    """Одноразовый токен подтверждения email или сброса пароля.

    Та же энтропия, что у refresh-токена; в БД — только SHA-256
    (`hash_refresh_token`), сам токен уходит клиенту в ссылке.
    """
    return secrets.token_urlsafe(32)


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def hash_ip(ip: str | None) -> str | None:
    """Хеш IP для антиспама и аудита.

    Сырые адреса — персональные данные. Для сравнения "тот же клиент"
    хеша достаточно. Соль — SECRET_KEY, чтобы хеш нельзя было
    сопоставить с таблицей всех IPv4.
    """
    if not ip:
        return None
    return hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest()
