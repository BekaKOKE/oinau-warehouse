"""Запросы публичного каталога.

Все выборки здесь по определению видят только то, что можно показать
посетителю: опубликованные, активные и не удалённые записи. Фильтр
задаётся один раз в `_visible_products()` — если бы он повторялся
в каждом методе, рано или поздно кто-то бы его забыл, и черновик товара
попал бы на витрину.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.orm import aliased, joinedload, selectinload
from sqlalchemy.sql.elements import UnaryExpression

from app.core.pagination import PageParams
from app.core.repository import BaseRepository
from app.modules.catalog.enums import AttributeValueType, ProductSort
from app.modules.catalog.models import (
    Attribute,
    AttributeOption,
    Category,
    CategoryTranslation,
    Product,
    ProductAttributeValue,
    ProductCategory,
    ProductTranslation,
)
from app.modules.catalog.visibility import public_visibility_clause
from app.modules.inventory.models import Stock, Warehouse
from app.modules.media.models import ProductImage
from app.modules.pricing.models import PriceList, PriceTier

# Конфигурация полнотекстового поиска. Совпадает с той, что зашита
# в генерируемую колонку product_translations.search_vector: иначе
# запрос и индекс разбирали бы слова по разным правилам.
FTS_CONFIG = "russian"

# Длина поискового запроса ограничена: строка уходит в ILIKE
# с trigram-индексом, и очень длинный шаблон превращает поиск
# в дорогое сканирование.
MAX_SEARCH_LENGTH = 100


@dataclass(frozen=True)
class ProductFilters:
    category_slug: str | None = None
    search: str | None = None
    availability: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    featured: bool | None = None
    # Фильтр по характеристикам типа OPTION: (код, (slug варианта, ...)).
    # Разные характеристики — «И», варианты одной — «ИЛИ».
    attributes: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class FacetRow:
    code: str
    name_i18n: dict[str, Any]
    unit: str | None
    option_slug: str
    option_i18n: dict[str, Any]
    count: int


@dataclass(frozen=True)
class ProductRow:
    """Товар вместе с вычисленными на стороне БД полями.

    Цена и остаток приходят агрегатами из подзапросов, а не отдельными
    обращениями на каждый товар — иначе страница каталога из 24 позиций
    давала бы полсотни запросов.
    """

    product: Product
    name: str
    short_description: str | None
    description: str | None
    seo_title: str | None
    seo_description: str | None
    min_price: Decimal | None
    max_price: Decimal | None
    available_quantity: Decimal | None


class CatalogRepository(BaseRepository[Product]):
    model = Product

    # ------------------------------------------------------------ прайс-лист
    async def get_public_price_list(self) -> PriceList | None:
        """Публичный прайс-лист — тот, что помечен как основной.

        Дилерские и партнёрские прайсы наружу не попадают никогда:
        публичный API просто не знает об их существовании.
        """
        query = select(PriceList).where(
            PriceList.is_default.is_(True), PriceList.is_active.is_(True)
        )
        return (await self.session.execute(query)).scalars().first()

    # -------------------------------------------------------------- категории
    async def list_visible_categories(self) -> list[Category]:
        query = (
            select(Category)
            .where(Category.deleted_at.is_(None), Category.is_active.is_(True))
            .options(selectinload(Category.translations), joinedload(Category.image_media))
            .order_by(Category.depth, Category.sort_order, Category.id)
        )
        return list((await self.session.execute(query)).scalars().all())

    async def count_products_by_category(self) -> dict[int, int]:
        """Сколько видимых товаров показывает страница каждой категории.

        Считается вся ветка: у категории «Комплектующие» в счётчике
        и её собственные товары, и товары «Канатов» с «Креплениями» —
        ровно то, что посетитель увидит, открыв её. То же правило, что
        в `_category_product_ids()`, иначе счётчик на карточке расходился
        бы с числом позиций на странице.

        COUNT(DISTINCT), а не сумма по подкатегориям: товар, привязанный
        сразу к разделу и к подразделу, — это одна позиция в выдаче.
        """
        descendant = aliased(Category)
        query = (
            select(Category.id, func.count(func.distinct(ProductCategory.product_id)))
            .join(
                descendant,
                and_(
                    descendant.deleted_at.is_(None),
                    descendant.is_active.is_(True),
                    or_(
                        descendant.id == Category.id,
                        descendant.path.like(Category.path + ".%"),
                    ),
                ),
            )
            .join(ProductCategory, ProductCategory.category_id == descendant.id)
            .join(Product, Product.id == ProductCategory.product_id)
            .where(
                Category.deleted_at.is_(None),
                Category.is_active.is_(True),
                self._visible_products(),
            )
            .group_by(Category.id)
        )
        rows = (await self.session.execute(query)).all()
        return {int(category_id): int(total) for category_id, total in rows}

    async def get_category_by_slug(self, slug: str) -> Category | None:
        query = (
            select(Category)
            .where(
                Category.slug == slug,
                Category.deleted_at.is_(None),
                Category.is_active.is_(True),
            )
            .options(selectinload(Category.translations), joinedload(Category.image_media))
        )
        return (await self.session.execute(query)).scalars().first()

    async def get_category_ancestors(self, category: Category) -> list[Category]:
        """Хлебные крошки из материализованного пути — одним запросом.

        Путь вида "1.14.37" уже содержит всех предков, поэтому рекурсивный
        обход дерева не нужен.
        """
        ancestor_ids = [int(part) for part in category.path.split(".") if part.isdigit()]
        ancestor_ids = [item for item in ancestor_ids if item != category.id]
        if not ancestor_ids:
            return []

        query = (
            select(Category)
            .where(
                Category.id.in_(ancestor_ids),
                Category.deleted_at.is_(None),
                Category.is_active.is_(True),
            )
            .options(selectinload(Category.translations))
            .order_by(Category.depth)
        )
        return list((await self.session.execute(query)).scalars().all())

    # ---------------------------------------------------------------- товары
    def _visible_products(self) -> ColumnElement[bool]:
        # Правило описано один раз в app/modules/catalog/visibility.py:
        # админка показывает признак публичности по тому же условию.
        return public_visibility_clause()

    def _price_aggregate(self, price_list_id: int | None) -> Any:
        """Мин/макс цена товара по публичному прайс-листу."""
        query = select(
            PriceTier.product_id.label("product_id"),
            func.min(PriceTier.price).label("min_price"),
            func.max(PriceTier.price).label("max_price"),
        ).group_by(PriceTier.product_id)
        # price_list_id = None означает, что публичный прайс не заведён:
        # подзапрос обязан вернуть пусто, а не цены всех прайс-листов.
        query = query.where(PriceTier.price_list_id == price_list_id)
        return query.subquery("price_agg")

    def _stock_aggregate(self) -> Any:
        """Свободный остаток по активным складам.

        Наружу это число не попадает — оно нужно только для вычисления
        статуса наличия и фильтра «в наличии».
        """
        return (
            select(
                Stock.product_id.label("product_id"),
                func.sum(Stock.quantity - Stock.reserved).label("available"),
            )
            .join(Warehouse, Warehouse.id == Stock.warehouse_id)
            .where(Warehouse.is_active.is_(True))
            .group_by(Stock.product_id)
            .subquery("stock_agg")
        )

    async def _category_product_ids(self, slug: str) -> Select[tuple[int]] | None:
        """Товары категории и всех её подкатегорий.

        Фильтр по материализованному пути: страница «Комплектующие»
        обязана показывать товары из «Канатов» и «Креплений», иначе
        верхние разделы каталога окажутся пустыми.
        """
        category = await self.get_category_by_slug(slug)
        if category is None:
            return None

        return select(ProductCategory.product_id).join(
            Category,
            and_(
                Category.id == ProductCategory.category_id,
                Category.deleted_at.is_(None),
                Category.is_active.is_(True),
                or_(
                    Category.id == category.id,
                    Category.path.like(f"{category.path}.%"),
                ),
            ),
        )

    async def list_products(
        self,
        *,
        filters: ProductFilters,
        sort: ProductSort,
        params: PageParams,
        locale: str,
        fallback_locale: str,
        price_list_id: int | None,
    ) -> tuple[list[ProductRow], int]:
        primary = aliased(ProductTranslation)
        fallback = aliased(ProductTranslation)
        price_agg = self._price_aggregate(price_list_id)
        stock_agg = self._stock_aggregate()

        name_expr = func.coalesce(primary.name, fallback.name)
        short_expr = func.coalesce(primary.short_description, fallback.short_description)

        base = (
            select(Product)
            .outerjoin(
                primary,
                and_(primary.product_id == Product.id, primary.locale == locale),
            )
            .outerjoin(
                fallback,
                and_(fallback.product_id == Product.id, fallback.locale == fallback_locale),
            )
            .outerjoin(price_agg, price_agg.c.product_id == Product.id)
            .outerjoin(stock_agg, stock_agg.c.product_id == Product.id)
            .where(self._visible_products())
        )

        if filters.category_slug:
            category_ids = await self._category_product_ids(filters.category_slug)
            if category_ids is None:
                return [], 0
            base = base.where(Product.id.in_(category_ids))

        if filters.featured is not None:
            base = base.where(Product.is_featured.is_(filters.featured))

        if filters.min_price is not None:
            base = base.where(price_agg.c.min_price >= filters.min_price)
        if filters.max_price is not None:
            base = base.where(price_agg.c.min_price <= filters.max_price)

        if filters.availability:
            base = base.where(self._availability_filter(filters.availability, stock_agg))

        for code, slugs in filters.attributes:
            base = base.where(Product.id.in_(self._attribute_filter(code, slugs)))

        # Пустая или состоящая из пробелов строка поиска — это отсутствие
        # поиска, а не поиск по пустой строке: websearch_to_tsquery('')
        # не совпадёт ни с чем и молча вернул бы пустую выдачу.
        search_term = (filters.search or "").strip()

        rank: ColumnElement[float] | None = None
        if search_term:
            base, rank = self._apply_search(base, search_term, primary, fallback)

        total = (
            await self.session.execute(
                select(func.count()).select_from(base.with_only_columns(Product.id).subquery())
            )
        ).scalar_one()

        query = (
            base.add_columns(
                name_expr.label("name"),
                short_expr.label("short_description"),
                price_agg.c.min_price,
                price_agg.c.max_price,
                stock_agg.c.available,
            )
            .order_by(*self._order_by(sort, name_expr, price_agg, rank))
            .limit(params.limit)
            .offset(params.offset)
            .options(
                selectinload(Product.images).joinedload(ProductImage.media_file),
                # Характеристики — для колонок таблицы товаров раздела.
                selectinload(Product.attribute_values).joinedload(ProductAttributeValue.attribute),
                selectinload(Product.attribute_values).joinedload(ProductAttributeValue.option),
            )
        )

        rows = (await self.session.execute(query)).all()
        return [
            ProductRow(
                product=row[0],
                name=row.name or row[0].sku,
                short_description=row.short_description,
                description=None,
                seo_title=None,
                seo_description=None,
                min_price=row.min_price,
                max_price=row.max_price,
                available_quantity=row.available,
            )
            for row in rows
        ], total

    def _attribute_filter(self, code: str, slugs: tuple[str, ...]) -> Select[tuple[int]]:
        """Товары, у которых характеристика `code` принимает один из вариантов."""
        return (
            select(ProductAttributeValue.product_id)
            .join(Attribute, Attribute.id == ProductAttributeValue.attribute_id)
            .join(AttributeOption, AttributeOption.id == ProductAttributeValue.option_id)
            .where(Attribute.code == code, AttributeOption.slug.in_(slugs))
        )

    async def get_category_facets(self, slug: str) -> list[FacetRow] | None:
        """Значения фильтруемых характеристик среди видимых товаров раздела.

        Считается по всей ветке раздела, как и выдача. Только OPTION:
        у вариантов есть стабильный slug для ссылки и счётчик имеет смысл.
        None — раздела нет.
        """
        category_ids = await self._category_product_ids(slug)
        if category_ids is None:
            return None
        count = func.count(func.distinct(ProductAttributeValue.product_id))
        query = (
            select(
                Attribute.code,
                Attribute.name_i18n,
                Attribute.unit,
                AttributeOption.slug,
                AttributeOption.value_i18n,
                count.label("total"),
            )
            .join(Attribute, Attribute.id == ProductAttributeValue.attribute_id)
            .join(AttributeOption, AttributeOption.id == ProductAttributeValue.option_id)
            .join(Product, Product.id == ProductAttributeValue.product_id)
            .where(
                Product.id.in_(category_ids),
                self._visible_products(),
                Attribute.value_type == AttributeValueType.OPTION.value,
                Attribute.is_filterable.is_(True),
                Attribute.is_visible.is_(True),
                Attribute.is_active.is_(True),
            )
            .group_by(
                Attribute.id,
                Attribute.code,
                Attribute.name_i18n,
                Attribute.unit,
                Attribute.sort_order,
                AttributeOption.id,
                AttributeOption.slug,
                AttributeOption.value_i18n,
                AttributeOption.sort_order,
            )
            .order_by(
                Attribute.sort_order,
                Attribute.code,
                AttributeOption.sort_order,
                AttributeOption.slug,
            )
        )
        rows = (await self.session.execute(query)).all()
        return [
            FacetRow(
                code=row.code,
                name_i18n=dict(row.name_i18n or {}),
                unit=row.unit,
                option_slug=row.slug,
                option_i18n=dict(row.value_i18n or {}),
                count=int(row.total),
            )
            for row in rows
        ]

    def _availability_filter(self, availability: str, stock_agg: Any) -> ColumnElement[bool]:
        """Фильтр по наличию повторяет логику resolve_availability().

        Дублирование правил в SQL и в Python неизбежно: вычислять статус
        построчно в приложении нельзя, потому что по нему надо
        фильтровать и считать total. Порядок условий здесь тот же, что
        в `resolve_availability`, и обе ветки закрыты тестами.
        """
        from app.modules.inventory.enums import PublicAvailability
        from app.modules.pricing.enums import PricingType

        on_request = and_(
            Product.stock_display_override.is_(None),
            Product.pricing_type == PricingType.ON_REQUEST.value,
        )
        in_stock = and_(
            Product.stock_display_override.is_(None),
            Product.pricing_type != PricingType.ON_REQUEST.value,
            func.coalesce(stock_agg.c.available, 0) > 0,
        )
        out_of_stock = and_(
            Product.stock_display_override.is_(None),
            Product.pricing_type != PricingType.ON_REQUEST.value,
            func.coalesce(stock_agg.c.available, 0) <= 0,
        )

        overridden = Product.stock_display_override == availability
        by_rules = {
            PublicAvailability.ON_REQUEST.value: on_request,
            PublicAvailability.IN_STOCK.value: in_stock,
            PublicAvailability.OUT_OF_STOCK.value: out_of_stock,
        }[availability]
        return or_(overridden, by_rules)

    def _apply_search(
        self,
        query: Select[Any],
        raw_search: str,
        primary: Any,
        fallback: Any,
    ) -> tuple[Select[Any], ColumnElement[float]]:
        """Полнотекстовый поиск плюс поиск по части артикула и названия.

        Три механизма дополняют друг друга:
          * `search_vector` — морфология: «канаты» находят «канат»;
          * trigram по `sku` — поиск по фрагменту артикула;
          * trigram по названию — устойчивость к опечаткам и к запросам,
            которые FTS отбрасывает как стоп-слова.

        Все три опираются на индексы, созданные на этапе 3; менять схему
        не потребовалось.
        """
        term = raw_search.strip()[:MAX_SEARCH_LENGTH]
        ts_query = func.websearch_to_tsquery(FTS_CONFIG, term)
        vector = func.coalesce(primary.search_vector, fallback.search_vector)
        pattern = f"%{term}%"

        query = query.where(
            or_(
                vector.op("@@")(ts_query),
                Product.sku.ilike(pattern),
                primary.name.ilike(pattern),
                fallback.name.ilike(pattern),
            )
        )
        rank = func.ts_rank_cd(vector, ts_query)
        return query, rank

    def _order_by(
        self,
        sort: ProductSort,
        name_expr: ColumnElement[str],
        price_agg: Any,
        rank: ColumnElement[float] | None,
    ) -> list[UnaryExpression[Any] | ColumnElement[Any]]:
        """ORDER BY строится только из значений белого списка.

        Product.id всегда добавляется последним: без устойчивого
        тай-брейкера соседние страницы могут повторить или потерять
        товар, когда у нескольких позиций совпадает ключ сортировки.
        """
        tiebreaker = Product.id.desc()

        if sort is ProductSort.RELEVANCE:
            if rank is None:
                # Без поискового запроса релевантность бессмысленна —
                # ведём себя как «сначала новые».
                return [Product.is_featured.desc(), Product.created_at.desc(), tiebreaker]
            return [rank.desc(), tiebreaker]

        if sort is ProductSort.NEWEST:
            return [Product.created_at.desc(), tiebreaker]
        if sort is ProductSort.PRICE_ASC:
            # Товары без цены («по запросу») уходят в конец, а не
            # оказываются «самыми дешёвыми».
            return [price_agg.c.min_price.asc().nullslast(), tiebreaker]
        if sort is ProductSort.PRICE_DESC:
            return [price_agg.c.min_price.desc().nullslast(), tiebreaker]
        if sort is ProductSort.SKU:
            return [Product.sku.asc(), tiebreaker]
        return [name_expr.asc().nullslast(), tiebreaker]

    # ------------------------------------------------------------ карточка
    async def get_product_by_slug(
        self, slug: str, *, locale: str, fallback_locale: str, price_list_id: int | None
    ) -> ProductRow | None:
        primary = aliased(ProductTranslation)
        fallback = aliased(ProductTranslation)
        price_agg = self._price_aggregate(price_list_id)
        stock_agg = self._stock_aggregate()

        query = (
            select(
                Product,
                func.coalesce(primary.name, fallback.name).label("name"),
                func.coalesce(primary.short_description, fallback.short_description).label(
                    "short_description"
                ),
                func.coalesce(primary.description, fallback.description).label("description"),
                func.coalesce(primary.seo_title, fallback.seo_title).label("seo_title"),
                func.coalesce(primary.seo_description, fallback.seo_description).label(
                    "seo_description"
                ),
                price_agg.c.min_price,
                price_agg.c.max_price,
                stock_agg.c.available,
            )
            .outerjoin(primary, and_(primary.product_id == Product.id, primary.locale == locale))
            .outerjoin(
                fallback,
                and_(fallback.product_id == Product.id, fallback.locale == fallback_locale),
            )
            .outerjoin(price_agg, price_agg.c.product_id == Product.id)
            .outerjoin(stock_agg, stock_agg.c.product_id == Product.id)
            .where(Product.slug == slug, self._visible_products())
            .options(
                selectinload(Product.images).joinedload(ProductImage.media_file),
                selectinload(Product.attribute_values).joinedload(ProductAttributeValue.attribute),
                selectinload(Product.attribute_values).joinedload(ProductAttributeValue.option),
                selectinload(Product.categories)
                .joinedload(ProductCategory.category)
                .selectinload(Category.translations),
            )
        )

        row = (await self.session.execute(query)).first()
        if row is None:
            return None

        return ProductRow(
            product=row[0],
            name=row.name or row[0].sku,
            short_description=row.short_description,
            description=row.description,
            seo_title=row.seo_title,
            seo_description=row.seo_description,
            min_price=row.min_price,
            max_price=row.max_price,
            available_quantity=row.available,
        )

    async def get_price_tiers(self, product_id: int, price_list_id: int | None) -> list[PriceTier]:
        """Ступени ТОЛЬКО публичного прайс-листа.

        Отдельный запрос, а не выборка через связь `Product.price_tiers`:
        связь подтянула бы и дилерские цены, и дальше всё держалось бы
        на аккуратности фильтрации в Python.
        """
        if price_list_id is None:
            return []
        query = (
            select(PriceTier)
            .where(PriceTier.product_id == product_id, PriceTier.price_list_id == price_list_id)
            .order_by(PriceTier.min_qty)
        )
        return list((await self.session.execute(query)).scalars().all())

    async def get_price_tiers_for(
        self, product_ids: list[int], price_list_id: int | None
    ) -> dict[int, list[PriceTier]]:
        """Ступени публичного прайса для страницы списка — одним запросом."""
        if price_list_id is None or not product_ids:
            return {}
        query = (
            select(PriceTier)
            .where(PriceTier.product_id.in_(product_ids), PriceTier.price_list_id == price_list_id)
            .order_by(PriceTier.product_id, PriceTier.min_qty)
        )
        result: dict[int, list[PriceTier]] = {}
        for tier in (await self.session.execute(query)).scalars().all():
            result.setdefault(tier.product_id, []).append(tier)
        return result

    async def get_related_products(
        self,
        *,
        product: Product,
        category_ids: list[int],
        limit: int,
        locale: str,
        fallback_locale: str,
        price_list_id: int | None,
    ) -> list[ProductRow]:
        """Похожие товары: те же категории, кроме самого товара.

        Никакого движка рекомендаций — на старте достаточно соседей
        по разделу.
        """
        if not category_ids:
            return []

        primary = aliased(ProductTranslation)
        fallback = aliased(ProductTranslation)
        price_agg = self._price_aggregate(price_list_id)
        stock_agg = self._stock_aggregate()

        query = (
            select(
                Product,
                func.coalesce(primary.name, fallback.name).label("name"),
                func.coalesce(primary.short_description, fallback.short_description).label(
                    "short_description"
                ),
                price_agg.c.min_price,
                price_agg.c.max_price,
                stock_agg.c.available,
            )
            .join(ProductCategory, ProductCategory.product_id == Product.id)
            .outerjoin(primary, and_(primary.product_id == Product.id, primary.locale == locale))
            .outerjoin(
                fallback,
                and_(fallback.product_id == Product.id, fallback.locale == fallback_locale),
            )
            .outerjoin(price_agg, price_agg.c.product_id == Product.id)
            .outerjoin(stock_agg, stock_agg.c.product_id == Product.id)
            .where(
                ProductCategory.category_id.in_(category_ids),
                Product.id != product.id,
                self._visible_products(),
            )
            .distinct()
            .order_by(Product.is_featured.desc(), Product.id.desc())
            .limit(limit)
            .options(
                selectinload(Product.images).joinedload(ProductImage.media_file),
                selectinload(Product.attribute_values).joinedload(ProductAttributeValue.attribute),
                selectinload(Product.attribute_values).joinedload(ProductAttributeValue.option),
            )
        )

        rows = (await self.session.execute(query)).all()
        return [
            ProductRow(
                product=row[0],
                name=row.name or row[0].sku,
                short_description=row.short_description,
                description=None,
                seo_title=None,
                seo_description=None,
                min_price=row.min_price,
                max_price=row.max_price,
                available_quantity=row.available,
            )
            for row in rows
        ]


__all__ = [
    "CatalogRepository",
    "CategoryTranslation",
    "FacetRow",
    "ProductFilters",
    "ProductRow",
]
