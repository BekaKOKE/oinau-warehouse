"""Тесты криптографического слоя."""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    JWT_AUDIENCE,
    JWT_ISSUER,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_ip,
    hash_password,
    hash_refresh_token,
    verify_password,
)


# ---------------------------------------------------------------- пароли
def test_password_hash_is_argon2id() -> None:
    hashed = hash_password("correct-horse-battery-staple")
    assert hashed.startswith("$argon2id$")
    assert "correct-horse" not in hashed


def test_same_password_gives_different_hashes() -> None:
    """Соль случайна: одинаковые пароли двух сотрудников неразличимы в дампе."""
    first = hash_password("correct-horse-battery-staple")
    second = hash_password("correct-horse-battery-staple")
    assert first != second
    assert verify_password("correct-horse-battery-staple", first)
    assert verify_password("correct-horse-battery-staple", second)


def test_wrong_password_is_rejected() -> None:
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-stapl", hashed) is False


def test_verify_against_missing_hash_returns_false() -> None:
    """Проверка несуществующего пользователя не падает и возвращает False."""
    assert verify_password("anything", None) is False


def test_verify_timing_is_similar_for_missing_user() -> None:
    """Время ответа не выдаёт, заведён ли такой email.

    Порог намеренно мягкий: тест ловит грубую ошибку (ранний return
    без вычисления хеша), а не микросекундные различия.
    """
    hashed = hash_password("correct-horse-battery-staple")

    started = time.perf_counter()
    verify_password("wrong-password-here", hashed)
    with_user = time.perf_counter() - started

    started = time.perf_counter()
    verify_password("wrong-password-here", None)
    without_user = time.perf_counter() - started

    assert without_user > with_user / 3


# ------------------------------------------------------------ access token
def test_access_token_roundtrip() -> None:
    subject = uuid.uuid4()
    token, expires_in = create_access_token(subject=subject, role="ADMIN")

    payload = decode_access_token(token)
    assert payload["sub"] == str(subject)
    assert payload["role"] == "ADMIN"
    assert payload["typ"] == "access"
    assert expires_in == settings.ACCESS_TOKEN_TTL_MINUTES * 60


def test_access_token_has_no_permissions_inside() -> None:
    """Права выводятся из роли при каждом запросе, а не фиксируются в токене.

    Иначе понижение прав роли не подействовало бы на уже выданные токены.
    """
    token, _ = create_access_token(subject=uuid.uuid4(), role="ADMIN")
    payload = decode_access_token(token)
    assert "permissions" not in payload


def test_expired_token_is_rejected() -> None:
    token, _ = create_access_token(
        subject=uuid.uuid4(), role="ADMIN", expires_in=timedelta(seconds=-1)
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_token_signed_with_other_key_is_rejected() -> None:
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "typ": "access",
            "iat": 0,
            "exp": 9999999999,
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
        },
        "attacker-key-of-sufficient-length-0123456789",
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(forged)


def test_unsigned_token_is_rejected() -> None:
    """alg=none — классическая атака на JWT. Список алгоритмов фиксирован."""
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "access", "iat": 0, "exp": 9999999999},
        key="",
        algorithm="none",
    )
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(forged)


def test_token_with_wrong_audience_is_rejected() -> None:
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "typ": "access",
            "iat": 0,
            "exp": 9999999999,
            "iss": JWT_ISSUER,
            "aud": "someone-else",
        },
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(jwt.InvalidAudienceError):
        decode_access_token(token)


def test_refresh_token_is_not_accepted_as_access() -> None:
    """Разделение типов: длинный refresh нельзя предъявить вместо access."""
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "typ": "refresh",
            "iat": 0,
            "exp": 9999999999,
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
        },
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


# ----------------------------------------------------------- refresh token
def test_refresh_tokens_are_unique_and_long() -> None:
    tokens = {generate_refresh_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(len(token) >= 43 for token in tokens)


def test_refresh_token_hash_is_deterministic() -> None:
    token = generate_refresh_token()
    assert hash_refresh_token(token) == hash_refresh_token(token)
    assert hash_refresh_token(token) != token
    assert len(hash_refresh_token(token)) == 64


def test_ip_hash_is_salted_and_stable() -> None:
    assert hash_ip(None) is None
    assert hash_ip("192.0.2.1") == hash_ip("192.0.2.1")
    assert hash_ip("192.0.2.1") != hash_ip("192.0.2.2")
    assert "192.0.2.1" not in (hash_ip("192.0.2.1") or "")
