"""Соответствие ограничений целостности каталога доменным ошибкам.

Имена взяты из фактической схемы (миграция 02b0358003e8): они заданы
явно в моделях и проверены запросом к pg_indexes. При переименовании
индекса в миграции нужно обновить и эту таблицу — иначе конфликт
перестанет распознаваться и вернётся 500.
"""

from __future__ import annotations

from app.core.exceptions import AppError
from app.modules.catalog.exceptions import (
    AttributeCodeExistsError,
    DuplicateAttributeValueError,
    DuplicateTranslationError,
    ExternalIdExistsError,
    PrimaryCategoryConflictError,
    ProductSkuExistsError,
    ProductSlugExistsError,
    SlugAlreadyExistsError,
)
from app.modules.pricing.exceptions import OverlappingTiersError

CATALOG_UNIQUE_ERRORS: dict[str, type[AppError]] = {
    # товары
    "uq_products_sku": ProductSkuExistsError,
    "uq_products_slug": ProductSlugExistsError,
    "uq_products_external_id": ExternalIdExistsError,
    "uq_product_translations_product_id_locale": DuplicateTranslationError,
    "uq_product_categories_primary": PrimaryCategoryConflictError,
    "uq_product_attribute_values_key": DuplicateAttributeValueError,
    # категории
    "uq_categories_slug": SlugAlreadyExistsError,
    "uq_categories_external_id": ExternalIdExistsError,
    "uq_category_translations_category_id_locale": DuplicateTranslationError,
    # характеристики
    "uq_attributes_code": AttributeCodeExistsError,
    "uq_attribute_options_attribute_id_slug": SlugAlreadyExistsError,
    # цены: EXCLUDE-ограничение на пересечение диапазонов количества.
    # Это не уникальный индекс, но приходит тем же IntegrityError
    # с именем constraint, поэтому обрабатывается общим механизмом.
    "no_overlapping_tiers": OverlappingTiersError,
}
