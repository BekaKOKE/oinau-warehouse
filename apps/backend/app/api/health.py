"""Health-эндпоинты.

/health       — liveness: процесс жив. Не трогает зависимости.
/health/ready — readiness: проверяет PostgreSQL, Redis и объектное хранилище.
                Именно его опрашивают Docker/оркестратор перед подачей трафика.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from app.core.config import settings
from app.core.logging import get_logger
from app.db.redis import get_redis
from app.db.session import SessionFactory

logger = get_logger(__name__)
router = APIRouter(tags=["health"])

CheckStatus = Literal["ok", "error", "skipped"]


class ComponentCheck(BaseModel):
    status: CheckStatus
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str


class ReadinessResponse(HealthResponse):
    checks: dict[str, ComponentCheck]


async def _timed(name: str, coro: Any) -> tuple[str, ComponentCheck]:
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        await asyncio.wait_for(coro, timeout=3.0)
    except Exception as exc:
        # Наружу отдаём только тип исключения, без текста и трейса.
        logger.warning("healthcheck_failed", component=name, error=str(exc))
        return name, ComponentCheck(status="error", error=type(exc).__name__)
    latency = round((loop.time() - started) * 1000, 2)
    return name, ComponentCheck(status="ok", latency_ms=latency)


async def _check_postgres() -> None:
    async with SessionFactory() as session:
        await session.execute(text("SELECT 1"))


async def _check_redis() -> None:
    await get_redis().ping()


async def _check_storage() -> None:
    from app.infrastructure.storage.client import ping_storage

    await ping_storage()


@router.get("/health", response_model=HealthResponse, summary="Liveness")
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__, environment=settings.ENV)


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness")
async def readiness(response: Response) -> ReadinessResponse:
    results = await asyncio.gather(
        _timed("postgres", _check_postgres()),
        _timed("redis", _check_redis()),
        _timed("storage", _check_storage()),
    )
    checks = dict(results)
    healthy = all(check.status != "error" for check in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ok" if healthy else "degraded",
        version=__version__,
        environment=settings.ENV,
        checks=checks,
    )
