"""Экспорт каталога в канонический XLSX.

Выгружаются живые (не удалённые) товары и категории, все
характеристики с вариантами, связи и ступени публичного прайс-листа.
Остатки НЕ выгружаются: источник истины по складу — 1С, а не файл.
Ключи файлов медиатеки и прочие внутренние идентификаторы в файл
не попадают.

Порядок строк детерминирован (товары по артикулу, категории от корня
к листьям), поэтому две выгрузки неизменного каталога совпадают
построчно, а выгрузка, возвращённая импортом без правок, не даёт
ни одного изменения.

Данные читаются фиксированным числом запросов, книга собирается в пуле
потоков, чтобы не блокировать событийный цикл.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.modules.catalog.enums import AttributeValueType, ProductStatus
from app.modules.catalog.models import (
    Attribute,
    Category,
    CategoryAttribute,
    Product,
    ProductAttributeValue,
    ProductCategory,
)
from app.modules.imports.validator import (
    CATEGORY_TEXTS,
    PRODUCT_TEXTS,
    current_category_slugs,
)
from app.modules.imports.xlsx_format import (
    COMMENT_PREFIX,
    FORMAT_VERSION,
    LIST_SEPARATOR,
    Sheet,
    SheetSpec,
    build_sheet_specs,
)
from app.modules.imports.xlsx_writer import write_workbook
from app.modules.pricing.enums import PricingType
from app.modules.pricing.models import PriceList
from app.modules.pricing.repository_admin import AdminPricingRepository

Rows = list[list[Any]]


def export_filename(prefix: str = "oinau-catalog") -> str:
    return f"{prefix}-{datetime.now(UTC):%Y%m%d-%H%M%S}.xlsx"


def _choices() -> dict[str, dict[str, list[str]]]:
    return {
        Sheet.PRODUCTS: {
            "status": [item.value for item in ProductStatus],
            "pricing_type": [item.value for item in PricingType],
        },
        Sheet.ATTRIBUTES: {"value_type": [item.value for item in AttributeValueType]},
    }


def build_readme(price_list: PriceList | None, generated_at: datetime | None) -> list[str]:
    currency = price_list.currency if price_list is not None else settings.DEFAULT_CURRENCY
    lines = [
        f"Каталог OINAU PRO — формат XLSX, версия {FORMAT_VERSION}",
        (
            f"Выгружено: {generated_at:%Y-%m-%d %H:%M} UTC"
            if generated_at
            else "Шаблон для заполнения"
        ),
        f"Валюта цен: {currency} (публичный прайс-лист)",
        "",
        "КАК РАБОТАЕТ ИМПОРТ",
        "1. Выгрузите каталог, отредактируйте файл и загрузите его на предпросмотр.",
        "2. Предпросмотр ничего не меняет: он показывает ошибки (лист, строка, колонка) "
        "и что будет создано или изменено.",
        "3. Подтверждение применяет весь файл одной транзакцией: либо всё, либо ничего.",
        "",
        "КЛЮЧИ",
        "Товар — sku (артикул). Существующий артикул — обновление, новый — создание. "
        "Артикул через импорт не переименовывается: новый артикул = новый товар.",
        "Категория — slug, характеристика — code, вариант значения — attribute_code + slug.",
        "",
        "ПРАВИЛА",
        "Импорт ничего не удаляет: строки, которых нет в файле, остаются как есть.",
        "Для товаров из листа Products их категории, цены (Prices), характеристики "
        "(ProductAttributes) и описательные характеристики (ProductSpecs) заменяются "
        "целиком: удалите строку — удалится значение.",
        "Для категорий из листа Categories так же заменяются фильтры (CategoryAttributes).",
        f"categories — slug категорий через «{LIST_SEPARATOR}», первая — основная.",
        "Логические значения: TRUE/FALSE (также 1/0, да/нет).",
        "Цены — до 2 знаков после запятой, количества — до 3. Формулы не принимаются: "
        "вставляйте значения.",
        "pricing_type: FIXED — одна ступень от 1 без верхней границы; FROM и TIERED — "
        "ступени без пересечений (не больше 20); ON_REQUEST — без ступеней. "
        "Пустой max_qty — «и выше».",
        "Тексты — простой текст без HTML.",
        f"Колонки с заголовком, начинающимся с «{COMMENT_PREFIX}», считаются пометками и "
        "не импортируются. Другие неизвестные колонки — ошибка.",
        "",
        "ОСТАТКИ",
        "Остатки на складах через Excel не выгружаются и не загружаются: их источник — 1С.",
    ]
    return lines


class CatalogExportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.pricing = AdminPricingRepository(session)

    @property
    def specs(self) -> dict[str, SheetSpec]:
        return build_sheet_specs(settings.SUPPORTED_LOCALES, settings.DEFAULT_LOCALE)

    @property
    def locales(self) -> list[str]:
        default = settings.DEFAULT_LOCALE
        return [default, *[item for item in settings.SUPPORTED_LOCALES if item != default]]

    async def export_catalog(self) -> bytes:
        price_list = await self.pricing.get_default_price_list()
        products = await self._products()
        tiers = (
            await self.pricing.list_tiers_for([item.id for item in products], price_list.id)
            if price_list is not None
            else {}
        )
        categories = await self._categories()
        links = await self._category_links()
        attributes = await self._attributes()

        specs = self.specs
        sheets: list[tuple[SheetSpec, Sequence[Sequence[Any]]]] = [
            (specs[Sheet.PRODUCTS], self._product_rows(specs[Sheet.PRODUCTS], products)),
            (specs[Sheet.PRICES], self._price_rows(products, tiers)),
            (specs[Sheet.PRODUCT_ATTRIBUTES], self._value_rows(products)),
            (specs[Sheet.PRODUCT_SPECS], self._spec_rows(products)),
            (specs[Sheet.CATEGORIES], self._category_rows(specs[Sheet.CATEGORIES], categories)),
            (specs[Sheet.CATEGORY_ATTRIBUTES], self._link_rows(categories, links)),
            (specs[Sheet.ATTRIBUTES], self._attribute_rows(specs[Sheet.ATTRIBUTES], attributes)),
            (
                specs[Sheet.ATTRIBUTE_OPTIONS],
                self._option_rows(specs[Sheet.ATTRIBUTE_OPTIONS], attributes),
            ),
        ]
        readme = build_readme(price_list, datetime.now(UTC))
        return await run_in_threadpool(write_workbook, sheets, readme=readme, choices=_choices())

    async def template(self) -> bytes:
        """Пустая книга канонического формата — для заполнения с нуля."""
        price_list = await self.pricing.get_default_price_list()
        sheets: list[tuple[SheetSpec, Sequence[Sequence[Any]]]] = [
            (spec, []) for spec in self.specs.values()
        ]
        readme = build_readme(price_list, None)
        return await run_in_threadpool(write_workbook, sheets, readme=readme, choices=_choices())

    # --------------------------------------------------------------- чтение
    async def _products(self) -> Sequence[Product]:
        query = (
            select(Product)
            .where(Product.deleted_at.is_(None))
            .options(
                selectinload(Product.translations),
                selectinload(Product.categories).joinedload(ProductCategory.category),
                selectinload(Product.attribute_values).joinedload(ProductAttributeValue.attribute),
                selectinload(Product.attribute_values).joinedload(ProductAttributeValue.option),
            )
            .order_by(Product.sku)
        )
        return (await self.session.execute(query)).scalars().unique().all()

    async def _categories(self) -> Sequence[Category]:
        query = (
            select(Category)
            .where(Category.deleted_at.is_(None))
            .options(selectinload(Category.translations))
            .order_by(Category.depth, Category.sort_order, Category.slug)
        )
        return (await self.session.execute(query)).scalars().all()

    async def _category_links(self) -> dict[int, list[tuple[str, int, bool]]]:
        rows = await self.session.execute(
            select(
                CategoryAttribute.category_id,
                Attribute.code,
                CategoryAttribute.sort_order,
                CategoryAttribute.is_required,
            )
            .join(Attribute, Attribute.id == CategoryAttribute.attribute_id)
            .order_by(CategoryAttribute.category_id, CategoryAttribute.sort_order, Attribute.code)
        )
        result: dict[int, list[tuple[str, int, bool]]] = {}
        for category_id, code, sort_order, is_required in rows.all():
            result.setdefault(category_id, []).append((code, sort_order, is_required))
        return result

    async def _attributes(self) -> Sequence[Attribute]:
        query = (
            select(Attribute)
            .options(selectinload(Attribute.options))
            .order_by(Attribute.sort_order, Attribute.code)
        )
        return (await self.session.execute(query)).scalars().all()

    # ---------------------------------------------------------------- строки
    def _row(self, spec: SheetSpec, values: dict[str, Any]) -> list[Any]:
        return [values.get(name) for name in spec.column_names]

    def _product_rows(self, spec: SheetSpec, products: Sequence[Product]) -> Rows:
        rows: Rows = []
        for product in products:
            values: dict[str, Any] = {
                "sku": product.sku,
                "slug": product.slug,
                "status": product.status,
                "is_active": product.is_active,
                "is_featured": product.is_featured,
                "categories": f"{LIST_SEPARATOR} ".join(current_category_slugs(product)) or None,
                "unit": product.unit,
                "min_order_qty": product.min_order_qty,
                "pricing_type": product.pricing_type,
                "brand": product.brand,
                "external_id": product.external_id,
            }
            translations = {item.locale: item for item in product.translations}
            for locale in self.locales:
                translation = translations.get(locale)
                for name in PRODUCT_TEXTS:
                    values[f"{name}_{locale}"] = getattr(translation, name) if translation else None
            rows.append(self._row(spec, values))
        return rows

    def _price_rows(self, products: Sequence[Product], tiers: dict[int, list[Any]]) -> Rows:
        return [
            [product.sku, tier.min_qty, tier.max_qty, tier.price]
            for product in products
            for tier in sorted(tiers.get(product.id, []), key=lambda item: item.min_qty)
        ]

    def _value_rows(self, products: Sequence[Product]) -> Rows:
        rows: Rows = []
        for product in products:
            values = sorted(
                product.attribute_values,
                key=lambda item: (
                    item.attribute.sort_order,
                    item.attribute.code,
                    item.option.sort_order if item.option else 0,
                    item.option.slug if item.option else "",
                    item.id,
                ),
            )
            for item in values:
                if item.option is not None:
                    value: Any = item.option.slug
                elif item.value_numeric is not None:
                    value = item.value_numeric
                elif item.value_bool is not None:
                    value = item.value_bool
                else:
                    value = item.value_string
                rows.append([product.sku, item.attribute.code, value])
        return rows

    def _spec_rows(self, products: Sequence[Product]) -> Rows:
        return [
            [product.sku, str(name), str(value)]
            for product in products
            for name, value in sorted((product.specs or {}).items(), key=lambda item: str(item[0]))
        ]

    def _category_rows(self, spec: SheetSpec, categories: Sequence[Category]) -> Rows:
        by_id = {category.id: category for category in categories}
        rows: Rows = []
        for category in categories:
            parent = by_id.get(category.parent_id) if category.parent_id is not None else None
            values: dict[str, Any] = {
                "slug": category.slug,
                "parent_slug": parent.slug if parent else None,
                "sort_order": category.sort_order,
                "is_active": category.is_active,
                "external_id": category.external_id,
            }
            translations = {item.locale: item for item in category.translations}
            for locale in self.locales:
                translation = translations.get(locale)
                for name in CATEGORY_TEXTS:
                    values[f"{name}_{locale}"] = getattr(translation, name) if translation else None
            rows.append(self._row(spec, values))
        return rows

    def _link_rows(
        self, categories: Sequence[Category], links: dict[int, list[tuple[str, int, bool]]]
    ) -> Rows:
        return [
            [category.slug, code, sort_order, is_required]
            for category in categories
            for code, sort_order, is_required in links.get(category.id, [])
        ]

    def _attribute_rows(self, spec: SheetSpec, attributes: Sequence[Attribute]) -> Rows:
        rows: Rows = []
        for attribute in attributes:
            names = attribute.name_i18n or {}
            values: dict[str, Any] = {
                "code": attribute.code,
                "value_type": attribute.value_type,
                "unit": attribute.unit,
                "is_filterable": attribute.is_filterable,
                "is_visible": attribute.is_visible,
                "is_active": attribute.is_active,
                "sort_order": attribute.sort_order,
            }
            for locale in self.locales:
                name = names.get(locale)
                values[f"name_{locale}"] = str(name) if name is not None else None
            rows.append(self._row(spec, values))
        return rows

    def _option_rows(self, spec: SheetSpec, attributes: Sequence[Attribute]) -> Rows:
        rows: Rows = []
        for attribute in attributes:
            for option in sorted(attribute.options, key=lambda item: (item.sort_order, item.slug)):
                texts = option.value_i18n or {}
                values: dict[str, Any] = {
                    "attribute_code": attribute.code,
                    "slug": option.slug,
                    "sort_order": option.sort_order,
                }
                for locale in self.locales:
                    text = texts.get(locale)
                    values[f"value_{locale}"] = str(text) if text is not None else None
                rows.append(self._row(spec, values))
        return rows
