"""Запросы справочника регионов."""

from __future__ import annotations

from sqlalchemy import select

from app.core.repository import BaseRepository
from app.modules.geo.models import Region


class RegionRepository(BaseRepository[Region]):
    model = Region

    async def list_active(self) -> list[Region]:
        """Активные регионы в порядке вывода.

        Порядок задаётся `sort_order`, а не алфавитом: первым в списке
        должен стоять основной регион работы компании.
        """
        query = (
            select(Region).where(Region.is_active.is_(True)).order_by(Region.sort_order, Region.id)
        )
        return list((await self.session.execute(query)).scalars().all())
