"""Вспомогательные утилиты тестов."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine


@contextmanager
def count_queries(engine: AsyncEngine) -> Iterator[list[str]]:
    """Считает SQL-запросы, ушедшие в БД за время блока."""
    statements: list[str] = []

    def _record(_conn, _cursor, statement, _params, _context, _many) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)
