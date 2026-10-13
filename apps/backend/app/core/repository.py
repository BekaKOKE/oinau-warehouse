"""Базовый репозиторий.

Репозиторий отвечает ТОЛЬКО за доступ к данным: собрать запрос, вернуть
объекты. Никаких правил вроде "заблокировать после 5 неудач" здесь нет —
это работа сервиса.

Разделение нужно, потому что одни и те же выборки будут использоваться
из HTTP-эндпоинтов, из фонового воркера и из будущего обмена с 1С.
Если запросы живут в роутерах, переиспользовать их невозможно.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base


class BaseRepository[ModelT: Base]:
    """Общие операции чтения и записи для одной модели."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------ helpers
    def _base_query(self, *, include_deleted: bool = False) -> Select[tuple[ModelT]]:
        """Базовый SELECT с отсечением мягко удалённых строк.

        Фильтр по deleted_at живёт здесь, а не в каждом запросе: иначе
        рано или поздно кто-то его забудет, и удалённый товар появится
        на витрине.
        """
        query = select(self.model)
        deleted_at = getattr(self.model, "deleted_at", None)
        if deleted_at is not None and not include_deleted:
            query = query.where(deleted_at.is_(None))
        return query

    # --------------------------------------------------------------- чтение
    async def get(self, entity_id: Any, *, include_deleted: bool = False) -> ModelT | None:
        query = self._base_query(include_deleted=include_deleted).where(
            self.model.id == entity_id  # type: ignore[attr-defined]
        )
        return (await self.session.execute(query)).scalar_one_or_none()

    async def find_one_by(self, *, include_deleted: bool = False, **filters: Any) -> ModelT | None:
        query = self._base_query(include_deleted=include_deleted).filter_by(**filters)
        return (await self.session.execute(query)).scalars().first()

    async def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
        **filters: Any,
    ) -> Sequence[ModelT]:
        query = (
            self._base_query(include_deleted=include_deleted)
            .filter_by(**filters)
            .order_by(self.model.id)  # type: ignore[attr-defined]
            .limit(limit)
            .offset(offset)
        )
        return (await self.session.execute(query)).scalars().all()

    async def count(self, *, include_deleted: bool = False, **filters: Any) -> int:
        query = self._base_query(include_deleted=include_deleted).filter_by(**filters)
        total = await self.session.execute(select(func.count()).select_from(query.subquery()))
        return total.scalar_one()

    # --------------------------------------------------------------- запись
    def add(self, entity: ModelT) -> ModelT:
        """Помещает объект в сессию. Коммит — обязанность сервиса."""
        self.session.add(entity)
        return entity

    async def flush(self) -> None:
        await self.session.flush()
