"""HTTP-middleware: корреляция запросов и базовые заголовки безопасности."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# Поверхности, ответы которых нельзя класть ни в один кеш: админка,
# кабинет клиента и вход/регистрация (в теле ответа — access-токен).
# Считается кортежем: str.startswith принимает его как есть.
PRIVATE_PATH_PREFIXES = (
    f"{settings.API_V1_PREFIX}/admin",
    f"{settings.API_V1_PREFIX}/customer",
    f"{settings.API_V1_PREFIX}/public/auth",
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


def register_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,  # refresh-токен живёт в httpOnly cookie
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER, "Idempotency-Key"],
        # Content-Disposition — имя файла для экспорта XLSX. Без явного
        # expose браузер скрывает заголовок от кода на другом источнике,
        # и админка сохраняла бы выгрузку под запасным именем.
        expose_headers=[REQUEST_ID_HEADER, "Content-Disposition"],
        max_age=600,
    )

    @app.middleware("http")
    async def _observability(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        response.headers[REQUEST_ID_HEADER] = request_id
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)

        # Ответы админки и кабинета содержат токены и персональные данные
        # заявок, ответы аутентификации — сами токены. no-store запрещает
        # их сохранение промежуточными прокси и дисковым кешем браузера.
        # На остальной публичный API не распространяется: каталог и тексты
        # кешировать как раз нужно.
        if request.url.path.startswith(PRIVATE_PATH_PREFIXES):
            response.headers.setdefault("Cache-Control", "no-store")
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )

        if request.url.path not in ("/health", "/health/live"):
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
                request_id=request_id,
            )
        return response
