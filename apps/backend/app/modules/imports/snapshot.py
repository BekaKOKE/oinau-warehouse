"""Состояние каталога, с которым сравнивается файл.

Загружается фиксированным числом запросов до проверки строк: справочники
целиком (их десятки строк), товары — только перечисленные в файле, плюс
лёгкие карты (артикулы, slug, внешние id) для проверки уникальности.
Проверка строк после этого идёт в памяти, без запроса на каждую строку.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.catalog.models import (
    Attribute,
    AttributeOption,
    Category,
    CategoryAttribute,
    Product,
    ProductAttributeValue,
    ProductCategory,
)
from app.modules.pricing.models import PriceList, PriceTier
from app.modules.pricing.repository_admin import AdminPricingRepository


@dataclass(frozen=True)
class ProductRef:
    """Лёгкая запись о товаре для проверки уникальности."""

    id: int
    sku: str
    slug: str
    external_id: str | None
    is_deleted: bool


@dataclass(frozen=True)
class CategoryLink:
    attribute_code: str
    sort_order: int
    is_required: bool


@dataclass
class CatalogSnapshot:
    price_list: PriceList | None
    # Живые товары из файла со всеми связями, по артикулу.
    products: dict[str, Product] = field(default_factory=dict)
    tiers: dict[int, list[PriceTier]] = field(default_factory=dict)
    # Все товары, включая удалённые, — только ключевые поля.
    product_refs: list[ProductRef] = field(default_factory=list)
    # Живые категории с переводами, по slug.
    categories: dict[str, Category] = field(default_factory=dict)
    categories_by_id: dict[int, Category] = field(default_factory=dict)
    deleted_category_slugs: set[str] = field(default_factory=set)
    # external_id -> slug среди всех категорий (индекс не смотрит на deleted_at).
    category_external_ids: dict[str, str] = field(default_factory=dict)
    category_links: dict[int, list[CategoryLink]] = field(default_factory=dict)
    attributes: dict[str, Attribute] = field(default_factory=dict)

    # ------------------------------------------------ производные карты
    def live_sku_by_slug(self) -> dict[str, str]:
        return {ref.slug: ref.sku for ref in self.product_refs if not ref.is_deleted}

    def live_skus_by_lower(self) -> dict[str, str]:
        return {ref.sku.lower(): ref.sku for ref in self.product_refs if not ref.is_deleted}

    def deleted_skus(self) -> set[str]:
        live = {ref.sku for ref in self.product_refs if not ref.is_deleted}
        return {ref.sku for ref in self.product_refs if ref.is_deleted and ref.sku not in live}

    def product_external_ids(self) -> dict[str, ProductRef]:
        return {ref.external_id: ref for ref in self.product_refs if ref.external_id is not None}


class CatalogSnapshotLoader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.pricing = AdminPricingRepository(session)

    async def load(self, skus: Sequence[str], *, lock_products: bool = False) -> CatalogSnapshot:
        """Снимок каталога для проверки файла.

        lock_products=True — при подтверждении: строки товаров из файла
        блокируются до конца транзакции, как в Admin API цен. Блокировка
        берётся ДО чтения связей, чтобы прочитать уже зафиксированное
        состояние, а не то, что конкурент вот-вот перепишет.
        """
        price_list = await self.pricing.get_default_price_list()
        snapshot = CatalogSnapshot(price_list=price_list)

        unique_skus = sorted(set(skus))
        if lock_products and unique_skus:
            ids = (
                (
                    await self.session.execute(
                        select(Product.id).where(
                            Product.sku.in_(unique_skus), Product.deleted_at.is_(None)
                        )
                    )
                )
                .scalars()
                .all()
            )
            await self.pricing.lock_products(sorted(ids))

        await self._load_product_refs(snapshot)
        await self._load_products(snapshot, unique_skus)
        await self._load_categories(snapshot)
        await self._load_attributes(snapshot)
        return snapshot

    async def _load_product_refs(self, snapshot: CatalogSnapshot) -> None:
        rows = await self.session.execute(
            select(Product.id, Product.sku, Product.slug, Product.external_id, Product.deleted_at)
        )
        snapshot.product_refs = [
            ProductRef(
                id=row.id,
                sku=row.sku,
                slug=row.slug,
                external_id=row.external_id,
                is_deleted=row.deleted_at is not None,
            )
            for row in rows
        ]

    async def _load_products(self, snapshot: CatalogSnapshot, skus: list[str]) -> None:
        if not skus:
            return
        query = (
            select(Product)
            .where(Product.sku.in_(skus), Product.deleted_at.is_(None))
            .options(
                selectinload(Product.translations),
                selectinload(Product.categories).joinedload(ProductCategory.category),
                selectinload(Product.attribute_values).joinedload(ProductAttributeValue.attribute),
                selectinload(Product.attribute_values).joinedload(ProductAttributeValue.option),
            )
            # Сессия могла уже держать эти объекты: нужны свежие данные.
            .execution_options(populate_existing=True)
        )
        products = (await self.session.execute(query)).scalars().unique().all()
        snapshot.products = {product.sku: product for product in products}
        if snapshot.price_list is not None:
            snapshot.tiers = await self.pricing.list_tiers_for(
                [product.id for product in products], snapshot.price_list.id
            )

    async def _load_categories(self, snapshot: CatalogSnapshot) -> None:
        query = (
            select(Category)
            .options(selectinload(Category.translations))
            .execution_options(populate_existing=True)
        )
        for category in (await self.session.execute(query)).scalars().all():
            if category.external_id is not None:
                snapshot.category_external_ids[category.external_id] = category.slug
            if category.deleted_at is not None:
                snapshot.deleted_category_slugs.add(category.slug)
                continue
            snapshot.categories[category.slug] = category
            snapshot.categories_by_id[category.id] = category
        # slug удалённой категории, занятый живой, «удалённым» не считается
        snapshot.deleted_category_slugs -= set(snapshot.categories)

        links = await self.session.execute(
            select(CategoryAttribute, Attribute.code)
            .join(Attribute, Attribute.id == CategoryAttribute.attribute_id)
            .order_by(CategoryAttribute.category_id, CategoryAttribute.sort_order, Attribute.code)
        )
        for link, code in links.all():
            snapshot.category_links.setdefault(link.category_id, []).append(
                CategoryLink(
                    attribute_code=code, sort_order=link.sort_order, is_required=link.is_required
                )
            )

    async def _load_attributes(self, snapshot: CatalogSnapshot) -> None:
        query = (
            select(Attribute)
            .options(selectinload(Attribute.options))
            .execution_options(populate_existing=True)
        )
        snapshot.attributes = {
            attribute.code: attribute
            for attribute in (await self.session.execute(query)).scalars().all()
        }


def option_by_slug(attribute: Attribute) -> dict[str, AttributeOption]:
    return {option.slug: option for option in attribute.options}


__all__ = [
    "CatalogSnapshot",
    "CatalogSnapshotLoader",
    "CategoryLink",
    "ProductRef",
    "option_by_slug",
]
