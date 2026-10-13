"""Бизнес-правила Admin API товаров."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.integrity import guard_unique
from app.core.pagination import Page, PageParams
from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.catalog.enums import AttributeValueType
from app.modules.catalog.exceptions import (
    AttributeOptionOwnerError,
    AttributeValueTypeMismatchError,
    CategoryDeletedError,
    ExternalIdExistsError,
    ProductNotDeletedError,
    ProductSkuExistsError,
    ProductSlugExistsError,
)
from app.modules.catalog.integrity import CATALOG_UNIQUE_ERRORS
from app.modules.catalog.models import (
    Attribute,
    AttributeOption,
    Category,
    Product,
    ProductAttributeValue,
    ProductCategory,
    ProductTranslation,
)
from app.modules.catalog.mutability import ensure_mutable
from app.modules.catalog.repository_admin_products import (
    AdminProductRepository,
    ProductAdminFilters,
    ProductAdminSort,
)
from app.modules.catalog.schemas_admin_products import (
    ProductAttributeItem,
    ProductAttributeRead,
    ProductAttributesUpdate,
    ProductCategoriesUpdate,
    ProductCategoryItem,
    ProductCategoryRead,
    ProductCreate,
    ProductListItem,
    ProductListRow,
    ProductRead,
    ProductTranslationIn,
    ProductTranslationRead,
    ProductUpdate,
)
from app.modules.catalog.visibility import is_publicly_visible
from app.modules.inventory.availability import resolve_availability
from app.modules.media.urls import primary_url, variant_urls
from app.modules.users.models import User


class ProductAuditAction:
    CREATED = "catalog.product_created"
    UPDATED = "catalog.product_updated"
    DELETED = "catalog.product_deleted"
    RESTORED = "catalog.product_restored"
    CATEGORIES_REPLACED = "catalog.product_categories_replaced"
    ATTRIBUTES_REPLACED = "catalog.product_attributes_replaced"


PRODUCT_ENTITY = "product"

SCALAR_FIELDS = ("sku", "slug", "status", "is_active", "is_featured", "unit", "brand")


# ------------------------------------------------------------------------
# Общие правила записи товара.
#
# Вынесены из сервиса на уровень модуля, потому что их применяют два
# канала изменения каталога: Admin API и Excel-импорт. Копия правил
# в импорте рано или поздно разошлась бы с админкой.
# ------------------------------------------------------------------------
def build_category_links(
    product_id: int, items: list[ProductCategoryItem]
) -> list[ProductCategory]:
    """Связи товара с категориями по правилу основной категории.

    Основная категория задаёт канонический URL и хлебные крошки. Если её
    не указали явно, ею становится первая — товар без канонической
    категории поисковые системы увидят как дубль.
    """
    links = [
        ProductCategory(
            product_id=product_id,
            category_id=item.category_id,
            is_primary=item.is_primary,
            sort_order=item.sort_order,
        )
        for item in items
    ]
    if links and not any(link.is_primary for link in links):
        links[0].is_primary = True
    return links


def validate_attribute_value(
    attribute: Attribute,
    item: ProductAttributeItem,
    options: Mapping[int, AttributeOption],
) -> None:
    """Значение обязано соответствовать типу характеристики.

    Проверка дублирует CHECK в базе только по количеству заполненных
    колонок; соответствие типу база проверить не может — она не знает,
    какой `value_type` объявлен у характеристики.

    `is_active=false` у характеристики не мешает сохранить значение:
    флаг скрывает её из фильтров витрины, но уже заведённые данные
    товаров остаются валидными.
    """
    value_type = AttributeValueType(attribute.value_type)
    provided = {
        AttributeValueType.STRING: item.value_string is not None,
        AttributeValueType.NUMBER: item.value_numeric is not None,
        AttributeValueType.BOOLEAN: item.value_bool is not None,
        AttributeValueType.OPTION: item.option_id is not None,
    }

    if not provided[value_type]:
        raise AttributeValueTypeMismatchError(
            details={
                "attribute_id": attribute.id,
                "expected": value_type.value,
            }
        )

    if value_type is AttributeValueType.OPTION:
        option = options.get(item.option_id or 0)
        if option is None:
            raise NotFoundError(f"Вариант значения {item.option_id} не найден")
        if option.attribute_id != attribute.id:
            raise AttributeOptionOwnerError(
                details={"attribute_id": attribute.id, "option_id": option.id}
            )


def upsert_product_translations(
    session: AsyncSession, product: Product, translations: Mapping[str, ProductTranslationIn]
) -> None:
    """Обновляет переданные локали, не трогая остальные.

    Добавление казахской версии не должно стирать русскую. Коллекция
    `product.translations` должна быть загружена заранее.
    """
    existing = {item.locale: item for item in product.translations}
    for locale, payload in translations.items():
        data = payload.model_dump()
        if locale in existing:
            for field, value in data.items():
                setattr(existing[locale], field, value)
        else:
            session.add(ProductTranslation(product_id=product.id, locale=locale, **data))


class AdminProductService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = AdminProductRepository(session)
        self.audit = AuditService(session)

    # -------------------------------------------------------------- чтение
    async def list_products(
        self, *, filters: ProductAdminFilters, sort: ProductAdminSort, params: PageParams
    ) -> Page[ProductListRow]:
        rows, total = await self.repository.list_products(filters=filters, sort=sort, params=params)
        extras, price_list = await self.repository.list_extras([item.id for item in rows])
        items: list[ProductListRow] = []
        for product in rows:
            extra = extras[product.id]
            media = extra.main_image
            items.append(
                ProductListRow(
                    **self._to_list_item(product).model_dump(),
                    # Миниатюра, если воркер её построил; иначе основной вариант.
                    main_image_url=variant_urls(media).get("thumb") or primary_url(media),
                    images_count=extra.images_count,
                    pricing_type=product.pricing_type,
                    currency=price_list.currency if price_list else None,
                    min_price=extra.min_price,
                    max_price=extra.max_price,
                    public_availability=resolve_availability(
                        pricing_type=product.pricing_type,
                        stock_display_override=product.stock_display_override,
                        available_quantity=extra.available_quantity,
                    ),
                    stock_display_override=product.stock_display_override,
                )
            )
        return Page.create(items, total, params)

    async def get_product(self, product_id: int) -> ProductRead:
        return self._to_read(await self._require(product_id))

    # -------------------------------------------------------------- запись
    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def create_product(self, payload: ProductCreate, actor: User) -> ProductRead:
        await self._check_sku_unique(payload.sku)
        await self._check_slug_unique(payload.slug)
        await self._check_external_id_unique(payload.external_id)

        product = Product(
            sku=payload.sku,
            slug=payload.slug,
            status=payload.status.value,
            is_active=payload.is_active,
            is_featured=payload.is_featured,
            unit=payload.unit,
            min_order_qty=payload.min_order_qty,
            brand=payload.brand,
            specs=dict(payload.specs),
            external_id=payload.external_id,
        )
        self.session.add(product)
        await self.session.flush()

        self._add_translations(product.id, payload.translations)
        if payload.categories:
            await self._apply_categories(product.id, payload.categories)
        if payload.attributes:
            await self._apply_attributes(product.id, payload.attributes)
        await self.session.flush()

        self.audit.record(
            action=ProductAuditAction.CREATED,
            entity_type=PRODUCT_ENTITY,
            entity_id=product.id,
            user_id=actor.id,
            changes={"sku": {"old": None, "new": product.sku}},
        )
        await self.commit()
        return await self.get_product(product.id)

    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def update_product(
        self, product_id: int, payload: ProductUpdate, actor: User
    ) -> ProductRead:
        product = await self._require_mutable(product_id)
        fields = payload.model_dump(exclude_unset=True)
        changes: dict[str, Any] = {}

        if "sku" in fields and fields["sku"] != product.sku:
            await self._check_sku_unique(fields["sku"], exclude_id=product.id)
        if "slug" in fields and fields["slug"] != product.slug:
            await self._check_slug_unique(fields["slug"], exclude_id=product.id)
        if "external_id" in fields and fields["external_id"] != product.external_id:
            await self._check_external_id_unique(fields["external_id"], exclude_id=product.id)

        for field in SCALAR_FIELDS:
            if field not in fields:
                continue
            value = fields[field]
            if field == "status" and value is not None:
                value = payload.status.value if payload.status else value
            if value != getattr(product, field):
                changes[field] = {"old": getattr(product, field), "new": value}
                setattr(product, field, value)

        if "min_order_qty" in fields and fields["min_order_qty"] != product.min_order_qty:
            changes["min_order_qty"] = {
                "old": str(product.min_order_qty),
                "new": str(fields["min_order_qty"]),
            }
            product.min_order_qty = fields["min_order_qty"]

        if "external_id" in fields and fields["external_id"] != product.external_id:
            changes["external_id"] = {"old": product.external_id, "new": fields["external_id"]}
            product.external_id = fields["external_id"]

        if payload.specs is not None:
            changes["specs"] = {"old": product.specs, "new": payload.specs}
            product.specs = dict(payload.specs)

        if payload.translations is not None:
            self._upsert_translations(product, payload.translations)
            changes["translations"] = {"old": None, "new": sorted(payload.translations)}

        await self.session.flush()
        if changes:
            self.audit.record(
                action=ProductAuditAction.UPDATED,
                entity_type=PRODUCT_ENTITY,
                entity_id=product.id,
                user_id=actor.id,
                changes=changes,
            )
        await self.commit()
        return await self.get_product(product.id)

    async def delete_product(self, product_id: int, actor: User) -> None:
        """Мягкое удаление.

        Физическое удаление недопустимо: позиции заявок ссылаются на товар
        через `ON DELETE SET NULL`, и DELETE молча обнулил бы связь
        в исторических документах. Снапшот в `request_items` при этом
        уцелеет, но восстановить, о каком товаре шла речь, будет нельзя.
        """
        product = await self._require(product_id)
        if product.deleted_at is not None:
            raise NotFoundError("Товар уже удалён")

        product.deleted_at = datetime.now(UTC)
        product.is_active = False
        self.audit.record(
            action=ProductAuditAction.DELETED,
            entity_type=PRODUCT_ENTITY,
            entity_id=product.id,
            user_id=actor.id,
            changes={"sku": product.sku, "deleted_at": product.deleted_at.isoformat()},
        )
        await self.commit()

    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def restore_product(self, product_id: int, actor: User) -> ProductRead:
        """Единственная мутация, разрешённая для удалённого товара.

        Поэтому здесь `_require()`, а не `_require_mutable()`.
        """
        product = await self._require(product_id)
        if product.deleted_at is None:
            raise ProductNotDeletedError

        # Пока товар был удалён, артикул и slug мог занять другой товар.
        await self._check_sku_unique(product.sku, exclude_id=product.id)
        await self._check_slug_unique(product.slug, exclude_id=product.id)

        product.deleted_at = None
        self.audit.record(
            action=ProductAuditAction.RESTORED,
            entity_type=PRODUCT_ENTITY,
            entity_id=product.id,
            user_id=actor.id,
        )
        await self.commit()
        return await self.get_product(product.id)

    # ---------------------------------------------------------- категории
    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def set_categories(
        self, product_id: int, payload: ProductCategoriesUpdate, actor: User
    ) -> ProductRead:
        product = await self._require_mutable(product_id)
        await self._apply_categories(product.id, payload.items)

        self.audit.record(
            action=ProductAuditAction.CATEGORIES_REPLACED,
            entity_type=PRODUCT_ENTITY,
            entity_id=product.id,
            user_id=actor.id,
            changes={"category_ids": [item.category_id for item in payload.items]},
        )
        await self.commit()
        return await self.get_product(product.id)

    async def _apply_categories(self, product_id: int, items: list[ProductCategoryItem]) -> None:
        categories = await self.repository.get_categories_by_ids(
            [item.category_id for item in items]
        )
        for item in items:
            category = categories.get(item.category_id)
            if category is None:
                raise NotFoundError(f"Категория {item.category_id} не найдена")
            if category.deleted_at is not None:
                raise CategoryDeletedError(details={"category_id": category.id})
            # Неактивная категория разрешена намеренно: раздел может быть
            # временно скрыт с витрины, но принадлежность товара к нему
            # от этого не исчезает. Публичный API такие связи и так
            # отфильтровывает.

        await self.repository.replace_categories(
            product_id, build_category_links(product_id, items)
        )

    # ------------------------------------------------------- характеристики
    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def set_attributes(
        self, product_id: int, payload: ProductAttributesUpdate, actor: User
    ) -> ProductRead:
        product = await self._require_mutable(product_id)
        await self._apply_attributes(product.id, payload.items)

        self.audit.record(
            action=ProductAuditAction.ATTRIBUTES_REPLACED,
            entity_type=PRODUCT_ENTITY,
            entity_id=product.id,
            user_id=actor.id,
            changes={"attribute_ids": sorted({item.attribute_id for item in payload.items})},
        )
        await self.commit()
        return await self.get_product(product.id)

    async def _apply_attributes(self, product_id: int, items: list[ProductAttributeItem]) -> None:
        attributes = await self.repository.get_attributes_by_ids(
            [item.attribute_id for item in items]
        )
        options = await self.repository.get_options_by_ids(
            [item.option_id for item in items if item.option_id is not None]
        )

        values: list[ProductAttributeValue] = []
        for item in items:
            attribute = attributes.get(item.attribute_id)
            if attribute is None:
                raise NotFoundError(f"Характеристика {item.attribute_id} не найдена")

            validate_attribute_value(attribute, item, options)
            values.append(
                ProductAttributeValue(
                    product_id=product_id,
                    attribute_id=item.attribute_id,
                    value_string=item.value_string,
                    value_numeric=item.value_numeric,
                    value_bool=item.value_bool,
                    option_id=item.option_id,
                )
            )

        await self.repository.replace_attribute_values(product_id, values)

    # ---------------------------------------------------------- внутреннее
    async def _require(self, product_id: int) -> Product:
        """Товар для чтения — включая удалённый.

        Админка должна видеть удалённые товары: без этого нельзя ни
        разобрать историю, ни нажать «восстановить».
        """
        product = await self.repository.get_by_id(product_id)
        if product is None:
            raise NotFoundError("Товар не найден")
        return product

    async def _require_mutable(self, product_id: int) -> Product:
        """Товар для изменения. Удалённый отвергается.

        Единственное исключение — восстановление: оно работает
        с `_require()` напрямую.
        """
        return ensure_mutable(await self._require(product_id))

    async def _check_sku_unique(self, sku: str, *, exclude_id: int | None = None) -> None:
        existing = await self.repository.find_by_sku(sku)
        if existing is not None and existing.id != exclude_id:
            raise ProductSkuExistsError

    async def _check_slug_unique(self, slug: str, *, exclude_id: int | None = None) -> None:
        existing = await self.repository.find_by_slug(slug)
        if existing is not None and existing.id != exclude_id:
            raise ProductSlugExistsError

    async def _check_external_id_unique(
        self, external_id: str | None, *, exclude_id: int | None = None
    ) -> None:
        """Пустой external_id уникальности не требует.

        Индекс частичный (`WHERE external_id IS NOT NULL`): до интеграции
        с 1С поле пусто у всех товаров.
        """
        if external_id is None:
            return
        existing = await self.repository.find_by_external_id(external_id)
        if existing is not None and existing.id != exclude_id:
            raise ExternalIdExistsError

    def _add_translations(
        self, product_id: int, translations: dict[str, ProductTranslationIn]
    ) -> None:
        for locale, payload in translations.items():
            self.session.add(
                ProductTranslation(product_id=product_id, locale=locale, **payload.model_dump())
            )

    def _upsert_translations(
        self, product: Product, translations: dict[str, ProductTranslationIn]
    ) -> None:
        upsert_product_translations(self.session, product, translations)

    # -------------------------------------------------------------- сборка
    def _category_name(self, category: Category) -> str:
        by_locale = {item.locale: item for item in category.translations}
        translation = by_locale.get(settings.DEFAULT_LOCALE) or next(iter(by_locale.values()), None)
        return translation.name if translation else category.slug

    def _product_name(self, product: Product) -> str:
        by_locale = {item.locale: item for item in product.translations}
        translation = by_locale.get(settings.DEFAULT_LOCALE) or next(iter(by_locale.values()), None)
        return translation.name if translation else product.sku

    def _category_read(self, link: ProductCategory) -> ProductCategoryRead:
        return ProductCategoryRead(
            category_id=link.category_id,
            slug=link.category.slug,
            name=self._category_name(link.category),
            is_primary=link.is_primary,
            sort_order=link.sort_order,
            is_active=link.category.is_active,
        )

    def _to_list_item(self, product: Product) -> ProductListItem:
        links = sorted(product.categories, key=lambda item: (not item.is_primary, item.sort_order))
        primary = next((link for link in links if link.is_primary), None)
        return ProductListItem(
            id=product.id,
            sku=product.sku,
            slug=product.slug,
            name=self._product_name(product),
            status=product.status,
            is_active=product.is_active,
            is_featured=product.is_featured,
            is_publicly_visible=is_publicly_visible(product),
            unit=product.unit,
            brand=product.brand,
            external_id=product.external_id,
            primary_category=self._category_read(primary) if primary else None,
            categories_count=len(product.categories),
            created_at=product.created_at,
            updated_at=product.updated_at,
            deleted_at=product.deleted_at,
        )

    def _to_read(self, product: Product) -> ProductRead:
        base = self._to_list_item(product)
        links = sorted(product.categories, key=lambda item: (not item.is_primary, item.sort_order))

        attributes: list[ProductAttributeRead] = []
        for value in sorted(product.attribute_values, key=lambda item: item.attribute_id):
            attribute = value.attribute
            name_i18n = attribute.name_i18n or {}
            option = value.option
            attributes.append(
                ProductAttributeRead(
                    attribute_id=attribute.id,
                    code=attribute.code,
                    name=str(
                        name_i18n.get(settings.DEFAULT_LOCALE)
                        or next(iter(name_i18n.values()), attribute.code)
                    ),
                    value_type=attribute.value_type,
                    unit=attribute.unit,
                    value_string=value.value_string,
                    value_numeric=value.value_numeric,
                    value_bool=value.value_bool,
                    option_id=value.option_id,
                    option_slug=option.slug if option else None,
                    option_value=(
                        str(
                            (option.value_i18n or {}).get(settings.DEFAULT_LOCALE)
                            or next(iter((option.value_i18n or {}).values()), option.slug)
                        )
                        if option
                        else None
                    ),
                )
            )

        return ProductRead(
            **base.model_dump(),
            min_order_qty=product.min_order_qty,
            specs={str(key): str(item) for key, item in (product.specs or {}).items()},
            translations={
                item.locale: ProductTranslationRead(
                    name=item.name,
                    short_description=item.short_description,
                    description=item.description,
                    seo_title=item.seo_title,
                    seo_description=item.seo_description,
                )
                for item in product.translations
            },
            categories=[self._category_read(link) for link in links],
            attributes=attributes,
            pricing_type=product.pricing_type,
            stock_display_override=product.stock_display_override,
            sync_source=product.sync_source,
            synced_at=product.synced_at,
        )


__all__ = [
    "PRODUCT_ENTITY",
    "AdminProductService",
    "Decimal",
    "ProductAdminFilters",
    "ProductAdminSort",
    "ProductAuditAction",
    "build_category_links",
    "upsert_product_translations",
    "validate_attribute_value",
]
