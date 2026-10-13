"""Проверка файла и построение плана изменений.

Проверка работает в памяти по снимку каталога (snapshot.py) и не
обращается к базе. Одна и та же проверка выполняется дважды: при
предпросмотре и повторно при подтверждении — уже по свежему снимку,
под блокировкой.

Правила полей НЕ дублируются: каждая строка в итоге проходит через
Pydantic-схемы Admin API (ProductCreate, CategoryCreate, AttributeCreate,
AttributeOptionCreate, PricingUpdate). Если правило поменяется в
админке, оно поменяется и здесь. Собственный разбор ячеек нужен только
для понятных сообщений на русском и для типов Excel (float, bool).

Семантика файла (подробно — docs/api-catalog-import-export.md):

* сущности (товары, категории, характеристики, варианты значений)
  создаются или обновляются по стабильному ключу и никогда не удаляются;
* связи сущности из файла (категории товара, характеристики, цены,
  описательные характеристики, фильтры категории) заменяются целиком;
* всё, чего нет в файле, не трогается;
* артикул — неизменяемый ключ товара: переименование через импорт
  невозможно, новый артикул означает новый товар.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError

from app.db.types import LEN_SLUG
from app.modules.catalog.enums import AttributeValueType, ProductStatus
from app.modules.catalog.models import Attribute, AttributeOption, Category, Product
from app.modules.catalog.schemas_admin import (
    SLUG_PATTERN,
    AttributeCreate,
    AttributeOptionCreate,
    CategoryCreate,
    CategoryTranslationIn,
)
from app.modules.catalog.schemas_admin_products import (
    SKU_PATTERN,
    ProductCreate,
    ProductTranslationIn,
    ProductUpdate,
)
from app.modules.imports.cells import (
    CellError,
    as_bool,
    as_decimal,
    as_enum,
    as_identifier,
    as_int,
    as_list,
    as_text,
)
from app.modules.imports.issues import IssueCode, IssueCollector
from app.modules.imports.snapshot import CatalogSnapshot, CategoryLink, option_by_slug
from app.modules.imports.xlsx_format import EXCEL_CELL_MAX_LENGTH, Sheet
from app.modules.imports.xlsx_reader import CellValue, ParsedWorkbook, RowData
from app.modules.pricing.enums import PricingType
from app.modules.pricing.schemas_admin import PriceTierInput, PricingUpdate

CODE_PATTERN = r"^[a-z0-9_]+$"

SKU_HINT = "Артикул: латинские буквы, цифры и символы . _ / - без пробелов"
SLUG_HINT = "slug: строчные латинские буквы, цифры и дефис"
CODE_HINT = "Код: строчные латинские буквы, цифры и подчёркивание"

# Поля переводов: (длина, многострочное ли поле)
PRODUCT_TEXTS: dict[str, tuple[int, bool]] = {
    "name": (500, False),
    "short_description": (EXCEL_CELL_MAX_LENGTH, True),
    "description": (EXCEL_CELL_MAX_LENGTH, True),
    "seo_title": (500, False),
    "seo_description": (EXCEL_CELL_MAX_LENGTH, True),
}
CATEGORY_TEXTS: dict[str, tuple[int, bool]] = {
    "name": (500, False),
    "description": (EXCEL_CELL_MAX_LENGTH, True),
    "seo_title": (500, False),
    "seo_description": (EXCEL_CELL_MAX_LENGTH, True),
}
LABEL_TEXTS: dict[str, tuple[int, bool]] = {"name": (255, False)}
OPTION_TEXTS: dict[str, tuple[int, bool]] = {"value": (255, False)}

PRODUCT_SCALARS = ("slug", "status", "is_active", "is_featured", "unit", "brand", "external_id")

QTY_DIGITS, QTY_PLACES = 14, 3
MONEY_DIGITS, MONEY_PLACES = 14, 2
SPEC_NAME_MAX, SPEC_VALUE_MAX = 120, 500


# ===================================================================== план
@dataclass
class TierPlan:
    row: int
    min_qty: Decimal
    max_qty: Decimal | None
    price: Decimal


@dataclass
class AttributeValuePlan:
    row: int
    attribute_code: str
    value_type: AttributeValueType
    value_string: str | None = None
    value_numeric: Decimal | None = None
    value_bool: bool | None = None
    option_slug: str | None = None

    def key(self) -> tuple[str, str]:
        return (self.attribute_code, _value_key(self))


@dataclass
class AttributePlan:
    row: int
    code: str
    value_type: AttributeValueType
    unit: str | None
    is_filterable: bool
    is_visible: bool
    is_active: bool
    sort_order: int
    names: dict[str, str]
    existing: Attribute | None = None
    changes: dict[str, Any] = field(default_factory=dict)

    @property
    def action(self) -> str:
        return _action(self.existing, bool(self.changes))


@dataclass
class OptionPlan:
    row: int
    attribute_code: str
    slug: str
    sort_order: int
    values: dict[str, str]
    existing: AttributeOption | None = None
    changes: dict[str, Any] = field(default_factory=dict)

    @property
    def action(self) -> str:
        return _action(self.existing, bool(self.changes))


@dataclass
class CategoryPlan:
    row: int
    slug: str
    parent_slug: str | None
    sort_order: int
    is_active: bool
    external_id: str | None
    translations: dict[str, CategoryTranslationIn]
    existing: Category | None = None
    changes: dict[str, Any] = field(default_factory=dict)
    links: list[CategoryLink] = field(default_factory=list)
    links_changed: bool = False

    @property
    def action(self) -> str:
        return _action(self.existing, bool(self.changes) or self.links_changed)


@dataclass
class ProductPlan:
    row: int
    sku: str
    slug: str
    status: ProductStatus
    is_active: bool
    is_featured: bool
    unit: str
    min_order_qty: Decimal
    brand: str | None
    external_id: str | None
    pricing_type: PricingType
    translations: dict[str, ProductTranslationIn]
    category_slugs: list[str]
    tiers: list[TierPlan] = field(default_factory=list)
    attributes: list[AttributeValuePlan] = field(default_factory=list)
    specs: dict[str, str] = field(default_factory=dict)
    existing: Product | None = None
    field_changes: dict[str, Any] = field(default_factory=dict)
    categories_changed: bool = False
    attributes_changed: bool = False
    specs_changed: bool = False
    pricing_changed: bool = False
    # Только у пакетного импорта (bundle_validator.py). None — колонки
    # нет или ячейка пуста: эта часть товара не меняется.
    photos: list[str] | None = None
    schemes: list[str] | None = None
    stock: Decimal | None = None
    reserved: Decimal | None = None
    # Изменения фото, схем и остатков — их вычисляет планировщик пакета
    # после сверки с архивом и складом.
    extra_changes: list[str] = field(default_factory=list)

    @property
    def changed_parts(self) -> list[str]:
        parts = sorted(self.field_changes)
        for name, flag in (
            ("categories", self.categories_changed),
            ("attributes", self.attributes_changed),
            ("specs", self.specs_changed),
            ("pricing", self.pricing_changed),
        ):
            if flag:
                parts.append(name)
        parts.extend(self.extra_changes)
        return parts

    @property
    def action(self) -> str:
        return _action(self.existing, bool(self.changed_parts))


@dataclass
class ImportPlan:
    attributes: list[AttributePlan] = field(default_factory=list)
    options: list[OptionPlan] = field(default_factory=list)
    categories: list[CategoryPlan] = field(default_factory=list)
    products: list[ProductPlan] = field(default_factory=list)


@dataclass
class ValidationResult:
    plan: ImportPlan
    errors: IssueCollector
    warnings: IssueCollector
    sheet_rows: dict[str, int]

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def rows_total(self) -> int:
        return sum(self.sheet_rows.values())

    def counts(self, items: Iterable[Any]) -> dict[str, int]:
        counter = Counter(item.action for item in items)
        return {
            "create": counter.get("create", 0),
            "update": counter.get("update", 0),
            "unchanged": counter.get("unchanged", 0),
        }

    def summary(self) -> dict[str, Any]:
        return {
            "rows_total": self.rows_total,
            "sheets": dict(self.sheet_rows),
            "products": self.counts(self.plan.products),
            "categories": self.counts(self.plan.categories),
            "attributes": self.counts(self.plan.attributes),
            "attribute_options": self.counts(self.plan.options),
        }

    def product_changes(self) -> list[dict[str, Any]]:
        return [
            {
                "row": item.row,
                "sku": item.sku,
                "action": item.action,
                "changed": item.changed_parts if item.existing is not None else [],
            }
            for item in self.plan.products
            if item.action != "unchanged"
        ]


def _action(existing: object | None, changed: bool) -> str:
    if existing is None:
        return "create"
    return "update" if changed else "unchanged"


# ================================================================ сравнение
def _norm(value: Any) -> Any:
    """Пустая строка и NULL для текста — одно и то же."""
    if isinstance(value, str) and value == "":
        return None
    return value


def _decimal_key(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _value_key(value: AttributeValuePlan) -> str:
    if value.value_type is AttributeValueType.NUMBER and value.value_numeric is not None:
        return f"n:{_decimal_key(value.value_numeric)}"
    if value.value_type is AttributeValueType.BOOLEAN:
        return f"b:{value.value_bool}"
    if value.value_type is AttributeValueType.OPTION:
        return f"o:{value.option_slug}"
    return f"s:{value.value_string}"


def _stored_value_key(item: Any) -> tuple[str, str]:
    """Ключ значения характеристики из базы — в той же форме, что из файла."""
    code = item.attribute.code
    if item.option_id is not None:
        return (code, f"o:{item.option.slug}")
    if item.value_numeric is not None:
        return (code, f"n:{_decimal_key(item.value_numeric)}")
    if item.value_bool is not None:
        return (code, f"b:{item.value_bool}")
    return (code, f"s:{item.value_string}")


def _pricing_key(
    pricing_type: str, tiers: Iterable[tuple[Decimal, Decimal | None, Decimal]]
) -> tuple[str, tuple[tuple[Decimal, Decimal | None, Decimal], ...]]:
    return (pricing_type, tuple(sorted(tiers, key=lambda tier: tier[0])))


def _texts_differ(current: Any | None, desired: BaseModel) -> bool:
    if current is None:
        return True
    return any(
        _norm(getattr(current, name)) != _norm(value)
        for name, value in desired.model_dump().items()
    )


def current_category_slugs(product: Product) -> list[str]:
    """Категории товара в каноническом порядке: основная, затем по sort_order.

    Этот же порядок пишет экспорт, поэтому выгруженный и возвращённый
    файл не даёт ложных изменений.
    """
    links = sorted(
        (link for link in product.categories if link.category.deleted_at is None),
        key=lambda link: (not link.is_primary, link.sort_order, link.category.slug),
    )
    return [link.category.slug for link in links]


def _categories_differ(product: Product, desired: list[str]) -> bool:
    links = sorted(
        product.categories,
        key=lambda link: (not link.is_primary, link.sort_order, link.category.slug),
    )
    current = [(link.category.slug, link.is_primary) for link in links]
    wanted = [(slug, index == 0) for index, slug in enumerate(desired)]
    return current != wanted


# ============================================================== сообщения
def _pydantic_message(error: Mapping[str, Any]) -> str:
    kind = error.get("type", "")
    ctx = error.get("ctx") or {}
    messages: dict[str, Callable[[], str]] = {
        "missing": lambda: "Значение обязательно",
        "string_too_short": lambda: (
            "Значение обязательно"
            if ctx.get("min_length") == 1
            else f"Не короче {ctx.get('min_length')} символов"
        ),
        "string_too_long": lambda: f"Не длиннее {ctx.get('max_length')} символов",
        "string_pattern_mismatch": lambda: "Недопустимые символы",
        "greater_than": lambda: f"Значение должно быть больше {ctx.get('gt')}",
        "greater_than_equal": lambda: f"Значение должно быть не меньше {ctx.get('ge')}",
        "decimal_max_places": lambda: f"Не больше {ctx.get('decimal_places')} знаков после запятой",
        "decimal_max_digits": lambda: f"Не больше {ctx.get('max_digits')} цифр",
        "decimal_whole_digits": lambda: "Слишком большое число",
        "too_long": lambda: f"Не больше {ctx.get('max_length')} элементов",
        "enum": lambda: f"Допустимые значения: {ctx.get('expected')}",
    }
    builder = messages.get(kind)
    if builder is not None:
        return builder()
    message = str(error.get("msg", "Некорректное значение"))
    return message.removeprefix("Value error, ")


# ================================================================ проверка
class _Row:
    """Контекст проверки одной строки: собирает ошибки ячеек."""

    def __init__(self, validator: CatalogImportValidator, sheet: str, row: RowData) -> None:
        self.validator = validator
        self.sheet = sheet
        self.row = row
        # Ячейки, уже отвергнутые при чтении (формула, ошибка Excel, дата):
        # строка недействительна, но повторное «значение обязательно»
        # про ту же ячейку в отчёт не добавляется.
        self.bad = validator.bad_cells.get((sheet, row.number), set())
        self.ok = not self.bad

    def raw(self, column: str) -> CellValue:
        return self.row.cells.get(column)

    def is_bad(self, column: str) -> bool:
        return column in self.bad

    def get(self, column: str, parser: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if column in self.bad:
            return None
        try:
            return parser(self.raw(column), *args, **kwargs)
        except CellError as exc:
            self.error(column, exc.code, exc.message)
            return None

    def error(self, column: str | None, code: str, message: str, *, value: Any = ...) -> None:
        self.ok = False
        if value is ...:
            value = self.raw(column) if column else None
        self.validator.errors.add(
            sheet=self.sheet,
            row=self.row.number,
            column=column,
            code=code,
            message=message,
            value=value,
        )

    def warning(self, column: str | None, code: str, message: str) -> None:
        self.validator.warnings.add(
            sheet=self.sheet, row=self.row.number, column=column, code=code, message=message
        )

    def schema_errors(
        self, exc: ValidationError, column_of: Callable[[tuple[Any, ...]], str | None]
    ) -> None:
        for error in exc.errors(include_url=False):
            self.error(
                column_of(tuple(error.get("loc", ()))),
                IssueCode.INVALID_VALUE,
                _pydantic_message(error),
            )


def _plain_column(loc: tuple[Any, ...]) -> str | None:
    return str(loc[0]) if loc else None


def _translated_column(names: Mapping[str, str]) -> Callable[[tuple[Any, ...]], str | None]:
    """loc ('translations', 'ru', 'name') -> колонка name_ru."""

    def column_of(loc: tuple[Any, ...]) -> str | None:
        if loc and loc[0] in names:
            if len(loc) >= 3:
                return f"{loc[2]}_{loc[1]}"
            if len(loc) == 2:
                return f"{names[str(loc[0])]}_{loc[1]}"
            return None
        return _plain_column(loc)

    return column_of


class CatalogImportValidator:
    def __init__(
        self,
        workbook: ParsedWorkbook,
        snapshot: CatalogSnapshot,
        *,
        locales: list[str],
        default_locale: str,
    ) -> None:
        self.workbook = workbook
        self.snapshot = snapshot
        self.default_locale = default_locale
        self.locales = [default_locale, *[item for item in locales if item != default_locale]]
        self.errors = IssueCollector()
        self.warnings = IssueCollector()
        self.plan = ImportPlan()

        self.rows_by_number: dict[tuple[str, int], RowData] = {
            (name, row.number): row for name, sheet in workbook.sheets.items() for row in sheet.rows
        }
        self.bad_cells: dict[tuple[str, int], set[str]] = {}
        for issue in workbook.cell_issues:
            if issue.sheet is not None and issue.row is not None and issue.column is not None:
                self.bad_cells.setdefault((issue.sheet, issue.row), set()).add(issue.column)

        # Ключи, встреченные в файле (включая строки с ошибками): ссылки
        # на них не порождают повторных «не найдено».
        self.attribute_rows: dict[str, int] = {}
        self.attribute_types: dict[str, AttributeValueType | None] = {}
        self.option_rows: dict[tuple[str, str], int] = {}
        self.category_rows: dict[str, int] = {}
        self.product_rows: dict[str, int] = {}
        self.failed_skus: set[str] = set()
        self.failed_categories: set[str] = set()

        self.products: dict[str, ProductPlan] = {}
        self.categories: dict[str, CategoryPlan] = {}
        self.tiers: dict[str, list[TierPlan]] = {}
        self.values: dict[str, list[AttributeValuePlan]] = {}
        self.specs: dict[str, dict[str, str]] = {}
        self.spec_rows: dict[str, int] = {}
        self.links: dict[str, list[CategoryLink]] = {}

    # ------------------------------------------------------------ точка входа
    def validate(self) -> ValidationResult:
        sheet_rows = {name: len(sheet.rows) for name, sheet in self.workbook.sheets.items()}
        result = ValidationResult(
            plan=self.plan, errors=self.errors, warnings=self.warnings, sheet_rows=sheet_rows
        )

        if self.workbook.structure_issues:
            # Колонки ненадёжны — данные не проверяются, иначе отчёт
            # утонет в ошибках-следствиях.
            self.errors.extend(self.workbook.structure_issues)
            return result
        self.errors.extend(self.workbook.cell_issues)

        if result.rows_total == 0:
            self.errors.add(
                sheet=None,
                row=None,
                column=None,
                code=IssueCode.EMPTY_WORKBOOK,
                message="Файл не содержит ни одной строки данных",
            )
            return result

        self._attributes()
        self._options()
        self._categories()
        self._category_links()
        self._products()
        self._prices()
        self._product_attributes()
        self._product_specs()
        self._finalize_categories()
        self._finalize_products()
        return result

    # ---------------------------------------------------------------- общее
    def _rows(self, sheet: str) -> Iterable[_Row]:
        data = self.workbook.sheets.get(sheet)
        if data is None:
            return []
        return [_Row(self, sheet, row) for row in data.rows]

    def _columns(self, sheet: str) -> set[str]:
        data = self.workbook.sheets.get(sheet)
        return data.columns if data is not None else set()

    def _texts(
        self, row: _Row, fields: Mapping[str, tuple[int, bool]], required: str
    ) -> dict[str, dict[str, str | None]]:
        """Переводы из колонок вида name_ru, description_ru, ..."""
        columns = self._columns(row.sheet)
        result: dict[str, dict[str, str | None]] = {}
        for locale in self.locales:
            if f"{required}_{locale}" not in columns:
                continue
            values: dict[str, str | None] = {}
            for name, (max_length, multiline) in fields.items():
                values[name] = row.get(
                    f"{name}_{locale}", as_text, max_length=max_length, multiline=multiline
                )
            if locale == self.default_locale:
                column = f"{required}_{locale}"
                if values[required] is None and row.raw(column) is None and not row.is_bad(column):
                    row.error(column, IssueCode.REQUIRED, "Значение обязательно")
            elif values[required] is None:
                if any(value is not None for value in values.values()):
                    row.error(
                        f"{required}_{locale}",
                        IssueCode.REQUIRED,
                        f"Для перевода {locale} заполните {required}_{locale}",
                    )
                continue
            result[locale] = values
        return result

    def _attribute_type(self, code: str) -> AttributeValueType | None:
        if code in self.attribute_types:
            return self.attribute_types[code]
        existing = self.snapshot.attributes.get(code)
        return AttributeValueType(existing.value_type) if existing is not None else None

    def _attribute_known(self, code: str) -> bool:
        return code in self.attribute_rows or code in self.snapshot.attributes

    def _option_known(self, code: str, slug: str) -> bool:
        if (code, slug) in self.option_rows:
            return True
        existing = self.snapshot.attributes.get(code)
        return existing is not None and slug in option_by_slug(existing)

    def _category_known(self, slug: str) -> bool:
        return slug in self.category_rows or slug in self.snapshot.categories

    # ----------------------------------------------------------- Attributes
    def _attributes(self) -> None:
        for row in self._rows(Sheet.ATTRIBUTES):
            code = row.get(
                "code", as_identifier, pattern=CODE_PATTERN, max_length=64, hint=CODE_HINT
            )
            value_type = row.get("value_type", as_enum, AttributeValueType)
            names = self._texts(row, LABEL_TEXTS, "name")
            unit = row.get("unit", as_text, max_length=16)
            flags = {
                name: row.get(name, as_bool)
                for name in ("is_filterable", "is_visible", "is_active")
            }
            sort_order = row.get("sort_order", as_int)
            if code is None:
                continue
            if code in self.attribute_rows:
                row.error(
                    "code",
                    IssueCode.DUPLICATE_ROW,
                    f"Характеристика «{code}» уже указана в строке {self.attribute_rows[code]}",
                )
                continue
            self.attribute_rows[code] = row.row.number
            self.attribute_types[code] = value_type
            if not row.ok:
                continue

            names_map = {locale: str(values["name"]) for locale, values in names.items()}
            try:
                AttributeCreate.model_validate(
                    {
                        "code": code,
                        "value_type": value_type,
                        "unit": unit,
                        "sort_order": sort_order,
                        "names": names_map,
                        **flags,
                    }
                )
            except ValidationError as exc:
                row.schema_errors(exc, _translated_column({"names": "name"}))
                self.attribute_types[code] = None
                continue

            existing = self.snapshot.attributes.get(code)
            if existing is not None and existing.value_type != value_type:
                row.error(
                    "value_type",
                    IssueCode.ATTRIBUTE_TYPE_CHANGE,
                    f"Тип характеристики менять нельзя: сейчас {existing.value_type}. "
                    "Заведите новую характеристику",
                )
                # Зависимые строки не проверяются против ошибочного типа.
                self.attribute_types[code] = None
                continue

            plan = AttributePlan(
                row=row.row.number,
                code=code,
                value_type=value_type,
                unit=unit,
                sort_order=sort_order,
                names=names_map,
                existing=existing,
                **flags,
            )
            if existing is not None:
                plan.changes = self._attribute_changes(existing, plan)
            self.plan.attributes.append(plan)

    def _attribute_changes(self, existing: Attribute, plan: AttributePlan) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        for name in ("unit", "is_filterable", "is_visible", "is_active", "sort_order"):
            old, new = getattr(existing, name), getattr(plan, name)
            if _norm(old) != _norm(new):
                changes[name] = {"old": old, "new": new}
        current = existing.name_i18n or {}
        if any(current.get(locale) != name for locale, name in plan.names.items()):
            changes["names"] = {"old": current, "new": {**current, **plan.names}}
        return changes

    # ----------------------------------------------------- AttributeOptions
    def _options(self) -> None:
        for row in self._rows(Sheet.ATTRIBUTE_OPTIONS):
            code = row.get(
                "attribute_code", as_identifier, pattern=CODE_PATTERN, max_length=64, hint=CODE_HINT
            )
            slug = row.get(
                "slug", as_identifier, pattern=SLUG_PATTERN, max_length=LEN_SLUG, hint=SLUG_HINT
            )
            values = self._texts(row, OPTION_TEXTS, "value")
            sort_order = row.get("sort_order", as_int)
            if code is None or slug is None:
                continue
            key = (code, slug)
            if key in self.option_rows:
                row.error(
                    "slug",
                    IssueCode.DUPLICATE_ROW,
                    f"Вариант «{slug}» характеристики «{code}» уже указан в строке "
                    f"{self.option_rows[key]}",
                )
                continue
            self.option_rows[key] = row.row.number

            if not self._attribute_known(code):
                row.error(
                    "attribute_code",
                    IssueCode.ATTRIBUTE_NOT_FOUND,
                    f"Характеристика «{code}» не найдена ни в каталоге, ни на листе Attributes",
                )
                continue
            value_type = self._attribute_type(code)
            if value_type is None:
                row.ok = False  # строка характеристики с ошибкой — уже в отчёте
                continue
            if value_type is not AttributeValueType.OPTION:
                row.error(
                    "attribute_code",
                    IssueCode.ATTRIBUTE_NOT_OPTION,
                    f"Варианты значений допустимы только для типа OPTION, у «{code}» — "
                    f"{value_type.value}",
                )
                continue
            if not row.ok:
                continue

            values_map = {locale: str(item["value"]) for locale, item in values.items()}
            try:
                AttributeOptionCreate.model_validate(
                    {"slug": slug, "sort_order": sort_order, "values": values_map}
                )
            except ValidationError as exc:
                row.schema_errors(exc, _translated_column({"values": "value"}))
                continue

            attribute = self.snapshot.attributes.get(code)
            existing = option_by_slug(attribute).get(slug) if attribute is not None else None
            plan = OptionPlan(
                row=row.row.number,
                attribute_code=code,
                slug=slug,
                sort_order=sort_order,
                values=values_map,
                existing=existing,
            )
            if existing is not None:
                current = existing.value_i18n or {}
                if existing.sort_order != sort_order:
                    plan.changes["sort_order"] = {"old": existing.sort_order, "new": sort_order}
                if any(current.get(locale) != value for locale, value in values_map.items()):
                    plan.changes["values"] = {"old": current, "new": {**current, **values_map}}
            self.plan.options.append(plan)

    # ----------------------------------------------------------- Categories
    def _categories(self) -> None:
        for row in self._rows(Sheet.CATEGORIES):
            slug = row.get(
                "slug", as_identifier, pattern=SLUG_PATTERN, max_length=LEN_SLUG, hint=SLUG_HINT
            )
            parent_slug = None
            if row.raw("parent_slug") is not None:
                parent_slug = row.get(
                    "parent_slug",
                    as_identifier,
                    pattern=SLUG_PATTERN,
                    max_length=LEN_SLUG,
                    hint=SLUG_HINT,
                )
            texts = self._texts(row, CATEGORY_TEXTS, "name")
            sort_order = row.get("sort_order", as_int)
            is_active = row.get("is_active", as_bool)
            external_id = row.get("external_id", as_text, max_length=64)
            if slug is None:
                continue
            if slug in self.category_rows:
                row.error(
                    "slug",
                    IssueCode.DUPLICATE_ROW,
                    f"Категория «{slug}» уже указана в строке {self.category_rows[slug]}",
                )
                continue
            self.category_rows[slug] = row.row.number
            if not row.ok:
                self.failed_categories.add(slug)
                continue

            try:
                payload = CategoryCreate.model_validate(
                    {
                        "slug": slug,
                        "sort_order": sort_order,
                        "is_active": is_active,
                        "external_id": external_id,
                        "translations": texts,
                    }
                )
            except ValidationError as exc:
                row.schema_errors(exc, _translated_column({"translations": "name"}))
                self.failed_categories.add(slug)
                continue

            existing = self.snapshot.categories.get(slug)
            if existing is None and slug in self.snapshot.deleted_category_slugs:
                row.warning(
                    "slug",
                    IssueCode.DELETED_CATEGORY_SLUG_REUSED,
                    f"Категория «{slug}» была удалена. Будет создана новая категория; "
                    "удалённую можно восстановить в админке",
                )
            self.categories[slug] = CategoryPlan(
                row=row.row.number,
                slug=slug,
                parent_slug=parent_slug,
                sort_order=sort_order,
                is_active=is_active,
                external_id=external_id,
                translations=dict(payload.translations),
                existing=existing,
            )

    def _category_links(self) -> None:
        seen: set[tuple[str, str]] = set()
        for row in self._rows(Sheet.CATEGORY_ATTRIBUTES):
            slug = row.get(
                "category_slug",
                as_identifier,
                pattern=SLUG_PATTERN,
                max_length=LEN_SLUG,
                hint=SLUG_HINT,
            )
            code = row.get(
                "attribute_code", as_identifier, pattern=CODE_PATTERN, max_length=64, hint=CODE_HINT
            )
            sort_order = row.get("sort_order", as_int)
            is_required = row.get("is_required", as_bool)
            if slug is None or code is None:
                self._fail_category(slug)
                continue
            if slug not in self.category_rows:
                row.error(
                    "category_slug",
                    IssueCode.UNKNOWN_CATEGORY,
                    f"Категории «{slug}» нет на листе Categories: фильтры задаются только "
                    "для категорий из файла",
                )
                continue
            if not self._attribute_known(code):
                row.error(
                    "attribute_code",
                    IssueCode.ATTRIBUTE_NOT_FOUND,
                    f"Характеристика «{code}» не найдена ни в каталоге, ни на листе Attributes",
                )
            elif (slug, code) in seen:
                row.error(
                    "attribute_code",
                    IssueCode.DUPLICATE_ROW,
                    f"Характеристика «{code}» уже указана для категории «{slug}»",
                )
            seen.add((slug, code))
            if not row.ok:
                self._fail_category(slug)
                continue
            self.links.setdefault(slug, []).append(
                CategoryLink(attribute_code=code, sort_order=sort_order, is_required=is_required)
            )

    def _fail_category(self, slug: str | None) -> None:
        if slug is not None:
            self.failed_categories.add(slug)

    def _finalize_categories(self) -> None:
        by_id = self.snapshot.categories_by_id
        final_parent: dict[str, str | None] = {
            slug: (by_id[category.parent_id].slug if category.parent_id in by_id else None)
            for slug, category in self.snapshot.categories.items()
        }
        for slug, plan in self.categories.items():
            final_parent[slug] = plan.parent_slug

        external_rows: dict[str, str] = {}
        for slug, plan in self.categories.items():
            row = _Row(self, Sheet.CATEGORIES, self._row_of(Sheet.CATEGORIES, plan.row))
            parent = plan.parent_slug
            if parent is not None:
                if parent == slug:
                    row.error(
                        "parent_slug",
                        IssueCode.CATEGORY_CYCLE,
                        "Категория не может быть родителем самой себя",
                    )
                elif not self._category_known(parent):
                    if parent in self.snapshot.deleted_category_slugs:
                        row.error(
                            "parent_slug",
                            IssueCode.CATEGORY_DELETED,
                            f"Родительская категория «{parent}» удалена",
                        )
                    else:
                        row.error(
                            "parent_slug",
                            IssueCode.CATEGORY_NOT_FOUND,
                            f"Родительская категория «{parent}» не найдена ни в каталоге, "
                            "ни на листе Categories",
                        )
                elif self._in_cycle(slug, final_parent):
                    row.error(
                        "parent_slug",
                        IssueCode.CATEGORY_CYCLE,
                        "Циклическая вложенность: категория оказалась бы внутри своей же ветки",
                    )

            if plan.external_id is not None:
                owner = self.snapshot.category_external_ids.get(plan.external_id)
                if owner is not None and owner != slug:
                    row.error(
                        "external_id",
                        IssueCode.EXTERNAL_ID_TAKEN,
                        f"Внешний идентификатор уже занят категорией «{owner}»",
                    )
                elif plan.external_id in external_rows:
                    row.error(
                        "external_id",
                        IssueCode.DUPLICATE_ROW,
                        "Внешний идентификатор уже указан у категории "
                        f"«{external_rows[plan.external_id]}»",
                    )
                external_rows.setdefault(plan.external_id, slug)

            if not row.ok or slug in self.failed_categories:
                self.failed_categories.add(slug)
                continue

            plan.links = self.links.get(slug, [])
            existing = plan.existing
            if existing is None:
                plan.links_changed = bool(plan.links)
            else:
                current_links = self.snapshot.category_links.get(existing.id, [])
                plan.links_changed = set(current_links) != set(plan.links)
                plan.changes = self._category_changes(existing, plan)
            self.plan.categories.append(plan)

    def _in_cycle(self, slug: str, final_parent: Mapping[str, str | None]) -> bool:
        seen: set[str] = set()
        current = final_parent.get(slug)
        while current is not None:
            if current == slug:
                return True
            if current in seen:
                return False
            seen.add(current)
            current = final_parent.get(current)
        return False

    def _category_changes(self, existing: Category, plan: CategoryPlan) -> dict[str, Any]:
        by_id = self.snapshot.categories_by_id
        changes: dict[str, Any] = {}
        current_parent = by_id[existing.parent_id].slug if existing.parent_id in by_id else None
        if current_parent != plan.parent_slug:
            changes["parent_slug"] = {"old": current_parent, "new": plan.parent_slug}
        for name in ("sort_order", "is_active", "external_id"):
            old, new = getattr(existing, name), getattr(plan, name)
            if _norm(old) != _norm(new):
                changes[name] = {"old": old, "new": new}
        current = {item.locale: item for item in existing.translations}
        locales = [
            locale
            for locale, texts in plan.translations.items()
            if _texts_differ(current.get(locale), texts)
        ]
        if locales:
            changes["translations"] = {"old": None, "new": sorted(locales)}
        return changes

    def _row_of(self, sheet: str, number: int) -> RowData:
        return self.rows_by_number[(sheet, number)]

    # ------------------------------------------------------------- Products
    def _products(self) -> None:
        live_lower = self.snapshot.live_skus_by_lower()
        deleted = self.snapshot.deleted_skus()
        file_lower: dict[str, str] = {}

        for row in self._rows(Sheet.PRODUCTS):
            sku = row.get("sku", as_identifier, pattern=SKU_PATTERN, max_length=64, hint=SKU_HINT)
            slug = row.get(
                "slug", as_identifier, pattern=SLUG_PATTERN, max_length=LEN_SLUG, hint=SLUG_HINT
            )
            status = row.get("status", as_enum, ProductStatus)
            is_active = row.get("is_active", as_bool)
            is_featured = row.get("is_featured", as_bool)
            unit = row.get("unit", as_text, max_length=16, required=True)
            min_order_qty = row.get(
                "min_order_qty",
                as_decimal,
                max_digits=QTY_DIGITS,
                decimal_places=QTY_PLACES,
                greater_than=Decimal(0),
            )
            pricing_type = row.get("pricing_type", as_enum, PricingType)
            brand = row.get("brand", as_text, max_length=255)
            external_id = row.get("external_id", as_text, max_length=64)
            category_slugs = row.get("categories", as_list) or []
            texts = self._texts(row, PRODUCT_TEXTS, "name")
            if sku is None:
                continue

            if sku in self.product_rows:
                row.error(
                    "sku",
                    IssueCode.DUPLICATE_ROW,
                    f"Артикул {sku} уже указан в строке {self.product_rows[sku]}",
                )
                continue
            self.product_rows[sku] = row.row.number

            other = file_lower.get(sku.lower())
            if other is not None:
                row.error(
                    "sku",
                    IssueCode.SKU_CASE_CONFLICT,
                    f"Артикулы {sku} и {other} различаются только регистром",
                )
            file_lower.setdefault(sku.lower(), sku)

            existing = self.snapshot.products.get(sku)
            if existing is None:
                same = live_lower.get(sku.lower())
                if same is not None and same != sku:
                    row.error(
                        "sku",
                        IssueCode.SKU_CASE_CONFLICT,
                        f"В каталоге уже есть артикул {same}: артикулы различаются только "
                        "регистром. Исправьте артикул в файле",
                    )
                elif sku in deleted:
                    row.warning(
                        "sku",
                        IssueCode.DELETED_SKU_REUSED,
                        f"Товар с артикулом {sku} был удалён. Будет создан новый товар; "
                        "удалённый можно восстановить в админке",
                    )

            seen: set[str] = set()
            for category in category_slugs:
                if category in seen:
                    row.error(
                        "categories",
                        IssueCode.DUPLICATE_ROW,
                        f"Категория «{category}» указана дважды",
                    )
                elif not self._category_known(category):
                    if category in self.snapshot.deleted_category_slugs:
                        row.error(
                            "categories",
                            IssueCode.CATEGORY_DELETED,
                            f"Категория «{category}» удалена",
                        )
                    else:
                        row.error(
                            "categories",
                            IssueCode.CATEGORY_NOT_FOUND,
                            f"Категория «{category}» не найдена ни в каталоге, "
                            "ни на листе Categories",
                        )
                seen.add(category)

            if not row.ok:
                self.failed_skus.add(sku)
                continue

            try:
                payload = ProductCreate.model_validate(
                    {
                        "sku": sku,
                        "slug": slug,
                        "status": status,
                        "is_active": is_active,
                        "is_featured": is_featured,
                        "unit": unit,
                        "min_order_qty": min_order_qty,
                        "brand": brand,
                        "external_id": external_id,
                        "translations": texts,
                    }
                )
            except ValidationError as exc:
                row.schema_errors(exc, _translated_column({"translations": "name"}))
                self.failed_skus.add(sku)
                continue

            self.products[sku] = ProductPlan(
                row=row.row.number,
                sku=sku,
                slug=payload.slug,
                status=payload.status,
                is_active=payload.is_active,
                is_featured=payload.is_featured,
                unit=payload.unit,
                min_order_qty=payload.min_order_qty,
                brand=payload.brand,
                external_id=payload.external_id,
                pricing_type=pricing_type,
                translations=dict(payload.translations),
                category_slugs=category_slugs,
                existing=existing,
            )

        self._check_product_uniqueness()

    def _check_product_uniqueness(self) -> None:
        live_by_slug = self.snapshot.live_sku_by_slug()
        external_ids = self.snapshot.product_external_ids()
        slugs: dict[str, str] = {}
        externals: dict[str, str] = {}
        for sku, plan in self.products.items():
            row = _Row(self, Sheet.PRODUCTS, self._row_of(Sheet.PRODUCTS, plan.row))
            holder = live_by_slug.get(plan.slug)
            if holder is not None and holder != sku:
                row.error(
                    "slug",
                    IssueCode.SLUG_TAKEN,
                    f"slug «{plan.slug}» уже занят товаром {holder}. Если slug меняется и у "
                    f"товара {holder}, выполните переименование в два импорта",
                )
            elif plan.slug in slugs:
                row.error(
                    "slug",
                    IssueCode.DUPLICATE_ROW,
                    f"slug «{plan.slug}» уже указан у товара {slugs[plan.slug]}",
                )
            slugs.setdefault(plan.slug, sku)

            if plan.external_id is not None:
                owner = external_ids.get(plan.external_id)
                own_id = plan.existing.id if plan.existing is not None else None
                if owner is not None and owner.id != own_id:
                    whose = "удалённым товаром" if owner.is_deleted else "товаром"
                    row.error(
                        "external_id",
                        IssueCode.EXTERNAL_ID_TAKEN,
                        f"Внешний идентификатор уже занят {whose} {owner.sku}",
                    )
                elif plan.external_id in externals:
                    row.error(
                        "external_id",
                        IssueCode.DUPLICATE_ROW,
                        f"Внешний идентификатор уже указан у товара {externals[plan.external_id]}",
                    )
                externals.setdefault(plan.external_id, sku)
            if not row.ok:
                self.failed_skus.add(sku)

    def _product_ref(self, row: _Row) -> str | None:
        """Артикул в дочернем листе: обязан быть на листе Products."""
        sku: str | None = row.get(
            "sku", as_identifier, pattern=SKU_PATTERN, max_length=64, hint=SKU_HINT
        )
        if sku is None:
            return None
        if sku not in self.product_rows:
            row.error(
                "sku",
                IssueCode.UNKNOWN_SKU,
                f"Товара {sku} нет на листе Products: связанные данные задаются только "
                "для товаров из файла",
            )
            return None
        return sku

    # --------------------------------------------------------------- Prices
    def _prices(self) -> None:
        for row in self._rows(Sheet.PRICES):
            sku = self._product_ref(row)
            min_qty = row.get(
                "min_qty",
                as_decimal,
                max_digits=QTY_DIGITS,
                decimal_places=QTY_PLACES,
                greater_than=Decimal(0),
            )
            max_qty = None
            if row.raw("max_qty") is not None:
                max_qty = row.get(
                    "max_qty",
                    as_decimal,
                    max_digits=QTY_DIGITS,
                    decimal_places=QTY_PLACES,
                    greater_than=Decimal(0),
                )
            price = row.get(
                "price",
                as_decimal,
                max_digits=MONEY_DIGITS,
                decimal_places=MONEY_PLACES,
                at_least=Decimal(0),
            )
            if sku is None:
                continue
            if row.ok:
                try:
                    PriceTierInput.model_validate(
                        {"min_qty": min_qty, "max_qty": max_qty, "price": price}
                    )
                except ValidationError as exc:
                    row.schema_errors(exc, lambda loc: str(loc[0]) if loc else "max_qty")
            if not row.ok:
                self.failed_skus.add(sku)
                continue
            self.tiers.setdefault(sku, []).append(
                TierPlan(row=row.row.number, min_qty=min_qty, max_qty=max_qty, price=price)
            )

    # ---------------------------------------------------- ProductAttributes
    def _product_attributes(self) -> None:
        seen: dict[str, set[tuple[str, str]]] = {}
        for row in self._rows(Sheet.PRODUCT_ATTRIBUTES):
            sku = self._product_ref(row)
            code = row.get(
                "attribute_code", as_identifier, pattern=CODE_PATTERN, max_length=64, hint=CODE_HINT
            )
            if sku is None or code is None:
                if sku is not None:
                    self.failed_skus.add(sku)
                continue
            if not self._attribute_known(code):
                row.error(
                    "attribute_code",
                    IssueCode.ATTRIBUTE_NOT_FOUND,
                    f"Характеристика «{code}» не найдена ни в каталоге, ни на листе Attributes",
                )
                self.failed_skus.add(sku)
                continue
            value_type = self._attribute_type(code)
            if value_type is None:
                self.failed_skus.add(sku)
                continue

            value = self._attribute_value(row, code, value_type)
            if value is None:
                self.failed_skus.add(sku)
                continue
            key = value.key() if value_type is AttributeValueType.OPTION else (code, "")
            if key in seen.setdefault(sku, set()):
                message = (
                    f"Вариант «{value.option_slug}» уже указан для этого товара"
                    if value_type is AttributeValueType.OPTION
                    else f"У характеристики типа {value_type.value} может быть только одно "
                    "значение; несколько допускается только у OPTION"
                )
                row.error("attribute_code", IssueCode.DUPLICATE_ROW, message)
                self.failed_skus.add(sku)
                continue
            seen[sku].add(key)
            self.values.setdefault(sku, []).append(value)

    def _attribute_value(
        self, row: _Row, code: str, value_type: AttributeValueType
    ) -> AttributeValuePlan | None:
        plan = AttributeValuePlan(row=row.row.number, attribute_code=code, value_type=value_type)
        if value_type is AttributeValueType.STRING:
            plan.value_string = row.get("value", as_text, max_length=255, required=True)
        elif value_type is AttributeValueType.NUMBER:
            plan.value_numeric = row.get(
                "value", as_decimal, max_digits=QTY_DIGITS, decimal_places=QTY_PLACES
            )
        elif value_type is AttributeValueType.BOOLEAN:
            plan.value_bool = row.get("value", as_bool)
        else:
            plan.option_slug = row.get(
                "value", as_identifier, pattern=SLUG_PATTERN, max_length=LEN_SLUG, hint=SLUG_HINT
            )
            if plan.option_slug is not None and not self._option_known(code, plan.option_slug):
                row.error(
                    "value",
                    IssueCode.OPTION_NOT_FOUND,
                    f"У характеристики «{code}» нет варианта «{plan.option_slug}». Добавьте его "
                    "на лист AttributeOptions",
                )
        return plan if row.ok else None

    # --------------------------------------------------------- ProductSpecs
    def _product_specs(self) -> None:
        for row in self._rows(Sheet.PRODUCT_SPECS):
            sku = self._product_ref(row)
            name = row.get("name", as_text, max_length=SPEC_NAME_MAX, required=True)
            value = row.get("value", as_text, max_length=SPEC_VALUE_MAX, multiline=True)
            if sku is None:
                continue
            if name is not None and name in self.specs.get(sku, {}):
                row.error("name", IssueCode.DUPLICATE_ROW, f"«{name}» уже указано для этого товара")
            if not row.ok:
                self.failed_skus.add(sku)
                continue
            assert name is not None
            self.specs.setdefault(sku, {})[name] = value or ""
            self.spec_rows.setdefault(sku, row.row.number)

        for sku, specs in self.specs.items():
            try:
                ProductUpdate.model_validate({"specs": specs})
            except ValidationError as exc:
                row = _Row(
                    self,
                    Sheet.PRODUCT_SPECS,
                    self._row_of(Sheet.PRODUCT_SPECS, self.spec_rows[sku]),
                )
                row.schema_errors(exc, lambda _loc: "name")
                self.failed_skus.add(sku)

    # ------------------------------------------------------------- итог
    def _finalize_products(self) -> None:
        price_list_reported = False
        for sku, plan in self.products.items():
            plan.tiers = sorted(self.tiers.get(sku, []), key=lambda tier: tier.min_qty)
            plan.attributes = self.values.get(sku, [])
            plan.specs = self.specs.get(sku, {})
            if sku in self.failed_skus:
                continue

            row = _Row(self, Sheet.PRODUCTS, self._row_of(Sheet.PRODUCTS, plan.row))
            existing = plan.existing
            desired = _pricing_key(
                plan.pricing_type.value,
                ((tier.min_qty, tier.max_qty, tier.price) for tier in plan.tiers),
            )
            if existing is not None:
                current = _pricing_key(
                    existing.pricing_type,
                    (
                        (tier.min_qty, tier.max_qty, tier.price)
                        for tier in self.snapshot.tiers.get(existing.id, [])
                    ),
                )
            else:
                # Состояние нового товара в Admin API: FIXED без ступеней.
                current = _pricing_key(PricingType.FIXED.value, ())

            # Неизменная цена не перепроверяется: в базе она уже есть,
            # и старые данные не должны блокировать импорт остального.
            if desired != current:
                plan.pricing_changed = True
                if self.snapshot.price_list is None:
                    if not price_list_reported:
                        self.errors.add(
                            sheet=Sheet.PRICES,
                            row=None,
                            column=None,
                            code=IssueCode.PRICE_LIST_MISSING,
                            message="Публичный прайс-лист не настроен: цены импортировать нельзя",
                        )
                        price_list_reported = True
                    self.failed_skus.add(sku)
                    continue
                try:
                    PricingUpdate.model_validate(
                        {
                            "pricing_type": plan.pricing_type,
                            "tiers": [
                                {
                                    "min_qty": tier.min_qty,
                                    "max_qty": tier.max_qty,
                                    "price": tier.price,
                                }
                                for tier in plan.tiers
                            ],
                        }
                    )
                except ValidationError as exc:
                    for error in exc.errors(include_url=False):
                        row.error(
                            "pricing_type",
                            IssueCode.INVALID_PRICING,
                            f"Цены товара: {_pydantic_message(error)}",
                            value=plan.pricing_type.value,
                        )
                    self.failed_skus.add(sku)
                    continue

            if existing is None:
                if plan.pricing_type is not PricingType.ON_REQUEST and not plan.tiers:
                    row.warning(
                        "pricing_type",
                        IssueCode.PRODUCT_WITHOUT_PRICE,
                        "Цена не задана (нет строк на листе Prices): на витрине товар будет "
                        "с кнопкой «Запросить цену»",
                    )
                if not plan.category_slugs:
                    row.warning(
                        "categories",
                        IssueCode.PRODUCT_WITHOUT_CATEGORY,
                        "У товара нет категорий: в разделах каталога он показан не будет",
                    )
                plan.categories_changed = bool(plan.category_slugs)
                plan.attributes_changed = bool(plan.attributes)
                plan.specs_changed = bool(plan.specs)
            else:
                plan.field_changes = self._product_changes(existing, plan)
                plan.categories_changed = _categories_differ(existing, plan.category_slugs)
                plan.attributes_changed = Counter(
                    _stored_value_key(item) for item in existing.attribute_values
                ) != Counter(value.key() for value in plan.attributes)
                current_specs = {
                    str(key): str(value) for key, value in (existing.specs or {}).items()
                }
                plan.specs_changed = current_specs != plan.specs

            self.plan.products.append(plan)

    def _product_changes(self, existing: Product, plan: ProductPlan) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        for name in PRODUCT_SCALARS:
            old = getattr(existing, name)
            new = getattr(plan, name)
            new = new.value if isinstance(new, ProductStatus) else new
            if _norm(old) != _norm(new):
                changes[name] = {"old": old, "new": new}
        if existing.min_order_qty != plan.min_order_qty:
            changes["min_order_qty"] = {
                "old": str(existing.min_order_qty),
                "new": str(plan.min_order_qty),
            }
        current = {item.locale: item for item in existing.translations}
        locales = [
            locale
            for locale, texts in plan.translations.items()
            if _texts_differ(current.get(locale), texts)
        ]
        if locales:
            changes["translations"] = {"old": None, "new": sorted(locales)}
        return changes
