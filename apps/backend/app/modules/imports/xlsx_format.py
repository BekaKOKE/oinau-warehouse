"""Канонический формат XLSX каталога (версия 1).

Один формат для экспорта и импорта: выгруженный файл возвращается
импортом без ручного преобразования. Полное описание — в
docs/api-catalog-import-export.md.

Книга состоит из листов-таблиц. Отношения вынесены на отдельные листы
(«одна строка — одна ступень цены / одно значение характеристики»),
а не упакованы в одну ячейку: так файл читается глазами, сортируется
и фильтруется средствами Excel.

Идентификаторы — человекочитаемые и стабильные: артикул товара,
slug категории, код характеристики, slug варианта значения. Внутренние
числовые id и UUID в файл не попадают.

Остатков в формате нет намеренно: источником истины по складу будет 1С.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Тип основной части книги в [Content_Types].xml. У .xlsm (с макросами)
# и .xltx (шаблон) он другой — такие файлы не принимаются.
XLSX_MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
)

FORMAT_VERSION = 1
README_SHEET = "README"
# Разделитель списков в ячейке (категории товара).
LIST_SEPARATOR = ";"
# Колонки, чей заголовок начинается с этого символа, — пометки
# пользователя. Импорт их пропускает.
COMMENT_PREFIX = "#"
# Предел длины ячейки Excel.
EXCEL_CELL_MAX_LENGTH = 32_767


class Sheet(StrEnum):
    PRODUCTS = "Products"
    PRICES = "Prices"
    PRODUCT_ATTRIBUTES = "ProductAttributes"
    PRODUCT_SPECS = "ProductSpecs"
    CATEGORIES = "Categories"
    CATEGORY_ATTRIBUTES = "CategoryAttributes"
    ATTRIBUTES = "Attributes"
    ATTRIBUTE_OPTIONS = "AttributeOptions"


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    # Колонка обязана присутствовать в заголовке. Необязательны только
    # переводы на дополнительные локали.
    required: bool = True
    width: int = 16
    # Колонки дополнительной локали добавляются только набором целиком:
    # иначе отсутствующая колонка стёрла бы уже заведённый перевод.
    group: str | None = None


@dataclass(frozen=True)
class SheetSpec:
    name: str
    columns: tuple[ColumnSpec, ...]
    description: str
    # Ниже — послабления пакетного импорта (bundle_format.py). У обычного
    # формата значения по умолчанию: лист обязателен, имя листа точное,
    # заголовки — только канонические имена колонок.
    optional: bool = False
    # Другие имена листа (без учёта регистра).
    alternatives: tuple[str, ...] = ()
    # Нет листа ни под одним именем — взять первый лист книги.
    first_sheet_fallback: bool = False
    # Приведение заголовка к каноническому имени колонки.
    resolve_header: Callable[[str], str | None] | None = None
    # Колонки с переменной частью имени («Цена от 100», «хар: Цвет»).
    dynamic: Callable[[str], bool] | None = None

    @property
    def column_names(self) -> list[str]:
        return [column.name for column in self.columns]


def _localized(
    base: str, locales: list[str], default_locale: str, *, width: int
) -> list[ColumnSpec]:
    """`name_ru` обязательна, `name_kk` и другие локали — нет."""
    ordered = [default_locale, *[item for item in locales if item != default_locale]]
    return [
        ColumnSpec(
            f"{base}_{locale}",
            required=locale == default_locale,
            width=width,
            group=None if locale == default_locale else locale,
        )
        for locale in ordered
    ]


def build_sheet_specs(locales: list[str], default_locale: str) -> dict[str, SheetSpec]:
    """Спецификация листов в порядке их следования в книге."""

    def loc(base: str, width: int) -> list[ColumnSpec]:
        return _localized(base, locales, default_locale, width=width)

    def main_locale(columns: list[ColumnSpec]) -> list[ColumnSpec]:
        return [column for column in columns if column.required]

    def extra_locales(columns: list[ColumnSpec]) -> list[ColumnSpec]:
        return [column for column in columns if not column.required]

    product_texts = [
        *loc("short_description", 40),
        *loc("description", 60),
        *loc("seo_title", 30),
        *loc("seo_description", 40),
    ]
    product_names = loc("name", 40)
    category_texts = [*loc("description", 40), *loc("seo_title", 30), *loc("seo_description", 40)]
    category_names = loc("name", 30)
    attribute_names = loc("name", 24)
    option_values = loc("value", 24)

    specs = [
        SheetSpec(
            Sheet.PRODUCTS,
            (
                ColumnSpec("sku", width=18),
                ColumnSpec("slug", width=28),
                *main_locale(product_names),
                ColumnSpec("status", width=12),
                ColumnSpec("is_active", width=10),
                ColumnSpec("is_featured", width=11),
                ColumnSpec("categories", width=30),
                ColumnSpec("unit", width=8),
                ColumnSpec("min_order_qty", width=13),
                ColumnSpec("pricing_type", width=13),
                ColumnSpec("brand", width=16),
                ColumnSpec("external_id", width=20),
                *main_locale(product_texts),
                *extra_locales(product_names),
                *extra_locales(product_texts),
            ),
            "Товары. Строка = товар, ключ — sku (артикул).",
        ),
        SheetSpec(
            Sheet.PRICES,
            (
                ColumnSpec("sku", width=18),
                ColumnSpec("min_qty", width=10),
                ColumnSpec("max_qty", width=10),
                ColumnSpec("price", width=12),
            ),
            "Ценовые ступени публичного прайс-листа. Строка = ступень.",
        ),
        SheetSpec(
            Sheet.PRODUCT_ATTRIBUTES,
            (
                ColumnSpec("sku", width=18),
                ColumnSpec("attribute_code", width=20),
                ColumnSpec("value", width=24),
            ),
            "Значения характеристик товаров. Строка = одно значение.",
        ),
        SheetSpec(
            Sheet.PRODUCT_SPECS,
            (
                ColumnSpec("sku", width=18),
                ColumnSpec("name", width=28),
                ColumnSpec("value", width=36),
            ),
            "Описательные характеристики карточки (без фильтров).",
        ),
        SheetSpec(
            Sheet.CATEGORIES,
            (
                ColumnSpec("slug", width=26),
                ColumnSpec("parent_slug", width=26),
                *main_locale(category_names),
                ColumnSpec("sort_order", width=10),
                ColumnSpec("is_active", width=10),
                ColumnSpec("external_id", width=20),
                *main_locale(category_texts),
                *extra_locales(category_names),
                *extra_locales(category_texts),
            ),
            "Категории. Ключ — slug.",
        ),
        SheetSpec(
            Sheet.CATEGORY_ATTRIBUTES,
            (
                ColumnSpec("category_slug", width=26),
                ColumnSpec("attribute_code", width=20),
                ColumnSpec("sort_order", width=10),
                ColumnSpec("is_required", width=11),
            ),
            "Характеристики в фильтрах категории.",
        ),
        SheetSpec(
            Sheet.ATTRIBUTES,
            (
                ColumnSpec("code", width=20),
                ColumnSpec("value_type", width=12),
                *main_locale(attribute_names),
                ColumnSpec("unit", width=8),
                ColumnSpec("is_filterable", width=12),
                ColumnSpec("is_visible", width=10),
                ColumnSpec("is_active", width=10),
                ColumnSpec("sort_order", width=10),
                *extra_locales(attribute_names),
            ),
            "Справочник характеристик. Ключ — code.",
        ),
        SheetSpec(
            Sheet.ATTRIBUTE_OPTIONS,
            (
                ColumnSpec("attribute_code", width=20),
                ColumnSpec("slug", width=20),
                *main_locale(option_values),
                ColumnSpec("sort_order", width=10),
                *extra_locales(option_values),
            ),
            "Варианты значений характеристик типа OPTION. Ключ — attribute_code + slug.",
        ),
    ]
    return {spec.name: spec for spec in specs}
