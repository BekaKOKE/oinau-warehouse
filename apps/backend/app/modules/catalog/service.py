"""Сборка публичных ответов каталога.

Сервис превращает строки БД в схемы: считает статус наличия, приводит
цену к публичному виду, форматирует характеристики и подставляет
локализованные тексты.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.pagination import Page, PageParams
from app.core.service import BaseService
from app.modules.catalog.enums import AttributeValueType, ProductSort
from app.modules.catalog.models import Category, ProductAttributeValue
from app.modules.catalog.repository import CatalogRepository, ProductFilters, ProductRow
from app.modules.catalog.schemas import (
    CategoryBreadcrumb,
    CategoryDetail,
    CategoryImage,
    CategoryNode,
    CharacteristicRead,
    DocumentRead,
    FacetOptionRead,
    FacetRead,
    ImageRead,
    PriceInfo,
    PriceTierRead,
    ProductColorDetail,
    ProductColorOption,
    ProductDetail,
    ProductListItem,
)
from app.modules.colors.models import ProductColor
from app.modules.colors.repository import ColorRepository
from app.modules.inventory.availability import resolve_availability
from app.modules.media.documents import is_document
from app.modules.media.enums import ImageKind
from app.modules.media.images import VARIANT_MIME
from app.modules.media.urls import primary_size, primary_url, variant_urls
from app.modules.pricing.enums import PricingType
from app.modules.pricing.models import PriceTier

RELATED_PRODUCTS_LIMIT = 8
# Роли привязки, которые показываются блоком «Схема / чертёж», а не в галерее.
DOCUMENT_KINDS = frozenset({ImageKind.SCHEME.value, ImageKind.DRAWING.value})

# Подписи булевых характеристик. Отдельная таблица переводов ради двух
# слов не нужна, но и «true» на витрине показывать нельзя.
BOOLEAN_LABELS: dict[str, tuple[str, str]] = {
    "ru": ("Да", "Нет"),
    "kk": ("Иә", "Жоқ"),
}


def resolve_locale(requested: str | None) -> tuple[str, str]:
    """Возвращает (запрошенная локаль, локаль запасного варианта).

    Неподдерживаемая локаль не считается ошибкой: посетитель с
    `Accept-Language: en` должен увидеть каталог, а не 400. Запрос
    молча обслуживается локалью по умолчанию.

    Разделение на две локали позволяет добавить казахский, не трогая
    ни один эндпоинт: строки без перевода автоматически покажутся
    по-русски, пока переводы не заполнены.
    """
    fallback = settings.DEFAULT_LOCALE
    if requested and requested in settings.SUPPORTED_LOCALES:
        return requested, fallback
    return fallback, fallback


def _localized(mapping: dict[str, Any], locale: str, fallback: str) -> str | None:
    value = mapping.get(locale) or mapping.get(fallback)
    return str(value) if value is not None else None


def _shift_price(price: PriceInfo, delta: Decimal) -> PriceInfo:
    """Цена в цвете: надбавка прибавляется к каждой ступени и границе.

    Тот же сдвиг делает заявка (`app/modules/colors/pricing.py`), поэтому
    витрина показывает ровно то, что зафиксирует снапшот.
    """
    if not delta or price.type is PricingType.ON_REQUEST:
        return price

    def shift(value: Decimal | None) -> Decimal | None:
        return value + delta if value is not None else None

    return price.model_copy(
        update={
            "price": shift(price.price),
            "from_price": shift(price.from_price),
            "to_price": shift(price.to_price),
            "tiers": [
                tier.model_copy(update={"price": tier.price + delta}) for tier in price.tiers
            ],
        }
    )


def _format_number(value: Decimal) -> str:
    """16.000 -> «16», 16.500 -> «16.5». Хвостовые нули на витрине лишние."""
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return f"{normalized:f}"


class CatalogService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = CatalogRepository(session)
        self.colors = ColorRepository(session)

    # -------------------------------------------------------------- категории
    async def get_category_tree(self, locale: str, fallback: str) -> list[CategoryNode]:
        categories = await self.repository.list_visible_categories()
        counts = await self.repository.count_products_by_category()

        nodes: dict[int, CategoryNode] = {}
        for category in categories:
            nodes[category.id] = CategoryNode(
                slug=category.slug,
                name=self._category_name(category, locale, fallback),
                depth=category.depth,
                image=self._category_image(category),
                product_count=counts.get(category.id, 0),
                children=[],
            )

        roots: list[CategoryNode] = []
        visible_ids = {category.id for category in categories}
        for category in categories:
            node = nodes[category.id]
            # Категория, чей родитель скрыт или удалён, всплывает
            # в корень: иначе она пропала бы из дерева целиком.
            if category.parent_id is not None and category.parent_id in visible_ids:
                nodes[category.parent_id].children.append(node)
            else:
                roots.append(node)
        return roots

    async def get_category(self, slug: str, locale: str, fallback: str) -> CategoryDetail:
        category = await self.repository.get_category_by_slug(slug)
        if category is None:
            raise NotFoundError("Категория не найдена")

        ancestors = await self.repository.get_category_ancestors(category)
        tree = await self.repository.list_visible_categories()
        counts = await self.repository.count_products_by_category()
        children = [
            CategoryNode(
                slug=child.slug,
                name=self._category_name(child, locale, fallback),
                depth=child.depth,
                image=self._category_image(child),
                product_count=counts.get(child.id, 0),
            )
            for child in tree
            if child.parent_id == category.id
        ]

        translation = self._category_translation(category, locale, fallback)
        return CategoryDetail(
            slug=category.slug,
            name=self._category_name(category, locale, fallback),
            description=translation.description if translation else None,
            image=self._category_image(category),
            product_count=counts.get(category.id, 0),
            seo_title=translation.seo_title if translation else None,
            seo_description=translation.seo_description if translation else None,
            breadcrumbs=[
                CategoryBreadcrumb(slug=item.slug, name=self._category_name(item, locale, fallback))
                for item in ancestors
            ],
            children=children,
        )

    def _category_image(self, category: Category) -> CategoryImage | None:
        """Обложка раздела или None.

        Только READY-файл с вариантами: ссылка на неготовый вела бы
        в 404. Правило то же, что у изображений товара.
        """
        url = primary_url(category.image_media)
        if url is None:
            return None
        width, height = primary_size(category.image_media)
        return CategoryImage(
            url=url,
            width=width,
            height=height,
            variants=variant_urls(category.image_media),
        )

    def _category_translation(self, category: Category, locale: str, fallback: str) -> Any:
        by_locale = {item.locale: item for item in category.translations}
        return by_locale.get(locale) or by_locale.get(fallback)

    def _category_name(self, category: Category, locale: str, fallback: str) -> str:
        translation = self._category_translation(category, locale, fallback)
        return translation.name if translation else category.slug

    # ---------------------------------------------------------------- товары
    async def list_products(
        self,
        *,
        filters: ProductFilters,
        sort: ProductSort,
        params: PageParams,
        locale: str,
        fallback: str,
    ) -> Page[ProductListItem]:
        price_list = await self.repository.get_public_price_list()
        rows, total = await self.repository.list_products(
            filters=filters,
            sort=sort,
            params=params,
            locale=locale,
            fallback_locale=fallback,
            price_list_id=price_list.id if price_list else None,
        )
        currency = price_list.currency if price_list else settings.DEFAULT_CURRENCY
        product_ids = [row.product.id for row in rows]
        tiers = await self.repository.get_price_tiers_for(
            product_ids, price_list.id if price_list else None
        )
        colors = await self.colors.colors_for_products(product_ids)
        items = [
            self._to_list_item(
                row,
                currency,
                locale,
                fallback,
                tiers.get(row.product.id, []),
                colors.get(row.product.id, []),
            )
            for row in rows
        ]
        return Page.create(items, total, params)

    async def get_category_facets(self, slug: str, locale: str, fallback: str) -> list[FacetRead]:
        rows = await self.repository.get_category_facets(slug)
        if rows is None:
            raise NotFoundError("Категория не найдена")
        facets: dict[str, FacetRead] = {}
        for row in rows:
            facet = facets.get(row.code)
            if facet is None:
                facet = FacetRead(
                    code=row.code,
                    name=_localized(row.name_i18n, locale, fallback) or row.code,
                    unit=row.unit,
                )
                facets[row.code] = facet
            facet.options.append(
                FacetOptionRead(
                    slug=row.option_slug,
                    name=_localized(row.option_i18n, locale, fallback) or row.option_slug,
                    count=row.count,
                )
            )
        return list(facets.values())

    async def get_product(self, slug: str, locale: str, fallback: str) -> ProductDetail:
        price_list = await self.repository.get_public_price_list()
        price_list_id = price_list.id if price_list else None
        currency = price_list.currency if price_list else settings.DEFAULT_CURRENCY

        row = await self.repository.get_product_by_slug(
            slug, locale=locale, fallback_locale=fallback, price_list_id=price_list_id
        )
        if row is None:
            raise NotFoundError("Товар не найден")

        product = row.product
        tiers = await self.repository.get_price_tiers(product.id, price_list_id)
        price = self._build_price(row, tiers, currency)
        colors = (await self.colors.colors_for_products([product.id])).get(product.id, [])

        categories = [
            CategoryBreadcrumb(
                slug=link.category.slug,
                name=self._category_name(link.category, locale, fallback),
            )
            for link in product.categories
            if link.category.is_active and link.category.deleted_at is None
        ]
        primary_link = next((link for link in product.categories if link.is_primary), None)
        breadcrumbs: list[CategoryBreadcrumb] = []
        if primary_link is not None and primary_link.category.deleted_at is None:
            ancestors = await self.repository.get_category_ancestors(primary_link.category)
            breadcrumbs = [
                CategoryBreadcrumb(slug=item.slug, name=self._category_name(item, locale, fallback))
                for item in [*ancestors, primary_link.category]
            ]

        return ProductDetail(
            sku=product.sku,
            slug=product.slug,
            name=row.name,
            short_description=row.short_description,
            description=row.description,
            brand=product.brand,
            unit=product.unit,
            min_order_qty=product.min_order_qty,
            is_featured=product.is_featured,
            price=price,
            availability=resolve_availability(
                pricing_type=product.pricing_type,
                stock_display_override=product.stock_display_override,
                available_quantity=row.available_quantity,
            ),
            colors=[
                ProductColorDetail(
                    **self._color_option(row, item).model_dump(),
                    price=_shift_price(price, item.price_delta),
                )
                for item in colors
            ],
            breadcrumbs=breadcrumbs,
            categories=categories,
            images=self._build_images(row, locale, fallback),
            documents=self._build_documents(row),
            characteristics=self._build_characteristics(product.attribute_values, locale, fallback),
            specs={str(key): str(value) for key, value in (product.specs or {}).items()},
            seo_title=row.seo_title,
            seo_description=row.seo_description,
        )

    async def get_related_products(
        self, slug: str, locale: str, fallback: str
    ) -> list[ProductListItem]:
        price_list = await self.repository.get_public_price_list()
        price_list_id = price_list.id if price_list else None
        currency = price_list.currency if price_list else settings.DEFAULT_CURRENCY

        row = await self.repository.get_product_by_slug(
            slug, locale=locale, fallback_locale=fallback, price_list_id=price_list_id
        )
        if row is None:
            raise NotFoundError("Товар не найден")

        category_ids = [
            link.category_id
            for link in row.product.categories
            if link.category.is_active and link.category.deleted_at is None
        ]
        related = await self.repository.get_related_products(
            product=row.product,
            category_ids=category_ids,
            limit=RELATED_PRODUCTS_LIMIT,
            locale=locale,
            fallback_locale=fallback,
            price_list_id=price_list_id,
        )
        product_ids = [item.product.id for item in related]
        tiers = await self.repository.get_price_tiers_for(product_ids, price_list_id)
        colors = await self.colors.colors_for_products(product_ids)
        return [
            self._to_list_item(
                item,
                currency,
                locale,
                fallback,
                tiers.get(item.product.id, []),
                colors.get(item.product.id, []),
            )
            for item in related
        ]

    # ------------------------------------------------------------- сборка
    def _to_list_item(
        self,
        row: ProductRow,
        currency: str,
        locale: str,
        fallback: str,
        tiers: list[PriceTier] | None = None,
        colors: list[ProductColor] | None = None,
    ) -> ProductListItem:
        images = self._build_images(row, locale, fallback)
        return ProductListItem(
            sku=row.product.sku,
            slug=row.product.slug,
            name=row.name,
            short_description=row.short_description,
            unit=row.product.unit,
            min_order_qty=row.product.min_order_qty,
            is_featured=row.product.is_featured,
            price=self._build_price(row, tiers=tiers, currency=currency),
            availability=resolve_availability(
                pricing_type=row.product.pricing_type,
                stock_display_override=row.product.stock_display_override,
                available_quantity=row.available_quantity,
            ),
            image=next((image for image in images if image.is_main), None)
            or (images[0] if images else None),
            characteristics=self._build_characteristics(
                list(row.product.attribute_values), locale, fallback
            ),
            specs={str(key): str(value) for key, value in (row.product.specs or {}).items()},
            colors=[self._color_option(row, item) for item in colors or []],
        )

    def _color_option(self, row: ProductRow, item: ProductColor) -> ProductColorOption:
        """Цвет для витрины: статус считает тот же resolver — по остатку цвета.

        Ручное переопределение наличия и «по запросу» у товара действуют
        и на все его цвета.
        """
        return ProductColorOption(
            code=item.color.code,
            name=item.color.name,
            hex=item.color.hex,
            availability=resolve_availability(
                pricing_type=row.product.pricing_type,
                stock_display_override=row.product.stock_display_override,
                available_quantity=item.quantity,
            ),
        )

    def _build_price(
        self, row: ProductRow, tiers: list[PriceTier] | None, currency: str
    ) -> PriceInfo:
        """Публичное представление цены.

        Ступени загружаются одним запросом на страницу списка
        (`get_price_tiers_for`): таблица товаров раздела показывает цены
        по количеству прямо в строке.
        """
        pricing_type = PricingType(row.product.pricing_type)

        if pricing_type is PricingType.ON_REQUEST or row.min_price is None:
            # Товар без цены в публичном прайсе показывается как
            # «по запросу», даже если помечен иначе: показать пустое
            # место вместо цены хуже, чем честную кнопку запроса.
            return PriceInfo(type=PricingType.ON_REQUEST, currency=currency)

        tier_reads = [
            PriceTierRead(
                min_quantity=tier.min_qty,
                max_quantity=tier.max_qty,
                price=tier.price,
            )
            for tier in (tiers or [])
        ]

        return PriceInfo(
            type=pricing_type,
            currency=currency,
            price=row.min_price if pricing_type is PricingType.FIXED else None,
            from_price=row.min_price,
            to_price=row.max_price if row.max_price != row.min_price else None,
            tiers=tier_reads,
        )

    def _build_images(self, row: ProductRow, locale: str, fallback: str) -> list[ImageRead]:
        """Изображения, реально доступные через CDN.

        Только READY: файлы в PENDING/PROCESSING/FAILED пропускаются —
        ссылка на них вела бы в 404. Ссылки строятся общим правилом
        медиатеки (app/modules/media/urls.py): на публичные варианты,
        а не на приватный оригинал.
        """
        images: list[ImageRead] = []
        for link in sorted(row.product.images, key=lambda item: (item.sort_order, item.id)):
            media = link.media_file
            # Схемы и документы — отдельный блок (`_build_documents`).
            if link.kind in DOCUMENT_KINDS or is_document(media.mime_type):
                continue
            url = primary_url(media)
            if url is None:
                continue
            width, height = primary_size(media)
            images.append(
                ImageRead(
                    url=url,
                    kind=link.kind,
                    alt=_localized(link.alt_i18n or {}, locale, fallback),
                    is_main=link.is_main,
                    width=width,
                    height=height,
                    variants=variant_urls(media),
                )
            )
        return images

    def _build_documents(self, row: ProductRow) -> list[DocumentRead]:
        """Схемы и чертежи: документы (PDF, DWG, DXF) и изображения-схемы."""
        documents: list[DocumentRead] = []
        for link in sorted(row.product.images, key=lambda item: (item.sort_order, item.id)):
            media = link.media_file
            document = is_document(media.mime_type)
            if not document and link.kind not in DOCUMENT_KINDS:
                continue
            url = primary_url(media)
            if url is None:
                continue
            variants = variant_urls(media)
            documents.append(
                DocumentRead(
                    url=url,
                    kind=link.kind,
                    filename=media.original_filename,
                    # Отдаётся то, что лежит по ссылке: у изображения —
                    # WebP-вариант, у документа — копия оригинала.
                    content_type=media.mime_type if document else VARIANT_MIME,
                    size_bytes=media.size_bytes if document else None,
                    preview_url=None if document else (variants.get("medium") or url),
                )
            )
        return documents

    def _build_characteristics(
        self, values: list[ProductAttributeValue], locale: str, fallback: str
    ) -> list[CharacteristicRead]:
        result: list[CharacteristicRead] = []
        for value in values:
            attribute = value.attribute
            if attribute is None or not attribute.is_visible or not attribute.is_active:
                continue

            rendered = self._render_value(value, locale, fallback)
            if rendered is None:
                continue

            result.append(
                CharacteristicRead(
                    code=attribute.code,
                    name=_localized(attribute.name_i18n or {}, locale, fallback) or attribute.code,
                    value=rendered,
                )
            )

        result.sort(key=lambda item: item.name)
        return result

    def _render_value(self, value: ProductAttributeValue, locale: str, fallback: str) -> str | None:
        """Готовая к выводу строка: число уже склеено с единицей измерения."""
        attribute = value.attribute
        value_type = AttributeValueType(attribute.value_type)

        if value_type is AttributeValueType.OPTION:
            if value.option is None:
                return None
            return _localized(value.option.value_i18n or {}, locale, fallback)

        if value_type is AttributeValueType.NUMBER:
            if value.value_numeric is None:
                return None
            rendered = _format_number(value.value_numeric)
            return f"{rendered} {attribute.unit}" if attribute.unit else rendered

        if value_type is AttributeValueType.BOOLEAN:
            if value.value_bool is None:
                return None
            yes, no = BOOLEAN_LABELS.get(locale, BOOLEAN_LABELS[settings.DEFAULT_LOCALE])
            return yes if value.value_bool else no

        return value.value_string
