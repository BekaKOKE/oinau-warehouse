"""Ошибки бизнес-правил каталога.

Каждая — отдельный код, чтобы админка могла показать осмысленное
сообщение, а не «конфликт».
"""

from __future__ import annotations

from app.core.exceptions import ConflictError


class SlugAlreadyExistsError(ConflictError):
    code = "slug_exists"
    message = "Категория с таким slug уже существует"


class AttributeCodeExistsError(ConflictError):
    code = "attribute_code_exists"
    message = "Характеристика с таким кодом уже существует"


class CategoryCycleError(ConflictError):
    code = "category_cycle"
    message = "Категория не может быть вложена сама в себя"


class CategoryHasChildrenError(ConflictError):
    code = "category_has_children"
    message = "Сначала удалите или перенесите подкатегории"


class CategoryHasProductsError(ConflictError):
    code = "category_has_products"
    message = "К категории привязаны товары"


class CategoryNotDeletedError(ConflictError):
    code = "category_not_deleted"
    message = "Категория не удалена, восстанавливать нечего"


class ParentCategoryDeletedError(ConflictError):
    code = "parent_deleted"
    message = "Родительская категория удалена"


class AttributeInUseError(ConflictError):
    code = "attribute_in_use"
    message = "Характеристика используется товарами"


class AttributeOptionInUseError(ConflictError):
    code = "attribute_option_in_use"
    message = "Значение характеристики используется товарами"


class AttributeTypeMismatchError(ConflictError):
    code = "attribute_type_mismatch"
    message = "Варианты значений допустимы только для характеристик типа OPTION"


class DuplicateAttributeLinkError(ConflictError):
    code = "duplicate_attribute_link"
    message = "Характеристика указана в списке дважды"


class ProductSkuExistsError(ConflictError):
    code = "sku_exists"
    message = "Товар с таким артикулом уже существует"


class ProductSlugExistsError(ConflictError):
    code = "product_slug_exists"
    message = "Товар с таким slug уже существует"


class ProductNotDeletedError(ConflictError):
    code = "product_not_deleted"
    message = "Товар не удалён, восстанавливать нечего"


class CategoryDeletedError(ConflictError):
    code = "category_deleted"
    message = "Нельзя привязать товар к удалённой категории"


class AttributeValueTypeMismatchError(ConflictError):
    code = "attribute_value_type_mismatch"
    message = "Значение не соответствует типу характеристики"


class AttributeOptionOwnerError(ConflictError):
    code = "attribute_option_owner_mismatch"
    message = "Вариант значения принадлежит другой характеристике"


class ExternalIdExistsError(ConflictError):
    code = "external_id_exists"
    message = "Объект с таким внешним идентификатором уже существует"


class DuplicateTranslationError(ConflictError):
    code = "duplicate_translation"
    message = "Перевод для этой локали уже существует"


class DuplicateAttributeValueError(ConflictError):
    code = "duplicate_attribute_value"
    message = "Такое значение характеристики уже задано у товара"


class PrimaryCategoryConflictError(ConflictError):
    code = "primary_category_conflict"
    message = "У товара уже назначена основная категория"


class ProductDeletedError(ConflictError):
    """Мутация удалённого товара.

    Живёт в каталоге, а не в модуле цен: правило относится к товару
    и применяется всеми модулями, которые его правят.
    """

    code = "product_deleted"
    message = "Товар удалён: изменение доступно только после восстановления"
