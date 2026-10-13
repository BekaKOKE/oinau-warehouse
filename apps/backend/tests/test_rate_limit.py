"""Тесты ограничения частоты запросов."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from redis.asyncio import from_url

from app.core.config import settings
from app.core.rate_limit import RateLimiter, parse_rate
from app.modules.users.models import User
from tests.conftest import DEFAULT_PASSWORD

MakeUser = Callable[..., Awaitable[User]]


def test_parse_rate() -> None:
    assert parse_rate("10/minute") == (10, 60)
    assert parse_rate("5/hour") == (5, 3600)
    with pytest.raises(ValueError, match="Неизвестный период"):
        parse_rate("5/fortnight")


@pytest.fixture
async def redis_client():
    client = from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    yield client
    await client.aclose()


async def test_limiter_blocks_after_limit(redis_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    limiter = RateLimiter(redis_client)
    key = f"test:{uuid.uuid4().hex}"

    for expected_remaining in (2, 1, 0):
        allowed, remaining = await limiter.hit(key, "3/minute")
        assert allowed is True
        assert remaining == expected_remaining

    allowed, remaining = await limiter.hit(key, "3/minute")
    assert allowed is False
    assert remaining == 0


async def test_limiter_reset(redis_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    limiter = RateLimiter(redis_client)
    key = f"test:{uuid.uuid4().hex}"

    await limiter.hit(key, "1/minute")
    assert (await limiter.hit(key, "1/minute"))[0] is False

    await limiter.reset(key)
    assert (await limiter.hit(key, "1/minute"))[0] is True


async def test_limiter_fails_open_when_redis_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Падение Redis не должно ронять вход в админку и приём заявок."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    broken = from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.1)
    limiter = RateLimiter(broken)

    allowed, remaining = await limiter.hit("test:down", "1/minute")
    assert allowed is True
    assert remaining == -1
    await broken.aclose()


async def test_limiter_disabled_by_settings(redis_client) -> None:
    limiter = RateLimiter(redis_client)
    for _ in range(10):
        assert (await limiter.hit("test:disabled", "1/minute"))[0] is True


async def test_login_endpoint_is_rate_limited(
    api: AsyncClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Перебор пароля упирается в 429 раньше, чем в блокировку записи."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN", "3/minute")
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
    user = await make_user()
    # Свой адрес на каждый прогон: счётчики в Redis переживают тест
    client_ip = f"198.51.100.{uuid.uuid4().int % 250}"

    statuses = [
        (
            await api.post(
                "/api/v1/admin/auth/login",
                json={"email": user.email, "password": DEFAULT_PASSWORD},
                headers={"X-Forwarded-For": client_ip},
            )
        ).status_code
        for _ in range(5)
    ]

    assert 429 in statuses


def test_client_ip_ignores_forwarded_header_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """При TRUSTED_PROXY_HOPS=0 заголовок не учитывается вовсе."""
    from app.api.deps import get_client_ip

    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 0)
    request = _fake_request("203.0.113.9", "198.51.100.1, 203.0.113.7")
    assert get_client_ip(request) == "203.0.113.9"


@pytest.mark.parametrize(
    ("hops", "expected"),
    [
        (1, "203.0.113.7"),  # один nginx: настоящий клиент — последняя запись
        (2, "198.51.100.1"),  # Cloudflare + nginx
        (5, "10.0.0.1"),  # прокси больше, чем записей: берём самую левую
    ],
)
def test_client_ip_respects_trusted_hops(
    monkeypatch: pytest.MonkeyPatch, hops: int, expected: str
) -> None:
    from app.api.deps import get_client_ip

    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", hops)
    request = _fake_request("127.0.0.1", "10.0.0.1, 198.51.100.1, 203.0.113.7")
    assert get_client_ip(request) == expected


def _fake_request(peer: str, forwarded: str | None):
    """Минимальный Request без поднятия ASGI-приложения."""
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (peer, 12345),
        }
    )


async def test_rejected_attempts_do_not_grow_the_window(
    redis_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отклонённая попытка не попадает в окно.

    Проверяется состояние самого множества в Redis, а не только код
    ответа: если решение "пускать или нет" принимается ПОСЛЕ записи,
    ответы выглядят правильно, но каждая попытка перебора продлевает
    блокировку и раздувает ключ. Здесь после трёх разрешённых запросов
    в множестве обязано остаться ровно три элемента, сколько бы
    отклонённых попыток за ними ни последовало.
    """
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    limiter = RateLimiter(redis_client)
    key = f"test:{uuid.uuid4().hex}"
    redis_key = f"rl:{key}"

    for _ in range(3):
        assert (await limiter.hit(key, "3/minute"))[0] is True
    assert await redis_client.zcard(redis_key) == 3

    for _ in range(5):
        assert (await limiter.hit(key, "3/minute"))[0] is False

    assert await redis_client.zcard(redis_key) == 3
