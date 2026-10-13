"""Бизнес-правила Admin API каталога.

Здесь живут пересчёт материализованного пути, защита от циклов, проверки
безопасности удаления и запись в журнал аудита. Роутер только принимает
запрос, сервис принимает решения.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.integrity import guard_unique
from app.core.pagination import Page, PageParams
from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.catalog.exceptions import (
    AttributeCodeExistsError,
    AttributeInUseError,
    AttributeOptionInUseError,
    AttributeTypeMismatchError,
    CategoryCycleError,
    CategoryHasChildrenError,
    CategoryHasProductsError,
    CategoryNotDeletedError,
    ParentCategoryDeletedError,
    SlugAlreadyExistsError,
)
from app.modules.catalog.integrity import CATALOG_UNIQUE_ERRORS
from app.modules.catalog.models import (
    Attribute,
    AttributeOption,
    Category,
    CategoryAttribute,
    CategoryTranslation,
)
from app.modules.catalog.repository_admin import (
    AdminAttributeRepository,
    AdminCategoryRepository,
)
from app.modules.catalog.schemas_admin import (
    AttributeCategoryRef,
    AttributeCreate,
    AttributeOptionCreate,
    AttributeOptionRead,
    AttributeOptionUpdate,
    AttributeRead,
    AttributeUpdate,
    CategoryAttributeRead,
    CategoryAttributesUpdate,
    CategoryCreate,
    CategoryImageRead,
    CategoryRead,
    CategoryTranslationRead,
    CategoryTreeNode,
    CategoryUpdate,
)
from app.modules.media.exceptions import MediaNotFoundError
from app.modules.media.urls import primary_url, variant_urls
from app.modules.users.models import User


class AuditEntity:
    CATEGORY = "category"
    ATTRIBUTE = "attribute"
    ATTRIBUTE_OPTION = "attribute_option"
    CATEGORY_ATTRIBUTES = "category_attributes"


class CatalogAction:
    CATEGORY_CREATED = "catalog.category_created"
    CATEGORY_UPDATED = "catalog.category_updated"
    CATEGORY_DELETED = "catalog.category_deleted"
    CATEGORY_RESTORED = "catalog.category_restored"
    ATTRIBUTE_CREATED = "catalog.attribute_created"
    ATTRIBUTE_UPDATED = "catalog.attribute_updated"
    ATTRIBUTE_DELETED = "catalog.attribute_deleted"
    OPTION_CREATED = "catalog.attribute_option_created"
    OPTION_UPDATED = "catalog.attribute_option_updated"
    OPTION_DELETED = "catalog.attribute_option_deleted"
    ATTRIBUTES_ASSIGNED = "catalog.category_attributes_assigned"


def _localized(mapping: dict[str, Any], locale: str) -> str | None:
    """Значение локали с откатом на язык по умолчанию."""
    value = mapping.get(locale) or mapping.get(settings.DEFAULT_LOCALE)
    return str(value) if value is not None else None


def upsert_category_translations(
    session: AsyncSession, category: Category, translations: Mapping[str, Any]
) -> None:
    """Обновляет переданные локали категории, не трогая остальные.

    Общее правило Admin API и Excel-импорта. Коллекция
    `category.translations` должна быть загружена заранее.
    """
    existing = {item.locale: item for item in category.translations}
    for locale, payload in translations.items():
        data = payload.model_dump()
        if locale in existing:
            for field, value in data.items():
                setattr(existing[locale], field, value)
        else:
            session.add(CategoryTranslation(category_id=category.id, locale=locale, **data))


class AdminCategoryService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = AdminCategoryRepository(session)
        self.attributes = AdminAttributeRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------- чтение
    async def list_categories(
        self,
        *,
        params: PageParams,
        include_deleted: bool = False,
        is_active: bool | None = None,
        parent_id: int | None = None,
        search: str | None = None,
    ) -> Page[CategoryRead]:
        rows, total = await self.repository.list_categories(
            params=params,
            include_deleted=include_deleted,
            is_active=is_active,
            parent_id=parent_id,
            search=search,
        )
        counts = await self.repository.count_products([item.id for item in rows])
        return Page.create([self._to_read(item, counts) for item in rows], total, params)

    async def get_tree(self, *, include_deleted: bool = False) -> list[CategoryTreeNode]:
        categories = await self.repository.list_all(include_deleted=include_deleted)
        counts = await self.repository.count_products([item.id for item in categories])

        nodes = {
            item.id: CategoryTreeNode(
                id=item.id,
                slug=item.slug,
                name=self._name(item),
                parent_id=item.parent_id,
                depth=item.depth,
                sort_order=item.sort_order,
                is_active=item.is_active,
                products_count=counts.get(item.id, 0),
                deleted_at=item.deleted_at,
            )
            for item in categories
        }
        roots: list[CategoryTreeNode] = []
        present = set(nodes)
        for item in categories:
            if item.parent_id is not None and item.parent_id in present:
                nodes[item.parent_id].children.append(nodes[item.id])
            else:
                roots.append(nodes[item.id])
        return roots

    async def get_category(self, category_id: int) -> CategoryRead:
        category = await self._require(category_id)
        counts = await self.repository.count_products([category.id])
        return self._to_read(category, counts)

    # -------------------------------------------------------------- запись
    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def create_category(self, payload: CategoryCreate, actor: User) -> CategoryRead:
        if await self.repository.get_by_slug(payload.slug) is not None:
            raise SlugAlreadyExistsError

        parent = await self._resolve_parent(payload.parent_id)

        category = Category(
            slug=payload.slug,
            parent_id=parent.id if parent else None,
            depth=(parent.depth + 1) if parent else 0,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
            external_id=payload.external_id,
            image_media_id=await self._resolve_image(payload.image),
            path="",
        )
        self.session.add(category)
        await self.session.flush()
        # Путь строится из id, поэтому заполняется после flush.
        category.path = f"{parent.path}.{category.id}" if parent else str(category.id)

        for locale, translation in payload.translations.items():
            self.session.add(
                CategoryTranslation(
                    category_id=category.id, locale=locale, **translation.model_dump()
                )
            )
        await self.session.flush()

        self.audit.record(
            action=CatalogAction.CATEGORY_CREATED,
            entity_type=AuditEntity.CATEGORY,
            entity_id=category.id,
            user_id=actor.id,
            changes={"slug": {"old": None, "new": category.slug}},
        )
        await self.commit()
        return await self.get_category(category.id)

    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def update_category(
        self, category_id: int, payload: CategoryUpdate, actor: User
    ) -> CategoryRead:
        category = await self._require(category_id)
        fields = payload.model_dump(exclude_unset=True)
        changes: dict[str, Any] = {}

        # Порядок важен: перенос ветки выполняется массовым UPDATE и
        # делает загруженный объект неактуальным, поэтому идёт последним,
        # а всё остальное правится до него.
        if "slug" in fields and fields["slug"] != category.slug:
            existing = await self.repository.get_by_slug(fields["slug"])
            if existing is not None and existing.id != category.id:
                raise SlugAlreadyExistsError
            changes["slug"] = {"old": category.slug, "new": fields["slug"]}
            category.slug = fields["slug"]

        for field in ("sort_order", "is_active", "external_id"):
            if field in fields and fields[field] != getattr(category, field):
                changes[field] = {"old": getattr(category, field), "new": fields[field]}
                setattr(category, field, fields[field])

        # Переданный null снимает обложку; отсутствие ключа её не трогает.
        if "image" in fields:
            image_media_id = await self._resolve_image(payload.image)
            if image_media_id != category.image_media_id:
                changes["image_media_id"] = {
                    "old": category.image_media_id,
                    "new": image_media_id,
                }
                category.image_media_id = image_media_id

        if payload.translations is not None:
            await self._upsert_translations(category, payload.translations)
            changes["translations"] = {"old": None, "new": sorted(payload.translations)}

        await self.session.flush()

        if "parent_id" in fields and fields["parent_id"] != category.parent_id:
            changes["parent_id"] = {"old": category.parent_id, "new": fields["parent_id"]}
            await self._move(category, fields["parent_id"])
        if changes:
            self.audit.record(
                action=CatalogAction.CATEGORY_UPDATED,
                entity_type=AuditEntity.CATEGORY,
                entity_id=category.id,
                user_id=actor.id,
                changes=changes,
            )
        await self.commit()
        return await self.get_category(category.id)

    async def delete_category(self, category_id: int, actor: User) -> None:
        """Мягкое удаление с проверкой целостности каталога.

        Физическое удаление недопустимо: внешний ключ
        `product_categories → categories` объявлен с ON DELETE CASCADE,
        поэтому DELETE молча оборвал бы привязку товаров к разделу.
        """
        category = await self._require(category_id)
        if category.deleted_at is not None:
            raise NotFoundError("Категория уже удалена")

        if await self.repository.has_living_children(category.id):
            raise CategoryHasChildrenError

        linked = await self.repository.count_linked_products(category.id)
        if linked:
            raise CategoryHasProductsError(
                details={"products_count": linked},
            )

        category.deleted_at = datetime.now(UTC)
        category.is_active = False
        self.audit.record(
            action=CatalogAction.CATEGORY_DELETED,
            entity_type=AuditEntity.CATEGORY,
            entity_id=category.id,
            user_id=actor.id,
            changes={"deleted_at": {"old": None, "new": category.deleted_at.isoformat()}},
        )
        await self.commit()

    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def restore_category(self, category_id: int, actor: User) -> CategoryRead:
        category = await self._require(category_id)
        if category.deleted_at is None:
            raise CategoryNotDeletedError

        # Slug мог быть занят другой категорией, пока эта была удалена.
        conflict = await self.repository.get_by_slug(category.slug)
        if conflict is not None and conflict.id != category.id:
            raise SlugAlreadyExistsError

        parent = await self._resolve_parent(category.parent_id)
        if category.parent_id is not None and parent is None:
            raise ParentCategoryDeletedError

        category.deleted_at = None
        self.audit.record(
            action=CatalogAction.CATEGORY_RESTORED,
            entity_type=AuditEntity.CATEGORY,
            entity_id=category.id,
            user_id=actor.id,
        )
        await self.commit()
        return await self.get_category(category.id)

    # ------------------------------------------- связь категория ↔ атрибуты
    async def get_category_attributes(self, category_id: int) -> list[CategoryAttributeRead]:
        await self._require(category_id)
        rows = await self.repository.list_category_attributes(category_id)
        return [
            CategoryAttributeRead(
                attribute_id=attribute.id,
                code=attribute.code,
                name=_localized(attribute.name_i18n or {}, settings.DEFAULT_LOCALE)
                or attribute.code,
                value_type=attribute.value_type,
                unit=attribute.unit,
                sort_order=link.sort_order,
                is_required=link.is_required,
            )
            for link, attribute in rows
        ]

    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def set_category_attributes(
        self, category_id: int, payload: CategoryAttributesUpdate, actor: User
    ) -> list[CategoryAttributeRead]:
        category = await self._require(category_id)

        for item in payload.items:
            if await self.attributes.get_by_id(item.attribute_id) is None:
                raise NotFoundError(f"Характеристика {item.attribute_id} не найдена")

        await self.repository.replace_attributes(
            category.id,
            [
                CategoryAttribute(
                    category_id=category.id,
                    attribute_id=item.attribute_id,
                    sort_order=item.sort_order,
                    is_required=item.is_required,
                )
                for item in payload.items
            ],
        )
        self.audit.record(
            action=CatalogAction.ATTRIBUTES_ASSIGNED,
            entity_type=AuditEntity.CATEGORY_ATTRIBUTES,
            entity_id=category.id,
            user_id=actor.id,
            changes={"attribute_ids": [item.attribute_id for item in payload.items]},
        )
        await self.commit()
        return await self.get_category_attributes(category.id)

    # ----------------------------------------------------------- внутреннее
    async def _require(self, category_id: int) -> Category:
        category = await self.repository.get_by_id(category_id)
        if category is None:
            raise NotFoundError("Категория не найдена")
        return category

    async def _resolve_parent(self, parent_id: int | None) -> Category | None:
        if parent_id is None:
            return None
        parent = await self.repository.get_by_id(parent_id)
        if parent is None:
            raise NotFoundError("Родительская категория не найдена")
        if parent.deleted_at is not None:
            raise ParentCategoryDeletedError
        return parent

    async def _move(self, category: Category, parent_id: int | None) -> None:
        """Смена родителя с пересчётом пути всей ветки."""
        if parent_id == category.id:
            raise CategoryCycleError

        parent = await self._resolve_parent(parent_id)
        if parent is not None and (
            parent.path == category.path or parent.path.startswith(f"{category.path}.")
        ):
            # Новый родитель находится внутри перемещаемой ветки —
            # получилось бы кольцо, недостижимое из корня.
            raise CategoryCycleError

        new_path = f"{parent.path}.{category.id}" if parent else str(category.id)
        new_depth = (parent.depth + 1) if parent else 0
        old_path = category.path

        category.parent_id = parent.id if parent else None
        await self.session.flush()

        # Один UPDATE переписывает путь и глубину у самой категории и всех
        # её потомков. После него загруженные объекты устарели, поэтому
        # обращаться к ним больше нельзя — вызывающий код перечитывает
        # категорию отдельным запросом.
        await self.repository.move_subtree(
            old_path=old_path,
            new_path=new_path,
            depth_delta=new_depth - category.depth,
        )

    async def _upsert_translations(self, category: Category, translations: dict[str, Any]) -> None:
        upsert_category_translations(self.session, category, translations)

    def _name(self, category: Category) -> str:
        by_locale = {item.locale: item for item in category.translations}
        translation = by_locale.get(settings.DEFAULT_LOCALE) or next(iter(by_locale.values()), None)
        return translation.name if translation else category.slug

    async def _resolve_image(self, image: UUID | None) -> int | None:
        """UUID файла медиатеки → внутренний id.

        Несуществующий файл — 404 медиатеки, а не молчаливое «без
        картинки»: админка должна узнать, что выбранного файла нет.
        """
        if image is None:
            return None
        media = await self.repository.get_media_by_uuid(image)
        if media is None:
            raise MediaNotFoundError
        return media.id

    def _image_read(self, category: Category) -> CategoryImageRead | None:
        media = category.image_media
        if media is None:
            return None
        return CategoryImageRead(
            uuid=media.uuid,
            url=variant_urls(media).get("thumb") or primary_url(media),
        )

    def _to_read(self, category: Category, counts: dict[int, int]) -> CategoryRead:
        return CategoryRead(
            id=category.id,
            slug=category.slug,
            parent_id=category.parent_id,
            path=category.path,
            depth=category.depth,
            sort_order=category.sort_order,
            is_active=category.is_active,
            external_id=category.external_id,
            name=self._name(category),
            image=self._image_read(category),
            translations={
                item.locale: CategoryTranslationRead.model_validate(item)
                for item in category.translations
            },
            products_count=counts.get(category.id, 0),
            created_at=category.created_at,
            updated_at=category.updated_at,
            deleted_at=category.deleted_at,
        )


class AdminAttributeService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = AdminAttributeRepository(session)
        self.audit = AuditService(session)

    async def list_attributes(
        self,
        *,
        params: PageParams,
        is_active: bool | None = None,
        is_filterable: bool | None = None,
        search: str | None = None,
    ) -> Page[AttributeRead]:
        rows, total = await self.repository.list_attributes(
            params=params, is_active=is_active, is_filterable=is_filterable, search=search
        )
        ids = [item.id for item in rows]
        usage = await self.repository.count_usage(ids)
        categories = await self._categories(ids)
        return Page.create([self._to_read(item, usage, categories) for item in rows], total, params)

    async def get_attribute(self, attribute_id: int) -> AttributeRead:
        attribute = await self._require(attribute_id)
        usage = await self.repository.count_usage([attribute.id])
        return self._to_read(attribute, usage, await self._categories([attribute.id]))

    async def _categories(self, attribute_ids: list[int]) -> dict[int, list[AttributeCategoryRef]]:
        """Категории страницы характеристик — одним запросом."""
        result: dict[int, list[AttributeCategoryRef]] = {}
        for attribute_id, category in await self.repository.list_assigned_categories(attribute_ids):
            by_locale = {item.locale: item for item in category.translations}
            translation = by_locale.get(settings.DEFAULT_LOCALE) or next(
                iter(by_locale.values()), None
            )
            result.setdefault(attribute_id, []).append(
                AttributeCategoryRef(
                    id=category.id,
                    slug=category.slug,
                    name=translation.name if translation else category.slug,
                )
            )
        return result

    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def create_attribute(self, payload: AttributeCreate, actor: User) -> AttributeRead:
        if await self.repository.get_by_code(payload.code) is not None:
            raise AttributeCodeExistsError

        attribute = Attribute(
            code=payload.code,
            value_type=payload.value_type.value,
            unit=payload.unit,
            is_filterable=payload.is_filterable,
            is_visible=payload.is_visible,
            is_active=payload.is_active,
            sort_order=payload.sort_order,
            name_i18n=dict(payload.names),
        )
        self.session.add(attribute)
        await self.session.flush()

        for option in payload.options:
            self.session.add(
                AttributeOption(
                    attribute_id=attribute.id,
                    slug=option.slug,
                    sort_order=option.sort_order,
                    value_i18n=dict(option.values),
                )
            )
        await self.session.flush()

        self.audit.record(
            action=CatalogAction.ATTRIBUTE_CREATED,
            entity_type=AuditEntity.ATTRIBUTE,
            entity_id=attribute.id,
            user_id=actor.id,
            changes={"code": {"old": None, "new": attribute.code}},
        )
        await self.commit()
        return await self.get_attribute(attribute.id)

    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def update_attribute(
        self, attribute_id: int, payload: AttributeUpdate, actor: User
    ) -> AttributeRead:
        attribute = await self._require(attribute_id)
        fields = payload.model_dump(exclude_unset=True)
        changes: dict[str, Any] = {}

        for field in ("unit", "is_filterable", "is_visible", "is_active", "sort_order"):
            if field in fields and fields[field] != getattr(attribute, field):
                changes[field] = {"old": getattr(attribute, field), "new": fields[field]}
                setattr(attribute, field, fields[field])

        if payload.names is not None:
            merged = {**(attribute.name_i18n or {}), **payload.names}
            changes["names"] = {"old": attribute.name_i18n, "new": merged}
            attribute.name_i18n = merged

        await self.session.flush()
        if changes:
            self.audit.record(
                action=CatalogAction.ATTRIBUTE_UPDATED,
                entity_type=AuditEntity.ATTRIBUTE,
                entity_id=attribute.id,
                user_id=actor.id,
                changes=changes,
            )
        await self.commit()
        return await self.get_attribute(attribute.id)

    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def delete_attribute(self, attribute_id: int, actor: User) -> None:
        """Удаление только неиспользуемой характеристики.

        У `attributes` нет `deleted_at`, а внешний ключ из
        `product_attribute_values` объявлен с ON DELETE RESTRICT, поэтому
        удалить используемую характеристику база и так не даст. Проверка
        нужна, чтобы вместо 500 от нарушения ограничения администратор
        получил понятную ошибку и подсказку: отключить характеристику
        через `is_active`, а не удалять.
        """
        attribute = await self._require(attribute_id)
        usage = (await self.repository.count_usage([attribute.id])).get(attribute.id, 0)
        if usage:
            raise AttributeInUseError(details={"usage_count": usage})

        await self.session.delete(attribute)
        self.audit.record(
            action=CatalogAction.ATTRIBUTE_DELETED,
            entity_type=AuditEntity.ATTRIBUTE,
            entity_id=attribute.id,
            user_id=actor.id,
            changes={"code": {"old": attribute.code, "new": None}},
        )
        await self.commit()

    # ------------------------------------------------------------- варианты
    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def create_option(
        self, attribute_id: int, payload: AttributeOptionCreate, actor: User
    ) -> AttributeOptionRead:
        attribute = await self._require(attribute_id)
        self._require_option_type(attribute)

        if await self.repository.find_option_by_slug(attribute.id, payload.slug) is not None:
            raise SlugAlreadyExistsError("Вариант с таким slug уже есть у характеристики")

        option = AttributeOption(
            attribute_id=attribute.id,
            slug=payload.slug,
            sort_order=payload.sort_order,
            value_i18n=dict(payload.values),
        )
        self.session.add(option)
        await self.session.flush()

        self.audit.record(
            action=CatalogAction.OPTION_CREATED,
            entity_type=AuditEntity.ATTRIBUTE_OPTION,
            entity_id=option.id,
            user_id=actor.id,
            changes={"attribute_id": attribute.id, "slug": option.slug},
        )
        await self.commit()
        return self._option_to_read(option)

    @guard_unique(CATALOG_UNIQUE_ERRORS)
    async def update_option(
        self, attribute_id: int, option_id: int, payload: AttributeOptionUpdate, actor: User
    ) -> AttributeOptionRead:
        option = await self.repository.get_option(attribute_id, option_id)
        if option is None:
            raise NotFoundError("Вариант значения не найден")

        fields = payload.model_dump(exclude_unset=True)
        changes: dict[str, Any] = {}

        if "slug" in fields and fields["slug"] != option.slug:
            existing = await self.repository.find_option_by_slug(attribute_id, fields["slug"])
            if existing is not None and existing.id != option.id:
                raise SlugAlreadyExistsError("Вариант с таким slug уже есть у характеристики")
            changes["slug"] = {"old": option.slug, "new": fields["slug"]}
            option.slug = fields["slug"]

        if "sort_order" in fields and fields["sort_order"] != option.sort_order:
            changes["sort_order"] = {"old": option.sort_order, "new": fields["sort_order"]}
            option.sort_order = fields["sort_order"]

        if payload.values is not None:
            merged = {**(option.value_i18n or {}), **payload.values}
            changes["values"] = {"old": option.value_i18n, "new": merged}
            option.value_i18n = merged

        await self.session.flush()
        if changes:
            self.audit.record(
                action=CatalogAction.OPTION_UPDATED,
                entity_type=AuditEntity.ATTRIBUTE_OPTION,
                entity_id=option.id,
                user_id=actor.id,
                changes=changes,
            )
        await self.commit()
        return self._option_to_read(option)

    async def delete_option(self, attribute_id: int, option_id: int, actor: User) -> None:
        option = await self.repository.get_option(attribute_id, option_id)
        if option is None:
            raise NotFoundError("Вариант значения не найден")

        usage = await self.repository.count_option_usage(option.id)
        if usage:
            raise AttributeOptionInUseError(details={"usage_count": usage})

        await self.session.delete(option)
        self.audit.record(
            action=CatalogAction.OPTION_DELETED,
            entity_type=AuditEntity.ATTRIBUTE_OPTION,
            entity_id=option_id,
            user_id=actor.id,
            changes={"attribute_id": attribute_id, "slug": option.slug},
        )
        await self.commit()

    # ----------------------------------------------------------- внутреннее
    async def _require(self, attribute_id: int) -> Attribute:
        attribute = await self.repository.get_by_id(attribute_id)
        if attribute is None:
            raise NotFoundError("Характеристика не найдена")
        return attribute

    def _require_option_type(self, attribute: Attribute) -> None:
        from app.modules.catalog.enums import AttributeValueType

        if attribute.value_type != AttributeValueType.OPTION.value:
            raise AttributeTypeMismatchError

    def _option_to_read(self, option: AttributeOption) -> AttributeOptionRead:
        return AttributeOptionRead(
            id=option.id,
            slug=option.slug,
            sort_order=option.sort_order,
            values={str(key): str(value) for key, value in (option.value_i18n or {}).items()},
        )

    def _to_read(
        self,
        attribute: Attribute,
        usage: dict[int, int],
        categories: dict[int, list[AttributeCategoryRef]] | None = None,
    ) -> AttributeRead:
        return AttributeRead(
            id=attribute.id,
            code=attribute.code,
            value_type=attribute.value_type,
            unit=attribute.unit,
            is_filterable=attribute.is_filterable,
            is_visible=attribute.is_visible,
            is_active=attribute.is_active,
            sort_order=attribute.sort_order,
            name=_localized(attribute.name_i18n or {}, settings.DEFAULT_LOCALE) or attribute.code,
            names={str(key): str(value) for key, value in (attribute.name_i18n or {}).items()},
            options=[
                self._option_to_read(option)
                for option in sorted(attribute.options, key=lambda item: (item.sort_order, item.id))
            ],
            usage_count=usage.get(attribute.id, 0),
            categories=(categories or {}).get(attribute.id, []),
            created_at=attribute.created_at,
            updated_at=attribute.updated_at,
        )
