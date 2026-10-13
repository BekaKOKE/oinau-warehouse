"""Схемы Admin API каталога.

Отдельные от публичных: админке нужны служебные поля (`id`, `deleted_at`,
`external_id`), которые витрине показывать нельзя. Смешивать два контракта
в одной схеме — верный способ однажды отдать наружу лишнее.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings
from app.db.types import LEN_SLUG
from app.modules.catalog.enums import AttributeValueType

# Код локали. Набор не ограничен списком SUPPORTED_LOCALES намеренно:
# переводы должны быть заведены ДО того, как язык включат на витрине.
LOCALE_PATTERN = r"^[a-z]{2}(-[A-Z]{2})?$"
SLUG_PATTERN = r"^[a-z0-9-]+$"

SlugField = Annotated[str, Field(min_length=1, max_length=LEN_SLUG, pattern=SLUG_PATTERN)]
CodeField = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")]


def _validate_locales(value: dict[str, Any]) -> dict[str, Any]:
    import re

    for locale in value:
        if not re.fullmatch(LOCALE_PATTERN, locale):
            raise ValueError(f"Некорректный код локали: {locale}")
    return value


# --------------------------------------------------------------- категории


class CategoryTranslationIn(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    seo_title: str | None = Field(default=None, max_length=500)
    seo_description: str | None = None


class CategoryTranslationRead(CategoryTranslationIn):
    model_config = ConfigDict(from_attributes=True)


class CategoryImageRead(BaseModel):
    """Обложка раздела: чем она задана и что показать в админке.

    `uuid` — файл медиатеки, он же уходит обратно при сохранении.
    `url` пуст, пока файл не обработан (PENDING/PROCESSING/FAILED):
    ссылка на такой файл вела бы в 404.
    """

    uuid: UUID
    url: str | None = None


class CategoryCreate(BaseModel):
    slug: SlugField
    parent_id: int | None = None
    sort_order: int = 0
    is_active: bool = True
    external_id: str | None = Field(default=None, max_length=64)
    # Файл медиатеки. Своего хранилища у категорий нет.
    image: UUID | None = None
    # Ключ — код локали. Такая форма позволяет добавить kk, не меняя схему.
    translations: dict[str, CategoryTranslationIn]

    @field_validator("translations")
    @classmethod
    def _check_translations(
        cls, value: dict[str, CategoryTranslationIn]
    ) -> dict[str, CategoryTranslationIn]:
        _validate_locales(value)
        if settings.DEFAULT_LOCALE not in value:
            raise ValueError(f"Обязателен перевод для локали {settings.DEFAULT_LOCALE}")
        return value


class CategoryUpdate(BaseModel):
    """Частичное обновление.

    Незаданные поля не трогаются — отличие «не передано» от «передано
    null» разбирается через `model_fields_set`.
    """

    slug: SlugField | None = None
    parent_id: int | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    external_id: str | None = Field(default=None, max_length=64)
    # Переданный null снимает обложку, отсутствие поля её не трогает.
    image: UUID | None = None
    translations: dict[str, CategoryTranslationIn] | None = None

    @field_validator("translations")
    @classmethod
    def _check_translations(
        cls, value: dict[str, CategoryTranslationIn] | None
    ) -> dict[str, CategoryTranslationIn] | None:
        if value is not None:
            _validate_locales(value)
        return value


class CategoryRead(BaseModel):
    id: int
    slug: str
    parent_id: int | None
    path: str
    depth: int
    sort_order: int
    is_active: bool
    external_id: str | None
    name: str
    image: CategoryImageRead | None = None
    translations: dict[str, CategoryTranslationRead]
    products_count: int = 0
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class CategoryTreeNode(BaseModel):
    id: int
    slug: str
    name: str
    # Родитель и время удаления: без них дерево с include_deleted=true
    # не отличает удалённые разделы от живых, и восстановить их из
    # дерева админки нельзя.
    parent_id: int | None = None
    depth: int
    sort_order: int
    is_active: bool
    products_count: int = 0
    deleted_at: datetime | None = None
    children: list[CategoryTreeNode] = Field(default_factory=list)


# ------------------------------------------------------------ характеристики


class AttributeOptionCreate(BaseModel):
    slug: SlugField
    sort_order: int = 0
    values: dict[str, str]

    @field_validator("values")
    @classmethod
    def _check_values(cls, value: dict[str, str]) -> dict[str, str]:
        _validate_locales(value)
        if settings.DEFAULT_LOCALE not in value:
            raise ValueError(f"Обязательно значение для локали {settings.DEFAULT_LOCALE}")
        return value


class AttributeOptionUpdate(BaseModel):
    slug: SlugField | None = None
    sort_order: int | None = None
    values: dict[str, str] | None = None

    @field_validator("values")
    @classmethod
    def _check_values(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None:
            _validate_locales(value)
        return value


class AttributeOptionRead(BaseModel):
    id: int
    slug: str
    sort_order: int
    values: dict[str, str]


class AttributeCreate(BaseModel):
    code: CodeField
    value_type: AttributeValueType
    unit: str | None = Field(default=None, max_length=16)
    is_filterable: bool = True
    is_visible: bool = True
    is_active: bool = True
    sort_order: int = 0
    names: dict[str, str]
    options: list[AttributeOptionCreate] = Field(default_factory=list)

    @field_validator("names")
    @classmethod
    def _check_names(cls, value: dict[str, str]) -> dict[str, str]:
        _validate_locales(value)
        if settings.DEFAULT_LOCALE not in value:
            raise ValueError(f"Обязательно название для локали {settings.DEFAULT_LOCALE}")
        return value

    @model_validator(mode="after")
    def _check_options(self) -> AttributeCreate:
        if self.options and self.value_type is not AttributeValueType.OPTION:
            raise ValueError("Варианты значений допустимы только для типа OPTION")
        return self


class AttributeUpdate(BaseModel):
    """Тип характеристики менять нельзя.

    Смена `value_type` осиротила бы уже заполненные значения: число
    в `value_numeric` не превратится в вариант справочника само собой.
    Правильный путь — завести новую характеристику и перенести данные.
    """

    unit: str | None = Field(default=None, max_length=16)
    is_filterable: bool | None = None
    is_visible: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None
    names: dict[str, str] | None = None

    @field_validator("names")
    @classmethod
    def _check_names(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None:
            _validate_locales(value)
        return value


class AttributeCategoryRef(BaseModel):
    """Категория, которой назначена характеристика (только неудалённые)."""

    id: int
    slug: str
    name: str


class AttributeRead(BaseModel):
    id: int
    code: str
    value_type: AttributeValueType
    unit: str | None
    is_filterable: bool
    is_visible: bool
    is_active: bool
    sort_order: int
    name: str
    names: dict[str, str]
    options: list[AttributeOptionRead] = Field(default_factory=list)
    # Число значений у товаров: пока оно больше нуля, удалить нельзя.
    usage_count: int = 0
    # Категории, которым назначена характеристика. При удалении
    # характеристики эти привязки исчезают вместе с ней (ON DELETE CASCADE),
    # поэтому админке нужно показать их заранее.
    categories: list[AttributeCategoryRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------- связь категория ↔ атрибут


class CategoryAttributeItem(BaseModel):
    attribute_id: int
    sort_order: int = 0
    is_required: bool = False


class CategoryAttributeRead(BaseModel):
    attribute_id: int
    code: str
    name: str
    value_type: AttributeValueType
    unit: str | None
    sort_order: int
    is_required: bool


class CategoryAttributesUpdate(BaseModel):
    """Полная замена набора характеристик категории.

    PUT, а не постепенное добавление: админка редактирует список целиком,
    и замена набора одной операцией избавляет от рассинхронизации, когда
    часть запросов прошла, а часть нет.
    """

    items: list[CategoryAttributeItem]

    @model_validator(mode="after")
    def _check_duplicates(self) -> CategoryAttributesUpdate:
        ids = [item.attribute_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Характеристика указана в списке несколько раз")
        return self


CategoryTreeNode.model_rebuild()
