"""Точка входа FastAPI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import register_middleware
from app.db.redis import close_redis
from app.db.session import dispose_engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info("app_startup", version=__version__, env=settings.ENV)
    if settings.is_production and settings.TRUSTED_PROXY_HOPS == 0:
        # Без этого весь трафик из-за обратного прокси выглядит как один
        # клиент: ограничение частоты и аудит теряют смысл.
        logger.warning(
            "trusted_proxy_hops_not_configured",
            hint="Задайте TRUSTED_PROXY_HOPS по числу обратных прокси перед приложением",
        )
    yield
    await dispose_engine()
    await close_redis()
    logger.info("app_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=__version__,
        docs_url=settings.docs_url,
        redoc_url=None,
        openapi_url=settings.openapi_url,
        lifespan=lifespan,
    )

    register_middleware(app)
    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
