"""Превращение нарушений целостности БД в доменные ошибки.

Предварительный SELECT не защищает от гонки: два запроса могут
одновременно убедиться, что артикул свободен, и оба перейти к вставке.
Второй получит нарушение уникального индекса. Последней гарантией
уникальности остаётся база — этот модуль переводит её отказ в понятный
409 вместо 500.

Конфликт определяется по ИМЕНИ constraint/индекса, а не по тексту
сообщения: текст зависит от версии и локали PostgreSQL, а имена
зафиксированы в миграции и naming convention.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from typing import Concatenate, ParamSpec, Protocol, TypeVar, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Максимальная глубина обхода цепочки исключений. SQLAlchemy оборачивает
# ошибку asyncpg в свой DBAPI-класс, поэтому имя constraint лежит на
# один-два уровня глубже.
_MAX_CAUSE_DEPTH = 5


def extract_constraint_name(error: IntegrityError) -> str | None:
    """Имя нарушенного constraint или уникального индекса.

    asyncpg кладёт его в `constraint_name`, psycopg — в `diag`.
    Поддерживаются оба: приложение работает через asyncpg, но Alembic
    и служебные скрипты используют psycopg.
    """
    candidate: BaseException | None = error
    for _ in range(_MAX_CAUSE_DEPTH):
        if candidate is None:
            break

        name = getattr(candidate, "constraint_name", None)
        if name:
            return str(name)

        diag = getattr(candidate, "diag", None)
        diag_name = getattr(diag, "constraint_name", None) if diag is not None else None
        if diag_name:
            return str(diag_name)

        candidate = getattr(candidate, "orig", None) or candidate.__cause__

    return None


def translate_integrity_error(
    error: IntegrityError, mapping: Mapping[str, type[AppError]]
) -> AppError | None:
    """Доменная ошибка для известного constraint, иначе None.

    None означает «нарушение нам незнакомо». Такое исключение обязано
    уйти наверх как есть: выдавать за бизнес-конфликт то, что на самом
    деле является ошибкой в коде или в схеме, — значит спрятать баг.
    """
    name = extract_constraint_name(error)
    if name is None:
        logger.error("integrity_error_without_constraint_name")
        return None

    error_class = mapping.get(name)
    if error_class is None:
        logger.error("unmapped_integrity_constraint", constraint=name)
        return None

    # Имя индекса наружу не отдаётся: это внутренняя деталь схемы.
    logger.info("integrity_conflict", constraint=name)
    return error_class()


class _HasSession(Protocol):
    session: AsyncSession


P = ParamSpec("P")
R = TypeVar("R")
ServiceT = TypeVar("ServiceT", bound=_HasSession)


def guard_unique(
    mapping: Mapping[str, type[AppError]],
) -> Callable[
    [Callable[Concatenate[ServiceT, P], Awaitable[R]]],
    Callable[Concatenate[ServiceT, P], Awaitable[R]],
]:
    """Декоратор для мутирующих методов сервиса.

    После IntegrityError транзакция PostgreSQL находится в состоянии
    aborted: любой следующий запрос в ней завершится ошибкой. Поэтому
    сессия откатывается до того, как исключение уйдёт наверх.
    """

    def decorator(
        method: Callable[Concatenate[ServiceT, P], Awaitable[R]],
    ) -> Callable[Concatenate[ServiceT, P], Awaitable[R]]:
        @wraps(method)
        async def wrapper(self: ServiceT, *args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await method(self, *args, **kwargs)
            except IntegrityError as exc:
                await self.session.rollback()
                domain_error = translate_integrity_error(exc, mapping)
                if domain_error is None:
                    raise
                raise domain_error from exc

        # functools.wraps возвращает _Wrapped, который mypy не считает
        # тождественным исходной сигнатуре, — приводим явно.
        return cast("Callable[Concatenate[ServiceT, P], Awaitable[R]]", wrapper)

    return decorator
