"""Запросы Admin API товаров."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import Select, and_, delete, func, or_, select
from sqlalchemy.orm import aliased, selectinload

from app.core.config import settings
from app.core.pagination import PageParams
from app.core.repository import BaseRepository
from app.modules.catalog.models import (
    Attribute,
    AttributeOption,
    Category,
    Product,
    ProductAttributeValue,
    ProductCategory,
    ProductTranslation,
)
from app.modules.inventory.repository_admin import available_quantity, stock_totals_subquery
from app.modules.media.models import MediaFile, ProductImage
from app.modules.pricing.models import PriceList, PriceTier


class ProductAdminSort(StrEnum):
    """Белый список сортировок админского списка."""

    NEWEST = "newest"
    UPDATED = "updated"
    NAME = "name"
    SKU = "sku"


@dataclass(frozen=True)
class ProductListExtras:
    """Данные строки списка из соседних доменов: фото, цена, остаток."""

    main_image: MediaFile | None = None
    images_count: int = 0
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    available_quantity: Decimal | None = None


@dataclass(frozen=True)
class ProductAdminFilters:
    search: str | None = None
    status: str | None = None
    is_active: bool | None = None
    is_featured: bool | None = None
    category_id: int | None = None
    external_id: str | None = None
    include_deleted: bool = False


class AdminProductRepository(BaseRepository[Product]):
    model = Product

    # Загрузка связей одним набором selectinload: число запросов
    # фиксировано и не зависит от размера страницы.
    def _load_options(self) -> list[Any]:
        return [
            selectinload(Product.translations),
            selectinload(Product.categories)
            .joinedload(ProductCategory.category)
            .selectinload(Category.translations),
            selectinload(Product.attribute_values).joinedload(ProductAttributeValue.attribute),
            selectinload(Product.attribute_values).joinedload(ProductAttributeValue.option),
        ]

    def _query(self, *, include_deleted: bool) -> Select[tuple[Product]]:
        # populate_existing: сервис читает товар, меняет его, коммитит
        # и читает снова в той же сессии. Без этого вернётся объект
        # из identity map со старыми коллекциями.
        query = (
            select(Product).options(*self._load_options()).execution_options(populate_existing=True)
        )
        if not include_deleted:
            query = query.where(Product.deleted_at.is_(None))
        return query

    async def get_by_id(self, product_id: int, *, include_deleted: bool = True) -> Product | None:
        query = self._query(include_deleted=include_deleted).where(Product.id == product_id)
        return (await self.session.execute(query)).scalars().first()

    async def find_by_sku(self, sku: str) -> Product | None:
        """Поиск среди живых: удалённый товар артикул не занимает —
        это соответствует частичному индексу `WHERE deleted_at IS NULL`."""
        query = self._query(include_deleted=False).where(Product.sku == sku)
        return (await self.session.execute(query)).scalars().first()

    async def find_by_slug(self, slug: str) -> Product | None:
        query = self._query(include_deleted=False).where(Product.slug == slug)
        return (await self.session.execute(query)).scalars().first()

    async def find_by_external_id(self, external_id: str) -> Product | None:
        """Внешний идентификатор уникален и среди удалённых товаров:
        индекс задан условием `WHERE external_id IS NOT NULL`, без
        оглядки на deleted_at."""
        query = self._query(include_deleted=True).where(Product.external_id == external_id)
        return (await self.session.execute(query)).scalars().first()

    async def list_products(
        self, *, filters: ProductAdminFilters, sort: ProductAdminSort, params: PageParams
    ) -> tuple[Sequence[Product], int]:
        translation = aliased(ProductTranslation)
        default_locale = settings.DEFAULT_LOCALE

        query = self._query(include_deleted=filters.include_deleted).outerjoin(
            translation,
            and_(
                translation.product_id == Product.id,
                translation.locale == default_locale,
            ),
        )

        if filters.status is not None:
            query = query.where(Product.status == filters.status)
        if filters.is_active is not None:
            query = query.where(Product.is_active.is_(filters.is_active))
        if filters.is_featured is not None:
            query = query.where(Product.is_featured.is_(filters.is_featured))
        if filters.external_id is not None:
            query = query.where(Product.external_id == filters.external_id)
        if filters.category_id is not None:
            query = query.where(
                Product.id.in_(
                    select(ProductCategory.product_id).where(
                        ProductCategory.category_id == filters.category_id
                    )
                )
            )
        if filters.search and filters.search.strip():
            pattern = f"%{filters.search.strip()}%"
            query = query.where(
                or_(
                    Product.sku.ilike(pattern),
                    Product.slug.ilike(pattern),
                    translation.name.ilike(pattern),
                )
            )

        total = (
            await self.session.execute(
                select(func.count()).select_from(query.with_only_columns(Product.id).subquery())
            )
        ).scalar_one()

        # Product.id последним — устойчивый тай-брейкер, без него
        # соседние страницы могут повторить или потерять товар.
        order_options: dict[ProductAdminSort, list[Any]] = {
            ProductAdminSort.NEWEST: [Product.created_at.desc()],
            ProductAdminSort.UPDATED: [Product.updated_at.desc()],
            ProductAdminSort.NAME: [translation.name.asc().nullslast()],
            ProductAdminSort.SKU: [Product.sku.asc()],
        }
        order = order_options[sort]

        rows = (
            await self.session.execute(
                query.order_by(*order, Product.id.desc()).limit(params.limit).offset(params.offset)
            )
        ).scalars()
        return rows.unique().all(), total

    async def list_extras(
        self, product_ids: Sequence[int]
    ) -> tuple[dict[int, ProductListExtras], PriceList | None]:
        """Фото, цены и остатки страницы — фиксированным числом запросов
        на всю страницу, сколько бы в ней ни было строк."""
        price_list = await self._public_price_list()
        if not product_ids:
            return {}, price_list
        ids = list(product_ids)

        counts: dict[int, int] = {
            row[0]: int(row[1])
            for row in (
                await self.session.execute(
                    select(ProductImage.product_id, func.count(ProductImage.id))
                    .where(ProductImage.product_id.in_(ids))
                    .group_by(ProductImage.product_id)
                )
            ).all()
        }
        main_images: dict[int, MediaFile] = {
            row[0]: row[1]
            for row in (
                await self.session.execute(
                    select(ProductImage.product_id, MediaFile)
                    .join(MediaFile, MediaFile.id == ProductImage.media_file_id)
                    .where(ProductImage.product_id.in_(ids), ProductImage.is_main.is_(True))
                )
            ).all()
        }

        prices: dict[int, tuple[Decimal, Decimal]] = {}
        if price_list is not None:
            price_rows = await self.session.execute(
                select(PriceTier.product_id, func.min(PriceTier.price), func.max(PriceTier.price))
                .where(PriceTier.product_id.in_(ids), PriceTier.price_list_id == price_list.id)
                .group_by(PriceTier.product_id)
            )
            prices = {row[0]: (row[1], row[2]) for row in price_rows.all()}

        totals = stock_totals_subquery()
        stock: dict[int, Decimal] = {
            row[0]: row[1]
            for row in (
                await self.session.execute(
                    select(totals.c.product_id, available_quantity(totals)).where(
                        totals.c.product_id.in_(ids)
                    )
                )
            ).all()
        }

        extras = {
            product_id: ProductListExtras(
                main_image=main_images.get(product_id),
                images_count=counts.get(product_id, 0),
                min_price=prices[product_id][0] if product_id in prices else None,
                max_price=prices[product_id][1] if product_id in prices else None,
                available_quantity=stock.get(product_id),
            )
            for product_id in ids
        }
        return extras, price_list

    async def _public_price_list(self) -> PriceList | None:
        query = select(PriceList).where(
            PriceList.is_default.is_(True), PriceList.is_active.is_(True)
        )
        return (await self.session.execute(query)).scalars().first()

    # ------------------------------------------------------------ связи
    async def get_categories_by_ids(self, category_ids: Sequence[int]) -> dict[int, Category]:
        if not category_ids:
            return {}
        query = (
            select(Category)
            .where(Category.id.in_(category_ids))
            .options(selectinload(Category.translations))
        )
        return {item.id: item for item in (await self.session.execute(query)).scalars().all()}

    async def get_attributes_by_ids(self, attribute_ids: Sequence[int]) -> dict[int, Attribute]:
        if not attribute_ids:
            return {}
        query = select(Attribute).where(Attribute.id.in_(attribute_ids))
        return {item.id: item for item in (await self.session.execute(query)).scalars().all()}

    async def get_options_by_ids(self, option_ids: Sequence[int]) -> dict[int, AttributeOption]:
        if not option_ids:
            return {}
        query = select(AttributeOption).where(AttributeOption.id.in_(option_ids))
        return {item.id: item for item in (await self.session.execute(query)).scalars().all()}

    async def replace_categories(self, product_id: int, links: Sequence[ProductCategory]) -> None:
        await self.session.execute(
            delete(ProductCategory).where(ProductCategory.product_id == product_id)
        )
        for link in links:
            self.session.add(link)
        await self.session.flush()

    async def replace_attribute_values(
        self, product_id: int, values: Sequence[ProductAttributeValue]
    ) -> None:
        await self.session.execute(
            delete(ProductAttributeValue).where(ProductAttributeValue.product_id == product_id)
        )
        for value in values:
            self.session.add(value)
        await self.session.flush()

    # ------------------------------------------------ пакетные операции
    # Нужны массовому импорту: полная замена связей сотни товаров одним
    # DELETE вместо сотни. Семантика та же, что у replace_* выше —
    # старый набор удаляется целиком, новый добавляет вызывающий код.
    async def delete_categories_for(self, product_ids: Sequence[int]) -> None:
        if product_ids:
            await self.session.execute(
                delete(ProductCategory).where(ProductCategory.product_id.in_(product_ids))
            )

    async def delete_attribute_values_for(self, product_ids: Sequence[int]) -> None:
        if product_ids:
            await self.session.execute(
                delete(ProductAttributeValue).where(
                    ProductAttributeValue.product_id.in_(product_ids)
                )
            )
