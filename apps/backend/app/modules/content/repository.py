"""Запросы CMS."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.repository import BaseRepository
from app.modules.content.enums import ContentSectionKey
from app.modules.content.models import ContentSection
from app.modules.media.models import MediaFile


class ContentRepository(BaseRepository[ContentSection]):
    model = ContentSection

    async def get_sections(self, keys: Sequence[ContentSectionKey]) -> dict[str, ContentSection]:
        """Несколько разделов одним запросом (страница + общие настройки)."""
        query = (
            select(ContentSection)
            .where(ContentSection.key.in_([key.value for key in keys]))
            .execution_options(populate_existing=True)
        )
        return {item.key: item for item in (await self.session.execute(query)).scalars().all()}

    async def list_sections(self) -> list[ContentSection]:
        query = select(ContentSection).order_by(ContentSection.key)
        return list((await self.session.execute(query)).scalars().all())

    async def get_for_update(self, key: ContentSectionKey) -> tuple[ContentSection, bool]:
        """Строка раздела под блокировкой и признак «создана сейчас».

        Строка создаётся при первом сохранении. INSERT ... ON CONFLICT
        DO NOTHING вместо «проверить и вставить»: два первых сохранения
        раздела одновременно не упрутся в уникальный индекс, а
        последовательно пройдут через блокировку.
        """
        inserted = (
            await self.session.execute(
                insert(ContentSection)
                .values(key=key.value, data={})
                .on_conflict_do_nothing(index_elements=[ContentSection.key])
                .returning(ContentSection.id)
            )
        ).scalar_one_or_none()
        query = (
            select(ContentSection)
            .where(ContentSection.key == key.value)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(query)).scalars().one(), inserted is not None

    async def get_media(self, media_uuids: Sequence[UUID]) -> dict[UUID, MediaFile]:
        """Файлы, на которые ссылается контент, — одним запросом."""
        if not media_uuids:
            return {}
        query = select(MediaFile).where(MediaFile.uuid.in_(list(media_uuids)))
        return {item.uuid: item for item in (await self.session.execute(query)).scalars().all()}
