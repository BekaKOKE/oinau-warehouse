"""Бизнес-правила Admin API ценообразования."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.integrity import guard_unique
from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.catalog.integrity import CATALOG_UNIQUE_ERRORS
from app.modules.catalog.models import Product
from app.modules.catalog.mutability import ensure_mutable
from app.modules.catalog.repository_admin_products import AdminProductRepository
from app.modules.pricing.enums import PricingType
from app.modules.pricing.exceptions import DefaultPriceListMissingError
from app.modules.pricing.models import PriceList, PriceTier
from app.modules.pricing.repository_admin import AdminPricingRepository
from app.modules.pricing.schemas_admin import (
    PriceListRead,
    PriceTierRead,
    PricingRead,
    PricingUpdate,
)
from app.modules.users.models import User

PRICING_ENTITY = "product_pricing"


class PricingAuditAction:
    UPDATED = "pricing.updated"


def tier_to_dict(min_qty: Decimal, max_qty: Decimal | None, price: Decimal) -> dict[str, Any]:
    """Ступень в журнале аудита: строки, а не float — точность не теряется.

    Один формат для Admin API и Excel-импорта: журнал читается одинаково,
    каким бы каналом ни поменяли цену.
    """
    return {
        "min_qty": str(min_qty),
        "max_qty": str(max_qty) if max_qty is not None else None,
        "price": str(price),
    }


class AdminPricingService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = AdminPricingRepository(session)
        self.products = AdminProductRepository(session)
        self.audit = AuditService(session)

    # -------------------------------------------------------------- чтение
    async def get_price_list(self) -> PriceListRead:
        price_list = await self._require_price_list()
        return PriceListRead(
            id=price_list.id,
            code=price_list.code,
            name=price_list.name,
            currency=price_list.currency,
        )

    async def get_pricing(self, product_id: int) -> PricingRead:
        product = await self._require_product(product_id)
        price_list = await self._require_price_list()
        tiers = await self.repository.list_tiers(product.id, price_list.id)
        return self._to_read(product, price_list, tiers)

    # -------------------------------------------------------------- запись
    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def set_pricing(
        self, product_id: int, payload: PricingUpdate, actor: User
    ) -> PricingRead:
        """Полная замена публичного ценообразования товара.

        Тип цены и набор ступеней меняются одной транзакцией: состояние,
        в котором товар помечен как TIERED, но ступеней ещё нет, наружу
        не попадает.
        """
        # Общее правило проекта: удалённый товар доступен только
        # на чтение и восстановление.
        product = ensure_mutable(await self._require_product(product_id))

        price_list = await self._require_price_list()

        # Блокировка строки товара сериализует конкурентные изменения
        # цен именно этого товара.
        await self.repository.lock_product(product.id)

        previous_tiers = await self.repository.list_tiers(product.id, price_list.id)
        previous = {
            "pricing_type": product.pricing_type,
            "tiers": [self._tier_to_dict(tier) for tier in previous_tiers],
        }

        await self.repository.replace_tiers(
            product.id,
            price_list.id,
            [
                PriceTier(
                    product_id=product.id,
                    price_list_id=price_list.id,
                    min_qty=tier.min_qty,
                    max_qty=tier.max_qty,
                    price=tier.price,
                )
                for tier in payload.tiers
            ],
        )
        product.pricing_type = payload.pricing_type.value
        await self.session.flush()

        current = {
            "pricing_type": payload.pricing_type.value,
            "tiers": [
                tier_to_dict(tier.min_qty, tier.max_qty, tier.price) for tier in payload.tiers
            ],
        }
        self.audit.record(
            action=PricingAuditAction.UPDATED,
            entity_type=PRICING_ENTITY,
            entity_id=product.id,
            user_id=actor.id,
            changes={"old": previous, "new": current},
        )
        await self.commit()
        return await self.get_pricing(product.id)

    # ---------------------------------------------------------- внутреннее
    async def _require_product(self, product_id: int) -> Product:
        product = await self.products.get_by_id(product_id)
        if product is None:
            raise NotFoundError("Товар не найден")
        return product

    async def _require_price_list(self) -> PriceList:
        price_list = await self.repository.get_default_price_list()
        if price_list is None:
            raise DefaultPriceListMissingError
        return price_list

    def _tier_to_dict(self, tier: PriceTier) -> dict[str, Any]:
        return tier_to_dict(tier.min_qty, tier.max_qty, tier.price)

    def _to_read(self, product: Product, price_list: PriceList, tiers: Any) -> PricingRead:
        prices: list[Decimal] = [tier.price for tier in tiers]
        return PricingRead(
            product_id=product.id,
            sku=product.sku,
            pricing_type=PricingType(product.pricing_type),
            currency=price_list.currency,
            price_list_code=price_list.code,
            tiers=[
                PriceTierRead(
                    id=tier.id,
                    min_qty=tier.min_qty,
                    max_qty=tier.max_qty,
                    price=tier.price,
                )
                for tier in tiers
            ],
            min_price=min(prices) if prices else None,
            max_price=max(prices) if prices else None,
        )
