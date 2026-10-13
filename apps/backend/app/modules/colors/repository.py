"""Запросы справочника цветов и цветов товара."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import delete, func, select

from app.core.repository import BaseRepository
from app.modules.colors.models import Color, ProductColor


class ColorRepository(BaseRepository[Color]):
    model = Color

    async def list_colors(self, *, is_active: bool | None = None) -> list[Color]:
        query = select(Color).order_by(Color.sort_order, Color.name, Color.id)
        if is_active is not None:
            query = query.where(Color.is_active.is_(is_active))
        return list((await self.session.execute(query)).scalars().all())

    async def get_color(self, color_id: int) -> Color | None:
        return await self.session.get(Color, color_id)

    async def get_colors_by_ids(self, ids: Sequence[int]) -> dict[int, Color]:
        if not ids:
            return {}
        query = select(Color).where(Color.id.in_(ids))
        return {color.id: color for color in (await self.session.execute(query)).scalars()}

    async def usage_counts(self, color_ids: Sequence[int]) -> dict[int, int]:
        """В скольких товарах используется каждый цвет — одним запросом."""
        if not color_ids:
            return {}
        query = (
            select(ProductColor.color_id, func.count())
            .where(ProductColor.color_id.in_(color_ids))
            .group_by(ProductColor.color_id)
        )
        rows = (await self.session.execute(query)).tuples().all()
        return dict(rows)

    # ------------------------------------------------------- цвета товара
    async def product_colors(self, product_id: int) -> list[ProductColor]:
        query = (
            select(ProductColor)
            .where(ProductColor.product_id == product_id)
            .order_by(ProductColor.sort_order, ProductColor.id)
        )
        return list((await self.session.execute(query)).scalars().unique().all())

    async def colors_for_products(
        self, product_ids: Sequence[int], *, active_only: bool = True
    ) -> dict[int, list[ProductColor]]:
        """Цвета нескольких товаров одним запросом — для страницы каталога и заявки.

        `active_only`: витрина и заявки не видят цветов, отключённых
        в справочнике.
        """
        if not product_ids:
            return {}
        query = (
            select(ProductColor)
            .join(Color, Color.id == ProductColor.color_id)
            .where(ProductColor.product_id.in_(product_ids))
            .order_by(ProductColor.product_id, ProductColor.sort_order, ProductColor.id)
        )
        if active_only:
            query = query.where(Color.is_active.is_(True))
        result: dict[int, list[ProductColor]] = defaultdict(list)
        for item in (await self.session.execute(query)).scalars().unique():
            result[item.product_id].append(item)
        return dict(result)

    async def delete_product_colors(self, product_id: int) -> None:
        query = delete(ProductColor).where(ProductColor.product_id == product_id)
        await self.session.execute(query)
