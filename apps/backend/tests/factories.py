"""Минимальные фабрики объектов для тестов схемы."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.enums import ProductStatus
from app.modules.catalog.models import Category, CategoryTranslation, Product, ProductTranslation
from app.modules.pricing.enums import PricingType
from app.modules.pricing.models import PriceList
from app.modules.requests.enums import RequestKind, RequestStatus
from app.modules.requests.models import Request, RequestItem


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def make_category(session: AsyncSession, **kwargs: object) -> Category:
    category = Category(slug=kwargs.pop("slug", unique("cat")), **kwargs)  # type: ignore[arg-type]
    session.add(category)
    await session.flush()
    session.add(
        CategoryTranslation(category_id=category.id, locale="ru", name="Тестовая категория")
    )
    await session.flush()
    return category


async def make_product(session: AsyncSession, **kwargs: object) -> Product:
    kwargs.setdefault("sku", unique("SKU"))
    kwargs.setdefault("slug", unique("product"))
    kwargs.setdefault("status", ProductStatus.PUBLISHED.value)
    product = Product(**kwargs)  # type: ignore[arg-type]
    session.add(product)
    await session.flush()
    session.add(
        ProductTranslation(product_id=product.id, locale="ru", name="Канат полипропиленовый 16 мм")
    )
    await session.flush()
    return product


async def make_price_list(session: AsyncSession, **kwargs: object) -> PriceList:
    kwargs.setdefault("code", unique("pl"))
    kwargs.setdefault("name", "Основной прайс")
    price_list = PriceList(**kwargs)  # type: ignore[arg-type]
    session.add(price_list)
    await session.flush()
    return price_list


async def make_request(session: AsyncSession, **kwargs: object) -> Request:
    kwargs.setdefault("number", unique("R"))
    kwargs.setdefault("kind", RequestKind.CART.value)
    kwargs.setdefault("status", RequestStatus.NEW.value)
    kwargs.setdefault("customer_name", "Иван Петров")
    kwargs.setdefault("phone", "+77011234567")
    request = Request(**kwargs)  # type: ignore[arg-type]
    session.add(request)
    await session.flush()
    return request


async def make_request_item(
    session: AsyncSession, request: Request, product: Product | None, **kwargs: object
) -> RequestItem:
    kwargs.setdefault("sku_snapshot", product.sku if product else "MANUAL")
    kwargs.setdefault("name_snapshot", "Канат полипропиленовый 16 мм")
    kwargs.setdefault("unit_snapshot", "m")
    kwargs.setdefault("pricing_type_snapshot", PricingType.TIERED.value)
    kwargs.setdefault("quantity", Decimal("10.000"))
    item = RequestItem(
        request_id=request.id,
        product_id=product.id if product else None,
        **kwargs,  # type: ignore[arg-type]
    )
    session.add(item)
    await session.flush()
    return item
