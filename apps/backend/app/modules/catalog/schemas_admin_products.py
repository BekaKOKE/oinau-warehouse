"""Схемы Admin API товаров.

Отдельные от публичных: админке нужны `id`, `status`, `deleted_at`,
`external_id` и признак фактической видимости на витрине — всё то, что
публичный контракт намеренно скрывает.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings
from app.db.types import LEN_SLUG
from app.modules.catalog.enums import AttributeValueType, ProductStatus
from app.modules.catalog.schemas_admin import LOCALE_PATTERN, SLUG_PATTERN
from app.modules.inventory.enums import PublicAvailability, StockDisplayOverride
from app.modules.pricing.enums import PricingType

# Артикул приходит из 1С и с бумажных прайсов: регистр, точки и слеши
# встречаются постоянно. Ограничиваем набор символов, но не навязываем
# собственный формат — иначе импорт из учётной системы начнёт падать.
SKU_PATTERN = r"^[A-Za-z0-9._/\-]+$"

SkuField = Annotated[str, Field(min_length=1, max_length=64, pattern=SKU_PATTERN)]
SlugField = Annotated[str, Field(min_length=1, max_length=LEN_SLUG, pattern=SLUG_PATTERN)]

MAX_SPEC_ENTRIES = 50


def _validate_locales(value: dict[str, Any]) -> dict[str, Any]:
    import re

    for locale in value:
        if not re.fullmatch(LOCALE_PATTERN, locale):
            raise ValueError(f"Некорректный код локали: {locale}")
    return value


def _validate_specs(value: dict[str, str]) -> dict[str, str]:
    if len(value) > MAX_SPEC_ENTRIES:
        raise ValueError(f"Не больше {MAX_SPEC_ENTRIES} описательных характеристик")
    for key, item in value.items():
        if not key.strip():
            raise ValueError("Пустое название описательной характеристики")
        if len(key) > 120 or len(str(item)) > 500:
            raise ValueError("Слишком длинная описательная характеристика")
    return value


# ------------------------------------------------------------- переводы


class ProductTranslationIn(BaseModel):
    """Локализуемые тексты.

    Название и описания лежат в `product_translations`, а не в `products`:
    по ним строится полнотекстовый индекс на конкретный язык.
    """

    name: str = Field(min_length=1, max_length=500)
    short_description: str | None = None
    description: str | None = None
    seo_title: str | None = Field(default=None, max_length=500)
    seo_description: str | None = None


class ProductTranslationRead(ProductTranslationIn):
    pass


# ---------------------------------------------------------- связи товара


class ProductCategoryItem(BaseModel):
    category_id: int = Field(ge=1)
    is_primary: bool = False
    sort_order: int = 0


class ProductCategoriesUpdate(BaseModel):
    """Полная замена набора категорий товара."""

    items: list[ProductCategoryItem]

    @model_validator(mode="after")
    def _check(self) -> ProductCategoriesUpdate:
        ids = [item.category_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Категория указана в списке несколько раз")
        if sum(1 for item in self.items if item.is_primary) > 1:
            raise ValueError("Основная категория может быть только одна")
        return self


class ProductCategoryRead(BaseModel):
    category_id: int
    slug: str
    name: str
    is_primary: bool
    sort_order: int
    is_active: bool


class ProductAttributeItem(BaseModel):
    """Значение характеристики.

    Ровно одно поле значения должно быть заполнено — так же, как этого
    требует CHECK-ограничение `num_nonnulls(...) = 1` в базе.
    """

    attribute_id: int = Field(ge=1)
    value_string: str | None = Field(default=None, max_length=255)
    value_numeric: Decimal | None = None
    value_bool: bool | None = None
    option_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _exactly_one_value(self) -> ProductAttributeItem:
        provided = [
            field
            for field in ("value_string", "value_numeric", "value_bool", "option_id")
            if getattr(self, field) is not None
        ]
        if len(provided) != 1:
            raise ValueError(
                "Должно быть заполнено ровно одно поле значения, передано: "
                + (", ".join(provided) or "ни одного")
            )
        return self


class ProductAttributesUpdate(BaseModel):
    """Полная замена характеристик товара.

    Дубликаты запрещены по паре (характеристика, вариант). Несколько
    значений одной характеристики допустимы только для типа OPTION —
    ровно это разрешает уникальный индекс
    `uq_product_attribute_values_key` (товар доступен в трёх цветах).
    """

    items: list[ProductAttributeItem]

    @model_validator(mode="after")
    def _check_duplicates(self) -> ProductAttributesUpdate:
        seen: set[tuple[int, int]] = set()
        for item in self.items:
            key = (item.attribute_id, item.option_id or 0)
            if key in seen:
                raise ValueError(
                    f"Характеристика {item.attribute_id} указана с тем же значением дважды"
                )
            seen.add(key)
        return self


class ProductAttributeRead(BaseModel):
    attribute_id: int
    code: str
    name: str
    value_type: AttributeValueType
    unit: str | None
    value_string: str | None = None
    value_numeric: Decimal | None = None
    value_bool: bool | None = None
    option_id: int | None = None
    option_slug: str | None = None
    option_value: str | None = None


# ------------------------------------------------------------- товары


class ProductCreate(BaseModel):
    sku: SkuField
    slug: SlugField
    status: ProductStatus = ProductStatus.DRAFT
    is_active: bool = True
    is_featured: bool = False
    unit: str = Field(default="pcs", min_length=1, max_length=16)
    min_order_qty: Decimal = Field(default=Decimal("1"), gt=0)
    brand: str | None = Field(default=None, max_length=255)
    specs: dict[str, str] = Field(default_factory=dict)
    external_id: str | None = Field(default=None, max_length=64)
    translations: dict[str, ProductTranslationIn]

    # Связи можно задать сразу при создании — иначе заведение товара
    # требовало бы трёх запросов подряд и оставляло бы окно, в котором
    # товар существует без категории.
    categories: list[ProductCategoryItem] = Field(default_factory=list)
    attributes: list[ProductAttributeItem] = Field(default_factory=list)

    @field_validator("translations")
    @classmethod
    def _check_translations(
        cls, value: dict[str, ProductTranslationIn]
    ) -> dict[str, ProductTranslationIn]:
        _validate_locales(value)
        if settings.DEFAULT_LOCALE not in value:
            raise ValueError(f"Обязателен перевод для локали {settings.DEFAULT_LOCALE}")
        return value

    @field_validator("specs")
    @classmethod
    def _check_specs(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_specs(value)

    @model_validator(mode="after")
    def _check_links(self) -> ProductCreate:
        ProductCategoriesUpdate(items=self.categories)
        ProductAttributesUpdate(items=self.attributes)
        return self


class ProductUpdate(BaseModel):
    """Частичное обновление: незаданные поля не трогаются."""

    sku: SkuField | None = None
    slug: SlugField | None = None
    status: ProductStatus | None = None
    is_active: bool | None = None
    is_featured: bool | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=16)
    min_order_qty: Decimal | None = Field(default=None, gt=0)
    brand: str | None = Field(default=None, max_length=255)
    specs: dict[str, str] | None = None
    external_id: str | None = Field(default=None, max_length=64)
    translations: dict[str, ProductTranslationIn] | None = None

    @field_validator("translations")
    @classmethod
    def _check_translations(
        cls, value: dict[str, ProductTranslationIn] | None
    ) -> dict[str, ProductTranslationIn] | None:
        if value is not None:
            _validate_locales(value)
        return value

    @field_validator("specs")
    @classmethod
    def _check_specs(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _validate_specs(value) if value is not None else None


class ProductListItem(BaseModel):
    id: int
    sku: str
    slug: str
    name: str
    status: ProductStatus
    is_active: bool
    is_featured: bool
    # Вычисляется по единому правилу из app/modules/catalog/visibility.py.
    # Отдельное поле нужно, чтобы админка не пересобирала это условие сама.
    is_publicly_visible: bool
    unit: str
    brand: str | None
    external_id: str | None
    primary_category: ProductCategoryRead | None = None
    categories_count: int = 0
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class ProductListRow(ProductListItem):
    """Строка списка товаров админки.

    К полям товара добавлено то, без чего таблицу каталога не прочитать:
    обложка, цена и наличие. Всё считается пакетно на страницу —
    отдельный запрос за ценой и фото на каждую строку дал бы N+1.
    Карточка товара (`ProductRead`) по-прежнему берёт цену, изображения
    и остатки своими эндпоинтами.
    """

    # Уменьшенная копия главного изображения; null — фото нет или файл
    # ещё не готов (витрина его тоже не покажет).
    main_image_url: str | None = None
    images_count: int = 0
    pricing_type: PricingType
    # Цены публичного прайс-листа — как на витрине. null — ступеней нет.
    currency: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    # Тот же resolver, что у витрины и GET /products/{id}/availability.
    public_availability: PublicAvailability
    stock_display_override: StockDisplayOverride | None = None


class ProductRead(ProductListItem):
    min_order_qty: Decimal
    specs: dict[str, str] = Field(default_factory=dict)
    translations: dict[str, ProductTranslationRead] = Field(default_factory=dict)
    categories: list[ProductCategoryRead] = Field(default_factory=list)
    attributes: list[ProductAttributeRead] = Field(default_factory=list)
    # Только для чтения: цена и переопределение наличия относятся
    # к соседним доменам и правятся своими эндпоинтами.
    pricing_type: str
    stock_display_override: str | None = None
    sync_source: str
    synced_at: datetime | None = None
