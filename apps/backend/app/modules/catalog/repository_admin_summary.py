"""Счётчики сводки каталога.

Всё считается ОДНИМ запросом агрегатами `count(*) FILTER (WHERE ...)`:
ни выгрузки товаров в приложение, ни отдельного запроса на каждый
счётчик. Изображения и цены проверяются коррелированными EXISTS по
индексам `ix_product_images_product_sort` и `ix_price_tiers_lookup`,
остатки — одним агрегирующим подзапросом.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, exists, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.enums import ProductStatus
from app.modules.catalog.models import Category, Product
from app.modules.catalog.visibility import public_visibility_clause
from app.modules.inventory.availability import availability_expression
from app.modules.inventory.enums import PublicAvailability
from app.modules.inventory.repository_admin import available_quantity, stock_totals_subquery
from app.modules.media.enums import MediaStatus
from app.modules.media.models import MediaFile, ProductImage
from app.modules.pricing.enums import PricingType
from app.modules.pricing.models import PriceList, PriceTier


class CatalogSummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary_counts(self) -> dict[str, int]:
        live = Product.deleted_at.is_(None)

        has_image = exists().where(ProductImage.product_id == Product.id)
        has_ready_image = exists().where(
            ProductImage.product_id == Product.id,
            MediaFile.id == ProductImage.media_file_id,
            MediaFile.status == MediaStatus.READY.value,
        )
        # Цена берётся только из публичного прайс-листа — того же, что
        # показывает витрина. Ступени дилерских прайсов товар «с ценой»
        # для посетителя не делают.
        has_public_price = exists().where(
            PriceTier.product_id == Product.id,
            PriceList.id == PriceTier.price_list_id,
            PriceList.is_default.is_(True),
            PriceList.is_active.is_(True),
        )

        totals = stock_totals_subquery()
        availability = availability_expression(
            pricing_type=Product.pricing_type,
            stock_display_override=Product.stock_display_override,
            available_quantity=available_quantity(totals),
        )
        on_request = Product.pricing_type == PricingType.ON_REQUEST.value

        def count(*conditions: Any) -> Any:
            return func.count().filter(and_(*conditions))

        def category_count(*conditions: Any) -> Any:
            # Некоррелированный скалярный подзапрос: вычисляется один раз,
            # а не на каждую строку товаров.
            return select(func.count()).select_from(Category).where(*conditions).scalar_subquery()

        category_live = Category.deleted_at.is_(None)

        query = (
            select(
                count(live).label("products_total"),
                count(live, Product.is_active.is_(True)).label("products_active"),
                count(live, Product.is_active.is_(False)).label("products_inactive"),
                count(public_visibility_clause()).label("products_publicly_visible"),
                count(live, Product.is_featured.is_(True)).label("products_featured"),
                count(live, Product.status == ProductStatus.DRAFT.value).label("products_draft"),
                count(live, Product.status == ProductStatus.PUBLISHED.value).label(
                    "products_published"
                ),
                count(live, Product.status == ProductStatus.ARCHIVED.value).label(
                    "products_archived"
                ),
                count(Product.deleted_at.isnot(None)).label("products_deleted"),
                count(live, not_(has_image)).label("content_without_images"),
                count(live, not_(has_ready_image)).label("content_without_ready_images"),
                count(live, not_(on_request), not_(has_public_price)).label(
                    "content_without_price"
                ),
                count(live, on_request).label("content_price_on_request"),
                count(live, availability == PublicAvailability.IN_STOCK.value).label(
                    "availability_in_stock"
                ),
                count(live, availability == PublicAvailability.OUT_OF_STOCK.value).label(
                    "availability_out_of_stock"
                ),
                count(live, availability == PublicAvailability.ON_REQUEST.value).label(
                    "availability_on_request"
                ),
                count(live, Product.stock_display_override.isnot(None)).label(
                    "availability_overridden"
                ),
                category_count(category_live).label("categories_total"),
                category_count(category_live, Category.is_active.is_(True)).label(
                    "categories_active"
                ),
                category_count(Category.deleted_at.isnot(None)).label("categories_deleted"),
            )
            # Агрегат без GROUP BY возвращает ровно одну строку — в том
            # числе когда товаров ещё нет.
            .select_from(Product)
            .outerjoin(totals, totals.c.product_id == Product.id)
        )
        row = (await self.session.execute(query)).mappings().one()
        return {key: int(value or 0) for key, value in row.items()}
