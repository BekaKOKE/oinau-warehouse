"""Бизнес-правила Admin API CMS.

Раздел сохраняется целиком (PUT): форма в админке всегда отправляет
документ полностью, а частичные слияния вложенных списков (FAQ,
способы доставки) порождали бы неочевидные результаты.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.content.enums import ContentSectionKey
from app.modules.content.models import ContentSection
from app.modules.content.repository import ContentRepository
from app.modules.content.schemas_admin import (
    SECTION_SCHEMAS,
    ContentModel,
    ContentSectionRead,
    ContentSectionSummary,
    collect_media_refs,
)
from app.modules.media.enums import MediaStatus
from app.modules.media.exceptions import MediaFailedError, MediaNotFoundError
from app.modules.media.repository_admin import AdminMediaRepository
from app.modules.users.models import User

CONTENT_ENTITY = "content_section"


class ContentAuditAction:
    SECTION_UPDATED = "content.section_updated"


# Значение поля в журнале аудита хранится целиком, только если оно
# небольшое. Длинный текст (ответы FAQ, описание доставки) дал бы
# сотни килобайт на одну запись; факт изменения поля важнее его копии.
AUDIT_VALUE_LIMIT = 2000


def _audit_value(value: Any) -> Any:
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded) <= AUDIT_VALUE_LIMIT:
        return value
    return {"omitted": True, "size": len(encoded)}


def parse_section[DataT: ContentModel](
    section: ContentSection | None, schema: type[DataT]
) -> DataT:
    """Данные раздела; для ещё не сохранённого раздела — пустые значения."""
    return schema.model_validate(section.data if section is not None else {})


class AdminContentService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = ContentRepository(session)
        self.media = AdminMediaRepository(session)
        self.audit = AuditService(session)

    async def list_sections(self) -> list[ContentSectionSummary]:
        stored = {item.key: item for item in await self.repository.list_sections()}
        return [
            ContentSectionSummary(
                key=key,
                is_configured=key.value in stored,
                updated_at=stored[key.value].updated_at if key.value in stored else None,
                updated_by_id=stored[key.value].updated_by_id if key.value in stored else None,
            )
            for key in ContentSectionKey
        ]

    async def get_section[DataT: ContentModel](
        self, key: ContentSectionKey, schema: type[DataT]
    ) -> ContentSectionRead[DataT]:
        section = (await self.repository.get_sections([key])).get(key.value)
        return self._to_read(key, section, parse_section(section, schema))

    async def update_section[DataT: ContentModel](
        self, key: ContentSectionKey, payload: DataT, actor: User
    ) -> ContentSectionRead[DataT]:
        if not isinstance(payload, SECTION_SCHEMAS[key]):
            raise TypeError(f"Схема {type(payload).__name__} не соответствует разделу {key}")

        await self._check_media(payload)
        section, created = await self.repository.get_for_update(key)

        old = dict(section.data or {})
        new = payload.model_dump(mode="json")
        changes = {
            field: {"old": _audit_value(old.get(field)), "new": _audit_value(new.get(field))}
            for field in sorted(set(old) | set(new))
            if old.get(field) != new.get(field)
        }

        # Первое сохранение фиксируется в журнале, даже если документ
        # пуст: появление раздела — тоже изменение.
        if changes or created:
            section.data = new
            section.updated_by_id = actor.id
            await self.session.flush()
            self.audit.record(
                action=ContentAuditAction.SECTION_UPDATED,
                entity_type=CONTENT_ENTITY,
                entity_id=section.id,
                user_id=actor.id,
                changes={"section": key.value, "created": created, **changes},
            )
        await self.commit()
        await self.session.refresh(section)
        return self._to_read(key, section, payload)

    async def _check_media(self, payload: ContentModel) -> None:
        """Ссылки на медиатеку должны вести на существующие файлы.

        FOR SHARE удерживает файлы до коммита: параллельное удаление
        файла дождётся сохранения раздела и увидит ссылку на него.
        Не готовый (PENDING/PROCESSING) файл допустим — витрина покажет
        его, когда обработка завершится; FAILED готовым не станет.
        """
        refs = collect_media_refs(payload)
        if not refs:
            return
        found = await self.media.get_by_uuids(sorted(refs), for_share=True)
        missing = sorted(str(item) for item in refs - set(found))
        if missing:
            raise MediaNotFoundError(details={"media_uuids": missing})
        failed = sorted(
            str(media.uuid) for media in found.values() if media.status == MediaStatus.FAILED.value
        )
        if failed:
            raise MediaFailedError(details={"media_uuids": failed})

    def _to_read[DataT: ContentModel](
        self, key: ContentSectionKey, section: ContentSection | None, data: DataT
    ) -> ContentSectionRead[DataT]:
        # Параметризация конкретной схемой обязательна: непараметризованная
        # модель сериализовала бы `data` как пустой ContentModel.
        read_model: type[ContentSectionRead[DataT]] = ContentSectionRead[type(data)]  # type: ignore[assignment,misc]
        return read_model(
            key=key,
            data=data,
            is_configured=section is not None,
            updated_at=section.updated_at if section is not None else None,
            updated_by_id=section.updated_by_id if section is not None else None,
        )
