"""Запросы Admin API медиатеки и изображений товаров."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Select, Text, cast, func, select, update
from sqlalchemy.orm import joinedload

from app.core.pagination import PageParams
from app.core.repository import BaseRepository
from app.modules.catalog.models import Category, Product
from app.modules.content.models import ContentSection
from app.modules.media.models import MediaFile, ProductImage


@dataclass(frozen=True)
class MediaAdminFilters:
    status: str | None = None
    search: str | None = None


@dataclass(frozen=True)
class MediaUsage:
    image_id: int
    product_id: int
    sku: str
    is_deleted: bool


class AdminMediaRepository(BaseRepository[MediaFile]):
    model = MediaFile

    def _usage_counts(self) -> Any:
        """Число привязок к товарам агрегатом, а не запросом на каждый файл."""
        return (
            select(
                ProductImage.media_file_id.label("media_file_id"),
                func.count().label("usage_count"),
            )
            .group_by(ProductImage.media_file_id)
            .subquery("usage")
        )

    async def list_media(
        self, *, filters: MediaAdminFilters, params: PageParams
    ) -> tuple[list[tuple[MediaFile, int]], int]:
        usage = self._usage_counts()
        query: Select[Any] = select(
            MediaFile, func.coalesce(usage.c.usage_count, 0).label("usage_count")
        ).outerjoin(usage, usage.c.media_file_id == MediaFile.id)

        if filters.status is not None:
            query = query.where(MediaFile.status == filters.status)
        if filters.search and filters.search.strip():
            query = query.where(MediaFile.original_filename.ilike(f"%{filters.search.strip()}%"))

        total = (
            await self.session.execute(
                select(func.count()).select_from(query.with_only_columns(MediaFile.id).subquery())
            )
        ).scalar_one()

        rows = (
            await self.session.execute(
                query.order_by(MediaFile.created_at.desc(), MediaFile.id.desc())
                .limit(params.limit)
                .offset(params.offset)
            )
        ).all()
        return [(row[0], int(row.usage_count)) for row in rows], total

    async def get_by_uuid(self, media_uuid: UUID, *, for_update: bool = False) -> MediaFile | None:
        query = (
            select(MediaFile)
            .where(MediaFile.uuid == media_uuid)
            .execution_options(populate_existing=True)
        )
        if for_update:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalars().first()

    async def get_by_uuids(
        self, media_uuids: Sequence[UUID], *, for_share: bool = False
    ) -> dict[UUID, MediaFile]:
        """Файлы по набору UUID одним запросом.

        FOR SHARE удерживает строки до конца транзакции: параллельное
        удаление файла дождётся её и увидит новую ссылку на него.
        """
        if not media_uuids:
            return {}
        query = select(MediaFile).where(MediaFile.uuid.in_(list(media_uuids)))
        if for_share:
            query = query.with_for_update(read=True)
        return {item.uuid: item for item in (await self.session.execute(query)).scalars().all()}

    async def lock_for_processing(self, media_id: int) -> MediaFile | None:
        """Строка файла под блокировкой на время обработки.

        SKIP LOCKED: если тот же файл уже обрабатывает другой воркер
        (повторная постановка в очередь), второй просто пропускает его.
        """
        query = (
            select(MediaFile)
            .where(MediaFile.id == media_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(query)).scalars().first()

    async def count_usage(self, media_id: int) -> int:
        query = select(func.count()).where(ProductImage.media_file_id == media_id)
        return int((await self.session.execute(query)).scalar_one())

    async def list_usages(self, media_id: int) -> list[MediaUsage]:
        query = (
            select(ProductImage.id, Product.id, Product.sku, Product.deleted_at)
            .join(Product, Product.id == ProductImage.product_id)
            .where(ProductImage.media_file_id == media_id)
            .order_by(Product.id)
        )
        return [
            MediaUsage(
                image_id=row[0], product_id=row[1], sku=row[2], is_deleted=row[3] is not None
            )
            for row in (await self.session.execute(query)).all()
        ]

    async def categories_using(self, media_id: int) -> list[str]:
        """Разделы каталога, у которых этот файл стоит обложкой.

        Удалённые категории тоже считаются: их можно восстановить,
        и картинка им понадобится.
        """
        query = (
            select(Category.slug).where(Category.image_media_id == media_id).order_by(Category.slug)
        )
        return list((await self.session.execute(query)).scalars().all())

    async def content_sections_referencing(self, media_uuid: UUID) -> list[str]:
        """Разделы CMS, в данных которых упомянут файл.

        Ссылки из CMS живут в JSONB и внешним ключом не защищены, поэтому
        проверяются здесь. Поиск по тексту документа надёжен: UUID
        уникален, случайного совпадения с обычным текстом не бывает,
        а ложное срабатывание лишь запретит удаление.
        """
        query = (
            select(ContentSection.key)
            .where(cast(ContentSection.data, Text).like(f"%{media_uuid}%"))
            .order_by(ContentSection.key)
        )
        return list((await self.session.execute(query)).scalars().all())

    async def delete(self, media: MediaFile) -> None:
        await self.session.delete(media)
        await self.session.flush()


class AdminProductImageRepository(BaseRepository[ProductImage]):
    model = ProductImage

    async def get_product(self, product_id: int) -> Product | None:
        """Лёгкая выборка: переводы и характеристики здесь не нужны."""
        query = select(Product).where(Product.id == product_id)
        return (await self.session.execute(query)).scalars().first()

    async def lock_product(self, product_id: int) -> None:
        """Сериализует правки галереи одного товара.

        Порядок и признак главного изображения — свойства набора целиком;
        без блокировки два параллельных запроса выдали бы одинаковый
        sort_order или упёрлись бы в уникальный индекс главного фото.
        """
        await self.session.execute(
            select(Product.id).where(Product.id == product_id).with_for_update()
        )

    async def list_images(self, product_id: int) -> list[ProductImage]:
        query = (
            select(ProductImage)
            .where(ProductImage.product_id == product_id)
            .options(joinedload(ProductImage.media_file))
            .order_by(ProductImage.sort_order, ProductImage.id)
            .execution_options(populate_existing=True)
        )
        return list((await self.session.execute(query)).scalars().all())

    async def next_sort_order(self, product_id: int) -> int:
        query = select(func.coalesce(func.max(ProductImage.sort_order), -1)).where(
            ProductImage.product_id == product_id
        )
        return int((await self.session.execute(query)).scalar_one()) + 1

    async def clear_main(self, product_id: int) -> None:
        """Снимает флаг главного изображения до назначения нового.

        Уникальный индекс uq_product_images_main не отложенный: если
        сначала поставить новый флаг, а потом снять старый, база
        отвергнет промежуточное состояние.
        """
        await self.session.execute(
            update(ProductImage)
            .where(ProductImage.product_id == product_id, ProductImage.is_main.is_(True))
            .values(is_main=False)
            .execution_options(synchronize_session="fetch")
        )
        await self.session.flush()

    async def delete(self, image: ProductImage) -> None:
        await self.session.delete(image)
        await self.session.flush()
