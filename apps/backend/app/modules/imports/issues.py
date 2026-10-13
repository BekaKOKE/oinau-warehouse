"""Ошибки и предупреждения в данных импортируемого файла.

Каждая запись указывает лист, строку (номер строки Excel, заголовок —
строка 1) и колонку, чтобы администратор нашёл ячейку сразу. Трейсов
и внутренних имён таблиц здесь нет и быть не должно.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Сколько записей возвращается и сохраняется. Остальные только
# считаются: тысяча одинаковых ошибок не помогает, а ответ раздувает.
MAX_REPORTED_ISSUES = 500
MAX_VALUE_PREVIEW = 100


class IssueCode:
    # структура книги
    MISSING_SHEET = "missing_sheet"
    NOT_A_WORKSHEET = "not_a_worksheet"
    MISSING_HEADER = "missing_header"
    MISSING_COLUMN = "missing_column"
    UNKNOWN_COLUMN = "unknown_column"
    DUPLICATE_COLUMN = "duplicate_column"
    VALUE_WITHOUT_HEADER = "value_without_header"
    TOO_MANY_ROWS = "too_many_rows"
    EMPTY_WORKBOOK = "empty_workbook"
    # ячейки
    FORMULA_NOT_ALLOWED = "formula_not_allowed"
    EXCEL_ERROR_VALUE = "excel_error_value"
    UNSUPPORTED_VALUE = "unsupported_value"
    REQUIRED = "required"
    INVALID_VALUE = "invalid_value"
    # ссылки и уникальность
    DUPLICATE_ROW = "duplicate_row"
    SKU_CASE_CONFLICT = "sku_case_conflict"
    SLUG_TAKEN = "slug_taken"
    EXTERNAL_ID_TAKEN = "external_id_taken"
    UNKNOWN_SKU = "unknown_sku"
    UNKNOWN_CATEGORY = "unknown_category"
    CATEGORY_NOT_FOUND = "category_not_found"
    CATEGORY_DELETED = "category_deleted"
    CATEGORY_CYCLE = "category_cycle"
    ATTRIBUTE_NOT_FOUND = "attribute_not_found"
    ATTRIBUTE_TYPE_CHANGE = "attribute_type_change"
    ATTRIBUTE_NOT_OPTION = "attribute_not_option"
    OPTION_NOT_FOUND = "option_not_found"
    INVALID_PRICING = "invalid_pricing"
    PRICE_LIST_MISSING = "default_price_list_missing"
    # пакетный импорт (ZIP)
    BUNDLE_REJECTED = "bundle_rejected"
    CATEGORY_AMBIGUOUS = "category_ambiguous"
    CURRENCY_MISMATCH = "currency_mismatch"
    PRICE_CONFLICT = "price_conflict"
    RELATION_CONFLICT = "relation_conflict"
    FILE_NOT_FOUND = "file_not_found"
    FILE_AMBIGUOUS = "file_ambiguous"
    FILE_UNSUPPORTED = "file_unsupported"
    FILE_TOO_LARGE = "file_too_large"
    FILE_CONTENT_MISMATCH = "file_content_mismatch"
    FILE_KIND_CONFLICT = "file_kind_conflict"
    IMAGE_LIMIT = "image_limit"
    STOCK_INVALID = "stock_invalid"
    WAREHOUSE_MISSING = "warehouse_missing"
    # предупреждения
    FILE_UNUSED = "file_unused"
    FILE_DUPLICATE = "file_duplicate"
    FILE_IGNORED = "file_ignored"
    DELETED_SKU_REUSED = "deleted_sku_reused"
    DELETED_CATEGORY_SLUG_REUSED = "deleted_category_slug_reused"
    PRODUCT_WITHOUT_PRICE = "product_without_price"
    PRODUCT_WITHOUT_CATEGORY = "product_without_category"


def preview_value(value: Any) -> str | None:
    """Короткое представление значения ячейки для отчёта."""
    if value is None:
        return None
    text = str(value)
    if len(text) > MAX_VALUE_PREVIEW:
        return text[: MAX_VALUE_PREVIEW - 1] + "…"
    return text


@dataclass(frozen=True)
class Issue:
    sheet: str | None
    row: int | None
    column: str | None
    code: str
    message: str
    value: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "row": self.row,
            "column": self.column,
            "code": self.code,
            "message": self.message,
            "value": self.value,
        }


@dataclass
class IssueCollector:
    """Список с ограничением длины и полным счётчиком."""

    limit: int = MAX_REPORTED_ISSUES
    items: list[Issue] = field(default_factory=list)
    total: int = 0

    def add(
        self,
        *,
        sheet: str | None,
        row: int | None,
        column: str | None,
        code: str,
        message: str,
        value: Any = None,
    ) -> None:
        self.total += 1
        if len(self.items) < self.limit:
            self.items.append(
                Issue(
                    sheet=sheet,
                    row=row,
                    column=column,
                    code=code,
                    message=message,
                    value=preview_value(value),
                )
            )

    def extend(self, issues: list[Issue]) -> None:
        for issue in issues:
            self.total += 1
            if len(self.items) < self.limit:
                self.items.append(issue)

    @property
    def truncated(self) -> bool:
        return self.total > len(self.items)

    def __bool__(self) -> bool:
        return self.total > 0
