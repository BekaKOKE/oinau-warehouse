"""Запросы публичного приёма заявок.

Все выборки пакетные: состав заявки проверяется и оценивается
фиксированным числом запросов, сколько бы позиций в ней ни было.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import aliased, selectinload

from app.core.config import settings
from app.core.repository import BaseRepository
from app.modules.catalog.models import Product, ProductTranslation
from app.modules.catalog.visibility import public_visibility_clause
from app.modules.geo.models import Region
from app.modules.pricing.models import PriceTier
from app.modules.requests.models import Request


@dataclass(frozen=True)
class OrderableProduct:
    """Товар, который можно заказать, и его название для снапшота."""

    product: Product
    name: str


class RequestRepository(BaseRepository[Request]):
    model = Request

    async def get_active_region(self, region_id: int) -> Region | None:
        """Отключённый регион заявок не принимает — так же, как не
        показывается в выборе города."""
        query = select(Region).where(Region.id == region_id, Region.is_active.is_(True))
        return (await self.session.execute(query)).scalars().first()

    async def get_orderable_products(self, skus: Sequence[str]) -> dict[str, OrderableProduct]:
        """Товары по артикулам — только видимые на витрине.

        Правило видимости берётся из catalog/visibility.py: заказать
        можно ровно то, что посетитель может увидеть. Черновик,
        отключённый или удалённый товар в результат не попадает.

        Название — в локали по умолчанию: заявку читают менеджеры,
        и снапшот должен быть на одном языке для всех заявок.
        """
        if not skus:
            return {}
        rows = await self._orderable(Product.sku.in_(skus))
        return {entry.product.sku: entry for entry in rows}

    async def find_orderable_products_ci(self, skus: Sequence[str]) -> dict[str, OrderableProduct]:
        """То же, но без учёта регистра — для списка, вставленного руками.

        Ключ результата — артикул в верхнем регистре. Индекс по `sku` здесь
        не работает, но список ограничен сотней позиций, а каталог —
        тысячами товаров.
        """
        keys = sorted({sku.upper() for sku in skus if sku})
        if not keys:
            return {}
        rows = await self._orderable(func.upper(Product.sku).in_(keys))
        return {entry.product.sku.upper(): entry for entry in rows}

    async def _orderable(self, condition: Any) -> list[OrderableProduct]:
        translation = aliased(ProductTranslation)
        query = (
            select(Product, translation.name)
            .outerjoin(
                translation,
                and_(
                    translation.product_id == Product.id,
                    translation.locale == settings.DEFAULT_LOCALE,
                ),
            )
            .where(condition, public_visibility_clause())
        )
        rows = (await self.session.execute(query)).all()
        return [
            OrderableProduct(product=product, name=name or product.sku) for product, name in rows
        ]

    async def get_price_tiers(
        self, product_ids: Sequence[int], price_list_id: int
    ) -> dict[int, list[PriceTier]]:
        """Ступени ТОЛЬКО указанного прайс-листа, одним запросом на всю заявку.

        Не через связь `Product.price_tiers`: она подтянула бы и
        дилерские цены.
        """
        if not product_ids:
            return {}
        query = (
            select(PriceTier)
            .where(PriceTier.product_id.in_(product_ids), PriceTier.price_list_id == price_list_id)
            .order_by(PriceTier.product_id, PriceTier.min_qty)
        )
        result: dict[int, list[PriceTier]] = defaultdict(list)
        for tier in (await self.session.execute(query)).scalars().all():
            result[tier.product_id].append(tier)
        return dict(result)

    async def next_request_id(self) -> int:
        """Следующий id заявки из её собственной последовательности.

        Нужен до вставки: человекочитаемый номер строится из id, а
        колонка `number` обязательна. Отдельная последовательность или
        таблица счётчиков потребовала бы изменения схемы; значение,
        взятое и не использованное из-за отката, просто пропускается.
        """
        query = text("SELECT nextval(pg_get_serial_sequence('requests', 'id'))")
        return int((await self.session.execute(query)).scalar_one())

    async def find_by_idempotency_key(self, key: str) -> Request | None:
        query = (
            select(Request)
            .where(Request.idempotency_key == key)
            .options(selectinload(Request.items), selectinload(Request.attachments))
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(query)).scalars().first()
