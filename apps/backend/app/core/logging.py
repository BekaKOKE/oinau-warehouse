"""Структурированное логирование.

В local — читаемый вывод в консоль, в проде — JSON для сбора логов.
Каждая запись несёт request_id, что позволяет собрать весь путь запроса.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any, cast

import structlog
from structlog.typing import Processor

from app.core.config import settings

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def _add_request_id(
    _logger: object, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    request_id = request_id_ctx.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        # Процессоры из structlog.processors, а не из structlog.stdlib:
        # логгер здесь PrintLogger, а не обёртка над logging.Logger.
        # `structlog.stdlib.add_logger_name` читает `logger.name`, которого
        # у PrintLogger нет, — имя модуля подставляет get_logger() ниже.
        structlog.processors.add_log_level,
        _add_request_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.LOG_FORMAT == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    for noisy in ("uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True

    # httpx на уровне INFO печатает строку запроса целиком. Для нас это
    # прямая утечка: токен бота Telegram стоит В ПУТИ URL, и такой лог
    # раздаёт ключ от рассылки всем, кто читает журнал. Своих запросов
    # мы логируем ровно столько, сколько нужно, — в провайдерах.
    _silence_httpx()


def _silence_httpx() -> None:
    """Глушит строку запроса httpx: в ней бывает секрет (см. Telegram)."""
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.WARNING)


# Применяется и при импорте: воркер и тесты могут не звать configure_logging().
_silence_httpx()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Логгер с именем модуля в поле `logger`.

    Имя привязывается явно: фабрика PrintLogger, в отличие от stdlib,
    позиционный аргумент `get_logger()` никуда не сохраняет.
    """
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(logger=name)
    return cast("structlog.stdlib.BoundLogger", logger)
