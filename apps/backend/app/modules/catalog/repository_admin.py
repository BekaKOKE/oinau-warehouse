"""Запросы Admin API каталога.

В отличие от публичного репозитория, здесь по умолчанию видны все записи,
кроме мягко удалённых: администратор работает и с черновиками, и
с отключёнными категориями.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, Text, cast, delete, func, or_, select, update
from sqlalchemy.orm import joinedload, selectinload

from app.core.pagination import PageParams
from app.core.repository import BaseRepository
from app.modules.catalog.models import (
    Attribute,
    AttributeOption,
    Category,
    CategoryAttribute,
    CategoryTranslation,
    ProductAttributeValue,
    ProductCategory,
)
from app.modules.media.models import MediaFile


class AdminCategoryRepository(BaseRepository[Category]):
    model = Category

    def _query(self, *, include_deleted: bool) -> Select[tuple[Category]]:
        # populate_existing обязателен: сервис читает категорию, меняет её,
        # коммитит и читает снова в той же сессии. Без него SQLAlchemy
        # вернёт объект из identity map со СТАРОЙ коллекцией переводов,
        # и только что добавленный перевод не попадёт в ответ.
        query = (
            select(Category)
            # Обложка нужна каждому ответу, а связь помечена
            # lazy="raise" — подгружается явно, одним запросом.
            .options(selectinload(Category.translations), joinedload(Category.image_media))
            .execution_options(populate_existing=True)
        )
        if not include_deleted:
            query = query.where(Category.deleted_at.is_(None))
        return query

    async def get_by_id(self, category_id: int, *, include_deleted: bool = True) -> Category | None:
        query = self._query(include_deleted=include_deleted).where(Category.id == category_id)
        return (await self.session.execute(query)).scalars().first()

    async def get_media_by_uuid(self, media_uuid: UUID) -> MediaFile | None:
        """Файл медиатеки по публичному UUID — для выбора обложки."""
        query = select(MediaFile).where(MediaFile.uuid == media_uuid)
        return (await self.session.execute(query)).scalars().first()

    async def get_by_slug(self, slug: str) -> Category | None:
        """Поиск среди живых категорий.

        Удалённая категория slug не занимает — это соответствует
        частичному уникальному индексу `WHERE deleted_at IS NULL`.
        """
        query = self._query(include_deleted=False).where(Category.slug == slug)
        return (await self.session.execute(query)).scalars().first()

    async def list_categories(
        self,
        *,
        params: PageParams,
        include_deleted: bool = False,
        is_active: bool | None = None,
        parent_id: int | None = None,
        search: str | None = None,
    ) -> tuple[Sequence[Category], int]:
        query = self._query(include_deleted=include_deleted)

        if is_active is not None:
            query = query.where(Category.is_active.is_(is_active))
        if parent_id is not None:
            query = query.where(Category.parent_id == parent_id)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Category.slug.ilike(pattern),
                    Category.id.in_(
                        select(CategoryTranslation.category_id).where(
                            CategoryTranslation.name.ilike(pattern)
                        )
                    ),
                )
            )

        total = (
            await self.session.execute(
                select(func.count()).select_from(query.with_only_columns(Category.id).subquery())
            )
        ).scalar_one()

        rows = (
            await self.session.execute(
                query.order_by(Category.path, Category.sort_order)
                .limit(params.limit)
                .offset(params.offset)
            )
        ).scalars()
        return rows.all(), total

    async def list_all(self, *, include_deleted: bool = False) -> Sequence[Category]:
        """Всё дерево целиком: переводы догружаются одним selectinload."""
        query = self._query(include_deleted=include_deleted).order_by(
            Category.depth, Category.sort_order, Category.id
        )
        return (await self.session.execute(query)).scalars().all()

    async def count_products(self, category_ids: Sequence[int]) -> dict[int, int]:
        """Число товаров по категориям одним запросом.

        Отдельный агрегат вместо загрузки связей: дерево из сотни
        категорий иначе дало бы сотню запросов.
        """
        if not category_ids:
            return {}
        query = (
            select(ProductCategory.category_id, func.count())
            .where(ProductCategory.category_id.in_(category_ids))
            .group_by(ProductCategory.category_id)
        )
        return {row[0]: row[1] for row in (await self.session.execute(query)).all()}

    async def has_living_children(self, category_id: int) -> bool:
        query = select(func.count()).where(
            Category.parent_id == category_id, Category.deleted_at.is_(None)
        )
        return bool((await self.session.execute(query)).scalar_one())

    async def count_linked_products(self, category_id: int) -> int:
        query = select(func.count()).where(ProductCategory.category_id == category_id)
        return int((await self.session.execute(query)).scalar_one())

    async def move_subtree(self, *, old_path: str, new_path: str, depth_delta: int) -> None:
        """Переносит ветку целиком одним UPDATE.

        Материализованный путь хранит предков строкой, поэтому смена
        родителя обязана переписать путь у всех потомков. Рекурсивный
        обход дал бы столько запросов, сколько узлов в ветке.
        """
        await self.session.execute(
            update(Category)
            .where(or_(Category.path == old_path, Category.path.like(f"{old_path}.%")))
            .values(
                path=func.concat(new_path, func.substr(Category.path, len(old_path) + 1)),
                depth=Category.depth + depth_delta,
            )
        )

    async def replace_attributes(
        self, category_id: int, items: Sequence[CategoryAttribute]
    ) -> None:
        await self.session.execute(
            delete(CategoryAttribute).where(CategoryAttribute.category_id == category_id)
        )
        for item in items:
            self.session.add(item)
        await self.session.flush()

    async def delete_attribute_links_for(self, category_ids: Sequence[int]) -> None:
        """Пакетный вариант replace_attributes() для импорта: одним DELETE."""
        if category_ids:
            await self.session.execute(
                delete(CategoryAttribute).where(CategoryAttribute.category_id.in_(category_ids))
            )

    async def list_category_attributes(
        self, category_id: int
    ) -> Sequence[tuple[CategoryAttribute, Attribute]]:
        query = (
            select(CategoryAttribute, Attribute)
            .join(Attribute, Attribute.id == CategoryAttribute.attribute_id)
            .where(CategoryAttribute.category_id == category_id)
            .order_by(CategoryAttribute.sort_order, Attribute.id)
        )
        return [(row[0], row[1]) for row in (await self.session.execute(query)).all()]


class AdminAttributeRepository(BaseRepository[Attribute]):
    model = Attribute

    def _query(self) -> Select[tuple[Attribute]]:
        # См. комментарий в AdminCategoryRepository._query.
        return (
            select(Attribute)
            .options(selectinload(Attribute.options))
            .execution_options(populate_existing=True)
        )

    async def get_by_id(self, attribute_id: int) -> Attribute | None:
        query = self._query().where(Attribute.id == attribute_id)
        return (await self.session.execute(query)).scalars().first()

    async def get_by_code(self, code: str) -> Attribute | None:
        query = self._query().where(Attribute.code == code)
        return (await self.session.execute(query)).scalars().first()

    async def list_attributes(
        self,
        *,
        params: PageParams,
        is_active: bool | None = None,
        is_filterable: bool | None = None,
        search: str | None = None,
    ) -> tuple[Sequence[Attribute], int]:
        query = self._query()
        if is_active is not None:
            query = query.where(Attribute.is_active.is_(is_active))
        if is_filterable is not None:
            query = query.where(Attribute.is_filterable.is_(is_filterable))
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Attribute.code.ilike(pattern),
                    # Поиск сразу по всем локалям: JSONB приводится к тексту.
                    # Индекс здесь не нужен — характеристик десятки, а не
                    # тысячи, и это админский поиск, а не витрина.
                    cast(Attribute.name_i18n, Text).ilike(pattern),
                )
            )

        total = (
            await self.session.execute(
                select(func.count()).select_from(query.with_only_columns(Attribute.id).subquery())
            )
        ).scalar_one()

        rows = (
            await self.session.execute(
                query.order_by(Attribute.sort_order, Attribute.id)
                .limit(params.limit)
                .offset(params.offset)
            )
        ).scalars()
        return rows.all(), total

    async def count_usage(self, attribute_ids: Sequence[int]) -> dict[int, int]:
        if not attribute_ids:
            return {}
        query = (
            select(ProductAttributeValue.attribute_id, func.count())
            .where(ProductAttributeValue.attribute_id.in_(attribute_ids))
            .group_by(ProductAttributeValue.attribute_id)
        )
        return {row[0]: row[1] for row in (await self.session.execute(query)).all()}

    async def list_assigned_categories(
        self, attribute_ids: Sequence[int]
    ) -> list[tuple[int, Category]]:
        """Неудалённые категории, которым назначены характеристики."""
        if not attribute_ids:
            return []
        query = (
            select(CategoryAttribute.attribute_id, Category)
            .join(Category, Category.id == CategoryAttribute.category_id)
            .where(
                CategoryAttribute.attribute_id.in_(attribute_ids),
                Category.deleted_at.is_(None),
            )
            .options(selectinload(Category.translations))
            .order_by(Category.path, Category.id)
        )
        return [(row[0], row[1]) for row in (await self.session.execute(query)).all()]

    async def count_option_usage(self, option_id: int) -> int:
        query = select(func.count()).where(ProductAttributeValue.option_id == option_id)
        return int((await self.session.execute(query)).scalar_one())

    async def get_option(self, attribute_id: int, option_id: int) -> AttributeOption | None:
        query = select(AttributeOption).where(
            AttributeOption.id == option_id, AttributeOption.attribute_id == attribute_id
        )
        return (await self.session.execute(query)).scalars().first()

    async def find_option_by_slug(self, attribute_id: int, slug: str) -> AttributeOption | None:
        query = select(AttributeOption).where(
            AttributeOption.attribute_id == attribute_id, AttributeOption.slug == slug
        )
        return (await self.session.execute(query)).scalars().first()
