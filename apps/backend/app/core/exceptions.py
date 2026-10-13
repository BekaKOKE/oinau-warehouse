"""Единый формат ошибок API.

Клиенты (web, admin, 1С) разбирают ответ по стабильной схеме:
    {"error": {"code": "not_found", "message": "...", "details": {...}}}
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)


class AppError(Exception):
    """Базовая ошибка бизнес-логики. Наследники живут в модулях."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"
    message: str = "Некорректный запрос"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Объект не найден"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "Конфликт состояния"


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"
    message = "Требуется аутентификация"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"
    message = "Недостаточно прав"


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Слишком много запросов"


def _jsonable(value: Any) -> Any:
    """Приводит детали ошибки к JSON-совместимому виду.

    Pydantic кладёт в ctx исходное исключение, а оно не сериализуется.
    Без этого 422 сам превращается в 500.
    """
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    request_id = request_id_ctx.get()
    if request_id:
        body["error"]["request_id"] = request_id
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,  # константа: имя в Starlette переименовано
            content=_payload(
                "validation_error",
                "Ошибка валидации входных данных",
                {"fields": _jsonable(exc.errors())},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(f"http_{exc.status_code}", str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Наружу не отдаём ни трейс, ни текст исключения.
        logger.exception("unhandled_error", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_payload("internal_error", "Внутренняя ошибка сервера"),
        )
