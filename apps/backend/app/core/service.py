"""Базовый сервис.

Сервис владеет бизнес-правилами и границей транзакции. Роутер только
валидирует вход и вызывает сервис; репозиторий только достаёт данные.

Коммит делается здесь, а не в зависимости FastAPI: одна операция может
затрагивать несколько таблиц (заявка + позиции + запись в outbox),
и они обязаны фиксироваться одной транзакцией.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
