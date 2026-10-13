"""Проверка книги пакетного импорта (ZIP).

Наследник обычного валидатора: правила полей, уникальность артикулов
и slug, категории, характеристики, цены проверяются тем же кодом и теми
же Pydantic-схемами Admin API. Здесь — только отличия пакета
(bundle_format.py):

* на листе товаров обязателен только артикул. Отсутствующая колонка или
  пустая ячейка — «не менять»: у существующего товара остаётся текущее
  значение, у нового — значение по умолчанию (опубликован, активен,
  шт., партия 1, цена по запросу);
* связи товара (категории, цены, характеристики, описательные
  характеристики) заменяются только у тех товаров, для которых они
  заданы в файле; у остальных не трогаются;
* категория — slug, название или путь «Раздел / Подраздел»;
* цена — одной колонкой «Цена» или ступенями «Цена от N» прямо на листе
  товаров; тип цены выводится из ступеней, если не указан явно;
* «Фото», «Схема», «Остаток», «Резерв» разбираются здесь, а сверяются
  с архивом и складом в планировщике пакета (bundle_plan.py).
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.db.types import LEN_SLUG
from app.modules.catalog.enums import AttributeValueType, ProductStatus
from app.modules.catalog.models import Product
from app.modules.catalog.schemas_admin import SLUG_PATTERN
from app.modules.catalog.schemas_admin_products import SKU_PATTERN, ProductCreate, ProductUpdate
from app.modules.imports.bundle_format import (
    ATTRIBUTE_PREFIX,
    CURRENCY,
    FILE_LIST_SEPARATORS,
    PHOTO_COLUMN_PREFIX,
    PHOTOS,
    PRICE,
    PRICE_FROM_PREFIX,
    RESERVED,
    SCHEMES,
    SPEC_PREFIX,
    SPECS,
    STOCK,
    product_slug,
)
from app.modules.imports.cells import (
    CellError,
    as_bool,
    as_decimal,
    as_enum,
    as_identifier,
    as_list,
    as_text,
)
from app.modules.imports.issues import IssueCode
from app.modules.imports.snapshot import CatalogSnapshot, option_by_slug
from app.modules.imports.validator import (
    MONEY_DIGITS,
    MONEY_PLACES,
    PRODUCT_TEXTS,
    QTY_DIGITS,
    QTY_PLACES,
    SKU_HINT,
    SLUG_HINT,
    SPEC_NAME_MAX,
    SPEC_VALUE_MAX,
    AttributeValuePlan,
    CatalogImportValidator,
    ProductPlan,
    TierPlan,
    _Row,
    _translated_column,
    current_category_slugs,
)
from app.modules.imports.xlsx_format import Sheet
from app.modules.imports.xlsx_reader import ParsedWorkbook
from app.modules.pricing.enums import PricingType

# Шаг количества: соседние ступени «от 1» и «от 100» становятся
# диапазонами [1; 99.999] и [100; ...] — без разрыва и без пересечения
# (границы включающие, точность количества — три знака).
QTY_STEP = Decimal("0.001")

DEFAULT_STATUS = ProductStatus.PUBLISHED
DEFAULT_UNIT = "pcs"
DEFAULT_MIN_ORDER_QTY = Decimal("1")

_CATEGORY_PATH_SEPARATOR = re.compile(r"\s*(?:/|>|→)\s*")


def _fold(text: str) -> str:
    """Название для сравнения: без регистра, «ё» = «е», пробелы схлопнуты."""
    return re.sub(r"\s+", " ", text.replace("ё", "е").replace("Ё", "Е")).strip().casefold()


class BundleImportValidator(CatalogImportValidator):
    def __init__(
        self,
        workbook: ParsedWorkbook,
        snapshot: CatalogSnapshot,
        *,
        locales: list[str],
        default_locale: str,
    ) -> None:
        super().__init__(workbook, snapshot, locales=locales, default_locale=default_locale)
        # Что задано колонками листа товаров (а не отдельными листами).
        self.column_tiers: dict[str, list[TierPlan]] = {}
        self.column_values: dict[str, list[AttributeValuePlan]] = {}
        self.column_specs: dict[str, dict[str, str]] = {}
        self.explicit_pricing: dict[str, PricingType] = {}
        # Товары, у которых связь задана файлом и потому заменяется.
        self.attributes_managed: set[str] = set()
        self.specs_managed: set[str] = set()
        self._category_names: dict[str, list[str]] | None = None
        self._category_paths: dict[str, list[str]] | None = None

    # ================================================================ товары
    def _products(self) -> None:
        live_lower = self.snapshot.live_skus_by_lower()
        deleted = self.snapshot.deleted_skus()
        file_lower: dict[str, str] = {}
        columns = self._columns(Sheet.PRODUCTS)

        for row in self._rows(Sheet.PRODUCTS):
            sku = row.get("sku", as_identifier, pattern=SKU_PATTERN, max_length=64, hint=SKU_HINT)
            if sku is None:
                continue
            if not self._register_sku(row, sku, live_lower, deleted, file_lower):
                continue
            existing = self.snapshot.products.get(sku)

            def present(column: str, row: _Row = row) -> bool:
                return column in columns and row.raw(column) is not None

            slug = (
                row.get(
                    "slug",
                    as_identifier,
                    pattern=SLUG_PATTERN,
                    max_length=LEN_SLUG,
                    hint=SLUG_HINT,
                )
                if present("slug")
                else None
            )
            status = row.get("status", as_enum, ProductStatus) if present("status") else None
            is_active = row.get("is_active", as_bool) if present("is_active") else None
            is_featured = row.get("is_featured", as_bool) if present("is_featured") else None
            unit = row.get("unit", as_text, max_length=16) if present("unit") else None
            min_order_qty = (
                row.get(
                    "min_order_qty",
                    as_decimal,
                    max_digits=QTY_DIGITS,
                    decimal_places=QTY_PLACES,
                    greater_than=Decimal(0),
                )
                if present("min_order_qty")
                else None
            )
            if present("pricing_type"):
                pricing_type = row.get("pricing_type", as_enum, PricingType)
                if pricing_type is not None:
                    self.explicit_pricing[sku] = pricing_type
            brand = row.get("brand", as_text, max_length=255) if present("brand") else None
            external_id = (
                row.get("external_id", as_text, max_length=64) if present("external_id") else None
            )
            texts = self._bundle_texts(row, existing, present)
            category_slugs = self._bundle_categories(row) if present("categories") else None

            self._bundle_currency(row, present)
            self._bundle_prices(row, sku, columns)
            self._bundle_specs(row, sku, columns)
            self._bundle_attributes(row, sku, columns)
            photos = self._file_list(row, columns, PHOTOS, PHOTO_COLUMN_PREFIX)
            schemes = self._file_list(row, columns, SCHEMES, None)
            stock = self._quantity(row, STOCK) if present(STOCK) else None
            reserved = self._quantity(row, RESERVED) if present(RESERVED) else None
            if stock is not None and reserved is not None and reserved > stock:
                row.error(
                    RESERVED,
                    IssueCode.STOCK_INVALID,
                    f"Резерв {reserved.normalize():f} больше остатка {stock.normalize():f}",
                )

            name = (texts.get(self.default_locale) or {}).get("name")
            if existing is None and name is None and not row.is_bad(f"name_{self.default_locale}"):
                row.error(
                    f"name_{self.default_locale}",
                    IssueCode.REQUIRED,
                    "Для нового товара нужно название",
                )

            if not row.ok:
                self.failed_skus.add(sku)
                continue
            assert name is not None

            payload_fields = self._resolve_fields(
                existing,
                sku=sku,
                name=name,
                slug=slug,
                status=status,
                is_active=is_active,
                is_featured=is_featured,
                unit=unit,
                min_order_qty=min_order_qty,
                brand=(brand, present("brand")),
                external_id=(external_id, present("external_id")),
            )
            try:
                payload = ProductCreate.model_validate({**payload_fields, "translations": texts})
            except ValidationError as exc:
                row.schema_errors(exc, _translated_column({"translations": "name"}))
                self.failed_skus.add(sku)
                continue

            plan = ProductPlan(
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
                # Настоящий тип выводится при итоговой сверке цен.
                pricing_type=PricingType.ON_REQUEST,
                translations=dict(payload.translations),
                category_slugs=(
                    category_slugs
                    if category_slugs is not None
                    else (current_category_slugs(existing) if existing is not None else [])
                ),
                existing=existing,
                photos=photos,
                schemes=schemes,
                stock=stock,
                reserved=reserved,
            )
            self.products[sku] = plan

        self._check_product_uniqueness()

    def _register_sku(
        self,
        row: _Row,
        sku: str,
        live_lower: dict[str, str],
        deleted: set[str],
        file_lower: dict[str, str],
    ) -> bool:
        """Дубли и конфликты регистра — те же правила, что у обычного импорта."""
        if sku in self.product_rows:
            row.error(
                "sku",
                IssueCode.DUPLICATE_ROW,
                f"Артикул {sku} уже указан в строке {self.product_rows[sku]}",
            )
            return False
        self.product_rows[sku] = row.row.number

        other = file_lower.get(sku.lower())
        if other is not None:
            row.error(
                "sku",
                IssueCode.SKU_CASE_CONFLICT,
                f"Артикулы {sku} и {other} различаются только регистром",
            )
        file_lower.setdefault(sku.lower(), sku)

        if sku not in self.snapshot.products:
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
        return True

    def _resolve_fields(
        self,
        existing: Product | None,
        *,
        sku: str,
        name: str,
        slug: str | None,
        status: ProductStatus | None,
        is_active: bool | None,
        is_featured: bool | None,
        unit: str | None,
        min_order_qty: Decimal | None,
        brand: tuple[str | None, bool],
        external_id: tuple[str | None, bool],
    ) -> dict[str, Any]:
        """Значение из файла, иначе текущее, иначе значение по умолчанию."""

        def keep(value: Any, attribute: str, default: Any) -> Any:
            if value is not None:
                return value
            return getattr(existing, attribute) if existing is not None else default

        def optional(pair: tuple[str | None, bool], attribute: str) -> str | None:
            value, given = pair
            if given:
                return value
            return getattr(existing, attribute) if existing is not None else None

        return {
            "sku": sku,
            "slug": keep(slug, "slug", None) or product_slug(name, sku),
            "status": status
            or (ProductStatus(existing.status) if existing is not None else DEFAULT_STATUS),
            "is_active": keep(is_active, "is_active", True),
            "is_featured": keep(is_featured, "is_featured", False),
            "unit": keep(unit, "unit", DEFAULT_UNIT),
            "min_order_qty": keep(min_order_qty, "min_order_qty", DEFAULT_MIN_ORDER_QTY),
            "brand": optional(brand, "brand"),
            "external_id": optional(external_id, "external_id"),
        }

    def _bundle_texts(
        self, row: _Row, existing: Product | None, present: Any
    ) -> dict[str, dict[str, str | None]]:
        """Переводы: ячейка из файла, иначе текущий текст товара."""
        current = (
            {item.locale: item for item in existing.translations} if existing is not None else {}
        )
        columns = self._columns(Sheet.PRODUCTS)
        result: dict[str, dict[str, str | None]] = {}
        for locale in self.locales:
            locale_columns = [f"{name}_{locale}" for name in PRODUCT_TEXTS]
            translation = current.get(locale)
            if (
                locale != self.default_locale
                and translation is None
                and not any(column in columns for column in locale_columns)
            ):
                continue
            values: dict[str, str | None] = {}
            for name, (max_length, multiline) in PRODUCT_TEXTS.items():
                column = f"{name}_{locale}"
                if present(column):
                    values[name] = row.get(
                        column, as_text, max_length=max_length, multiline=multiline
                    )
                else:
                    values[name] = getattr(translation, name) if translation is not None else None
            if values["name"] is None:
                if locale != self.default_locale and any(
                    value is not None for value in values.values()
                ):
                    row.error(
                        f"name_{locale}",
                        IssueCode.REQUIRED,
                        f"Для перевода {locale} заполните name_{locale}",
                    )
                if locale != self.default_locale:
                    continue
            result[locale] = values
        return result

    # ------------------------------------------------------------- категории
    def _bundle_categories(self, row: _Row) -> list[str] | None:
        try:
            tokens = as_list(row.raw("categories"))
        except CellError as exc:
            row.error("categories", exc.code, exc.message)
            return None
        slugs: list[str] = []
        for token in tokens:
            slug = self._resolve_category(row, token)
            if slug is None:
                continue
            if slug in slugs:
                row.error(
                    "categories", IssueCode.DUPLICATE_ROW, f"Категория «{token}» указана дважды"
                )
                continue
            slugs.append(slug)
        return slugs

    def _resolve_category(self, row: _Row, token: str) -> str | None:
        """slug, название или путь «Раздел / Подраздел» -> slug категории."""
        if self._category_known(token):
            return token
        names, paths = self._category_index()
        key = _fold(token)
        by_path = _CATEGORY_PATH_SEPARATOR.search(token) is not None
        candidates = (
            paths.get(" / ".join(_fold(part) for part in _CATEGORY_PATH_SEPARATOR.split(token)))
            if by_path
            else names.get(key)
        ) or []
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            row.error(
                "categories",
                IssueCode.CATEGORY_AMBIGUOUS,
                f"Категорий с названием «{token}» несколько. Укажите путь "
                "(«Раздел / Подраздел») или slug: " + ", ".join(sorted(candidates)),
                value=token,
            )
            return None
        if token in self.snapshot.deleted_category_slugs:
            row.error("categories", IssueCode.CATEGORY_DELETED, f"Категория «{token}» удалена")
            return None
        row.error(
            "categories",
            IssueCode.CATEGORY_NOT_FOUND,
            f"Категория «{token}» не существует",
            value=token,
        )
        return None

    def _category_index(self) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        """Название -> slug и путь названий -> slug: каталог плюс лист Categories."""
        if self._category_names is not None and self._category_paths is not None:
            return self._category_names, self._category_paths

        names_by_slug: dict[str, str] = {}
        parent_by_slug: dict[str, str | None] = {}
        by_id = self.snapshot.categories_by_id
        for slug, category in self.snapshot.categories.items():
            translations = {item.locale: item.name for item in category.translations}
            names_by_slug[slug] = translations.get(self.default_locale) or slug
            parent = by_id.get(category.parent_id) if category.parent_id is not None else None
            parent_by_slug[slug] = parent.slug if parent is not None else None
        for slug, plan in self.categories.items():
            translation = plan.translations.get(self.default_locale)
            names_by_slug[slug] = translation.name if translation is not None else slug
            parent_by_slug[slug] = plan.parent_slug

        names: dict[str, list[str]] = {}
        paths: dict[str, list[str]] = {}
        for slug, name in names_by_slug.items():
            names.setdefault(_fold(name), []).append(slug)
            chain: list[str] = []
            current: str | None = slug
            seen: set[str] = set()
            while current is not None and current not in seen:
                seen.add(current)
                chain.append(_fold(names_by_slug.get(current, current)))
                current = parent_by_slug.get(current)
            # Путь можно писать от любого уровня: «Качели / Сиденья»
            # и «Площадки / Качели / Сиденья» находят одну категорию.
            chain.reverse()
            for start in range(len(chain) - 1):
                paths.setdefault(" / ".join(chain[start:]), []).append(slug)
        self._category_names, self._category_paths = names, paths
        return names, paths

    # ----------------------------------------------------------------- цены
    def _bundle_currency(self, row: _Row, present: Any) -> None:
        if not present(CURRENCY):
            return
        currency = row.get(CURRENCY, as_text, max_length=8)
        if currency is None:
            return
        expected = self.snapshot.price_list.currency if self.snapshot.price_list else None
        normalized = currency.strip().upper().replace("₸", "KZT").replace("ТГ", "KZT")
        if expected is not None and normalized != expected:
            row.error(
                CURRENCY,
                IssueCode.CURRENCY_MISMATCH,
                f"Цены импортируются в валюте прайс-листа ({expected}), а не {currency}",
            )

    def _bundle_prices(self, row: _Row, sku: str, columns: set[str]) -> None:
        """«Цена» и «Цена от N» -> ступени публичного прайс-листа."""
        points: list[tuple[Decimal, str]] = []
        if PRICE in columns and row.raw(PRICE) is not None:
            points.append((Decimal(1), PRICE))
        for column in sorted(columns):
            if not column.startswith(PRICE_FROM_PREFIX) or row.raw(column) is None:
                continue
            try:
                quantity = as_decimal(
                    column.removeprefix(PRICE_FROM_PREFIX),
                    max_digits=QTY_DIGITS,
                    decimal_places=QTY_PLACES,
                    greater_than=Decimal(0),
                )
            except CellError:
                row.error(
                    column,
                    IssueCode.INVALID_VALUE,
                    "В заголовке «Цена от N» N должно быть положительным числом",
                )
                continue
            if any(existing == quantity for existing, _ in points):
                row.error(
                    column,
                    IssueCode.PRICE_CONFLICT,
                    f"Цена от {quantity.normalize():f} задана дважды "
                    "(например, колонками «Цена» и «Цена от 1»)",
                )
                continue
            points.append((quantity, column))
        if not points:
            return

        points.sort(key=lambda item: item[0])
        tiers: list[TierPlan] = []
        for index, (quantity, column) in enumerate(points):
            price = row.get(
                column,
                as_decimal,
                max_digits=MONEY_DIGITS,
                decimal_places=MONEY_PLACES,
                at_least=Decimal(0),
            )
            if price is None:
                continue
            upper = points[index + 1][0] - QTY_STEP if index + 1 < len(points) else None
            tiers.append(TierPlan(row=row.row.number, min_qty=quantity, max_qty=upper, price=price))
        if row.ok:
            self.column_tiers[sku] = tiers

    def _prices(self) -> None:
        super()._prices()
        for sku in sorted(set(self.column_tiers) & set(self.tiers)):
            self._conflict(sku, "Цены товара заданы и на листе товаров, и на листе Prices")
        for sku, tiers in self.column_tiers.items():
            self.tiers.setdefault(sku, tiers)

    # ------------------------------------------------ описательные характеристики
    def _bundle_specs(self, row: _Row, sku: str, columns: set[str]) -> None:
        """«Характеристики» (Имя: значение; ...) и колонки «хар: Имя»."""
        specs: dict[str, str] = {}

        def add(name: str, value: str, column: str) -> None:
            if not name:
                row.error(column, IssueCode.INVALID_VALUE, "Пустое название характеристики")
            elif name in specs:
                row.error(column, IssueCode.DUPLICATE_ROW, f"«{name}» указано дважды")
            elif len(name) > SPEC_NAME_MAX or len(value) > SPEC_VALUE_MAX:
                row.error(
                    column,
                    IssueCode.INVALID_VALUE,
                    f"Название — до {SPEC_NAME_MAX}, значение — до {SPEC_VALUE_MAX} символов",
                )
            else:
                specs[name] = value

        if SPECS in columns and row.raw(SPECS) is not None:
            text = row.get(SPECS, as_text, max_length=10_000, multiline=True)
            for chunk in re.split(r"[;\n]+", text or ""):
                if not chunk.strip():
                    continue
                name, separator, value = chunk.partition(":")
                if not separator:
                    row.error(
                        SPECS,
                        IssueCode.INVALID_VALUE,
                        f"«{chunk.strip()}»: ожидается «Название: значение»",
                    )
                    continue
                add(name.strip(), value.strip(), SPECS)
        for column in sorted(columns):
            if not column.startswith(SPEC_PREFIX) or row.raw(column) is None:
                continue
            value = row.get(column, as_text, max_length=SPEC_VALUE_MAX, multiline=True)
            if value is not None:
                add(column.removeprefix(SPEC_PREFIX).strip(), value, column)
        if specs and row.ok:
            self.column_specs[sku] = specs

    def _product_specs(self) -> None:
        super()._product_specs()
        for sku in sorted(set(self.column_specs) & set(self.specs)):
            self._conflict(
                sku,
                "Описательные характеристики заданы и на листе товаров, и на листе ProductSpecs",
            )
        for sku, specs in self.column_specs.items():
            try:
                ProductUpdate.model_validate({"specs": specs})
            except ValidationError as exc:
                row = self._product_row(sku)
                row.schema_errors(exc, lambda _loc: SPECS)
                self.failed_skus.add(sku)
                continue
            self.specs.setdefault(sku, specs)
        self.specs_managed = set(self.specs)

    # -------------------------------------------------------- характеристики
    def _bundle_attributes(self, row: _Row, sku: str, columns: set[str]) -> None:
        """Колонки «attr:код» — значения характеристик-фильтров."""
        values: list[AttributeValuePlan] = []
        for column in sorted(columns):
            if not column.startswith(ATTRIBUTE_PREFIX) or row.raw(column) is None:
                continue
            code = column.removeprefix(ATTRIBUTE_PREFIX)
            if not self._attribute_known(code):
                row.error(
                    column,
                    IssueCode.ATTRIBUTE_NOT_FOUND,
                    f"Характеристика «{code}» не найдена ни в каталоге, ни на листе Attributes",
                )
                continue
            value_type = self._attribute_type(code)
            if value_type is None:
                row.ok = False
                continue
            values.extend(self._column_values(row, column, code, value_type))
        if values and row.ok:
            self.column_values[sku] = values

    def _column_values(
        self, row: _Row, column: str, code: str, value_type: AttributeValueType
    ) -> list[AttributeValuePlan]:
        plan = AttributeValuePlan(row=row.row.number, attribute_code=code, value_type=value_type)
        if value_type is AttributeValueType.STRING:
            plan.value_string = row.get(column, as_text, max_length=255, required=True)
            return [plan] if plan.value_string is not None else []
        if value_type is AttributeValueType.NUMBER:
            plan.value_numeric = row.get(
                column, as_decimal, max_digits=QTY_DIGITS, decimal_places=QTY_PLACES
            )
            return [plan] if plan.value_numeric is not None else []
        if value_type is AttributeValueType.BOOLEAN:
            plan.value_bool = row.get(column, as_bool)
            return [plan] if plan.value_bool is not None else []

        # OPTION: несколько вариантов через «;», вариант — slug или название.
        try:
            tokens = as_list(row.raw(column))
        except CellError as exc:
            row.error(column, exc.code, exc.message)
            return []
        result: list[AttributeValuePlan] = []
        for token in tokens:
            slug = self._option_slug(code, token)
            if slug is None:
                row.error(
                    column,
                    IssueCode.OPTION_NOT_FOUND,
                    f"У характеристики «{code}» нет варианта «{token}». Добавьте его "
                    "на лист AttributeOptions или в админке",
                    value=token,
                )
                continue
            if any(item.option_slug == slug for item in result):
                continue
            result.append(
                AttributeValuePlan(
                    row=row.row.number,
                    attribute_code=code,
                    value_type=value_type,
                    option_slug=slug,
                )
            )
        return result

    def _option_slug(self, code: str, token: str) -> str | None:
        if re.fullmatch(SLUG_PATTERN, token) and self._option_known(code, token):
            return token
        key = _fold(token)
        attribute = self.snapshot.attributes.get(code)
        if attribute is not None:
            for slug, option in option_by_slug(attribute).items():
                if any(_fold(str(value)) == key for value in (option.value_i18n or {}).values()):
                    return slug
        for plan in self.plan.options:
            if plan.attribute_code == code and any(
                _fold(value) == key for value in plan.values.values()
            ):
                return plan.slug
        return None

    def _product_attributes(self) -> None:
        super()._product_attributes()
        for sku in sorted(set(self.column_values) & set(self.values)):
            self._conflict(
                sku, "Характеристики заданы и на листе товаров, и на листе ProductAttributes"
            )
        for sku, values in self.column_values.items():
            self.values.setdefault(sku, values)
        self.attributes_managed = set(self.values)

    # ---------------------------------------------------------- фото, склад
    def _file_list(
        self, row: _Row, columns: set[str], column: str, numbered_prefix: str | None
    ) -> list[str] | None:
        """Имена файлов: «a.jpg; b.jpg» и/или колонки «Фото 1», «Фото 2», ..."""
        names: list[str] = []
        sources: list[str] = []
        if column in columns and row.raw(column) is not None:
            sources.append(column)
        if numbered_prefix is not None:
            numbered = sorted(
                (
                    int(name.removeprefix(numbered_prefix)),
                    name,
                )
                for name in columns
                if name.startswith(numbered_prefix) and row.raw(name) is not None
            )
            sources.extend(name for _, name in numbered)
        if not sources:
            return None
        for source in sources:
            text = row.get(source, as_text, max_length=4000, multiline=True)
            if text is None:
                continue
            names.extend(item.strip() for item in FILE_LIST_SEPARATORS.split(text) if item.strip())
        return names or None

    def _quantity(self, row: _Row, column: str) -> Decimal | None:
        value: Decimal | None = row.get(
            column,
            as_decimal,
            max_digits=QTY_DIGITS,
            decimal_places=QTY_PLACES,
            at_least=Decimal(0),
        )
        return value

    # --------------------------------------------------------------- итог
    def _finalize_products(self) -> None:
        for sku, plan in self.products.items():
            existing = plan.existing
            explicit = self.explicit_pricing.get(sku)
            managed = sku in self.tiers or explicit is not None
            if not managed:
                if existing is not None:
                    # Цены не заданы — остаются текущими (сравнение даст
                    # «без изменений»).
                    plan.pricing_type = PricingType(existing.pricing_type)
                    self.tiers[sku] = [
                        TierPlan(
                            row=plan.row,
                            min_qty=tier.min_qty,
                            max_qty=tier.max_qty,
                            price=tier.price,
                        )
                        for tier in self.snapshot.tiers.get(existing.id, [])
                    ]
                else:
                    plan.pricing_type = PricingType.ON_REQUEST
                    self.warnings.add(
                        sheet=Sheet.PRODUCTS,
                        row=plan.row,
                        column=PRICE,
                        code=IssueCode.PRODUCT_WITHOUT_PRICE,
                        message="Цена не задана: на витрине товар будет с кнопкой «Запросить цену»",
                    )
            elif explicit is not None:
                plan.pricing_type = explicit
            else:
                tiers = self.tiers.get(sku, [])
                single = (
                    len(tiers) == 1 and tiers[0].min_qty == Decimal(1) and tiers[0].max_qty is None
                )
                plan.pricing_type = PricingType.FIXED if single else PricingType.TIERED

        super()._finalize_products()

        # Связи, не заданные файлом, у существующего товара не трогаются.
        for plan in self.plan.products:
            existing = plan.existing
            if existing is None:
                continue
            if plan.sku not in self.attributes_managed:
                plan.attributes_changed = False
            if plan.sku not in self.specs_managed:
                plan.specs = {str(key): str(value) for key, value in (existing.specs or {}).items()}
                plan.specs_changed = False

    def _product_row(self, sku: str) -> _Row:
        return _Row(self, Sheet.PRODUCTS, self._row_of(Sheet.PRODUCTS, self.product_rows[sku]))

    def _conflict(self, sku: str, message: str) -> None:
        row = self._product_row(sku)
        row.error("sku", IssueCode.RELATION_CONFLICT, message, value=sku)
        self.failed_skus.add(sku)


__all__ = ["BundleImportValidator"]
