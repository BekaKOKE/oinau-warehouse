"""Запросы Admin API ценообразования."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select

from app.core.repository import BaseRepository
from app.modules.catalog.models import Product
from app.modules.pricing.models import PriceList, PriceTier


class AdminPricingRepository(BaseRepository[PriceTier]):
    model = PriceTier

    async def get_default_price_list(self) -> PriceList | None:
        """Только прайс-лист по умолчанию.

        Остальные прайсы этому API неизвестны — все записи и чтения
        жёстко привязаны к публичному прайсу.
        """
        query = select(PriceList).where(
            PriceList.is_default.is_(True), PriceList.is_active.is_(True)
        )
        return (await self.session.execute(query)).scalars().first()

    async def lock_product(self, product_id: int) -> int | None:
        """Блокирует строку товара на время транзакции.

        PUT заменяет набор ступеней: сначала DELETE, потом INSERT.
        Без блокировки два параллельных запроса в режиме READ COMMITTED
        могут не увидеть строки друг друга при удалении и оставить
        объединённый набор из двух разных прайсов. Блокировка товара
        сериализует изменение цен именно этого товара, не мешая всем
        остальным.
        """
        query = select(Product.id).where(Product.id == product_id).with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def list_tiers(self, product_id: int, price_list_id: int) -> Sequence[PriceTier]:
        query = (
            select(PriceTier)
            .where(PriceTier.product_id == product_id, PriceTier.price_list_id == price_list_id)
            .order_by(PriceTier.min_qty)
        )
        return (await self.session.execute(query)).scalars().all()

    async def replace_tiers(
        self, product_id: int, price_list_id: int, tiers: Sequence[PriceTier]
    ) -> None:
        """Удаление и вставка в одной транзакции.

        Промежуточного коммита нет: товар ни на мгновение не остаётся
        с половиной новых цен.
        """
        await self.session.execute(
            delete(PriceTier).where(
                PriceTier.product_id == product_id,
                PriceTier.price_list_id == price_list_id,
            )
        )
        # flush до вставки: иначе новые ступени могут попасть в базу
        # раньше удаления старых и упереться в EXCLUDE-ограничение.
        await self.session.flush()

        for tier in tiers:
            self.session.add(tier)
        await self.session.flush()

    # ------------------------------------------------ пакетные операции
    async def lock_products(self, product_ids: Sequence[int]) -> None:
        """Блокировка строк нескольких товаров — как lock_product().

        Порядок по id одинаков для всех вызывающих, поэтому две
        транзакции, блокирующие пересекающиеся наборы, не устроят
        взаимную блокировку.
        """
        if product_ids:
            await self.session.execute(
                select(Product.id)
                .where(Product.id.in_(product_ids))
                .order_by(Product.id)
                .with_for_update()
            )

    async def list_tiers_for(
        self, product_ids: Sequence[int], price_list_id: int
    ) -> dict[int, list[PriceTier]]:
        result: dict[int, list[PriceTier]] = {product_id: [] for product_id in product_ids}
        if not product_ids:
            return result
        query = (
            select(PriceTier)
            .where(PriceTier.product_id.in_(product_ids), PriceTier.price_list_id == price_list_id)
            .order_by(PriceTier.product_id, PriceTier.min_qty)
        )
        for tier in (await self.session.execute(query)).scalars().all():
            result.setdefault(tier.product_id, []).append(tier)
        return result

    async def delete_tiers_for(self, product_ids: Sequence[int], price_list_id: int) -> None:
        """Удаление ступеней нескольких товаров в одном прайс-листе.

        Как и в replace_tiers(), вызывающий код обязан сделать flush до
        вставки новых ступеней: иначе упрётся в EXCLUDE-ограничение.
        """
        if product_ids:
            await self.session.execute(
                delete(PriceTier).where(
                    PriceTier.product_id.in_(product_ids),
                    PriceTier.price_list_id == price_list_id,
                )
            )
