"""Admin API CMS — /api/v1/admin/content.

Чтение и запись — существующее право `content.write` (ADMIN,
CONTENT_MANAGER, SUPERADMIN). MANAGER и VIEWER его не имеют: форм
редактирования контента у них нет, а опубликованный контент им, как
и всем, доступен через публичный API.

Эндпоинты по разделам, а не один `/{key}`: у каждого раздела своя
схема, и OpenAPI должен описывать её точно, а не объединением всех.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep, require_permissions
from app.modules.content.enums import ContentSectionKey
from app.modules.content.schemas_admin import (
    ContactsContent,
    ContentSectionRead,
    ContentSectionSummary,
    DeliveryContent,
    FaqContent,
    HomeContent,
    RequisitesContent,
    ServicesContent,
    SiteSettingsContent,
)
from app.modules.content.service_admin import AdminContentService
from app.modules.users.models import User
from app.modules.users.permissions import CONTENT_WRITE

ContentEditor = Annotated[User, Depends(require_permissions(CONTENT_WRITE))]

router = APIRouter(prefix="/content", tags=["admin:content"])


@router.get("", response_model=list[ContentSectionSummary], summary="Разделы контента")
async def list_sections(session: SessionDep, _: ContentEditor) -> list[ContentSectionSummary]:
    return await AdminContentService(session).list_sections()


# ---------------------------------------------------------------- главная
@router.get("/home", response_model=ContentSectionRead[HomeContent], summary="Главная")
async def get_home(session: SessionDep, _: ContentEditor) -> ContentSectionRead[HomeContent]:
    return await AdminContentService(session).get_section(ContentSectionKey.HOME, HomeContent)


@router.put("/home", response_model=ContentSectionRead[HomeContent], summary="Сохранить главную")
async def put_home(
    payload: HomeContent, session: SessionDep, actor: ContentEditor
) -> ContentSectionRead[HomeContent]:
    return await AdminContentService(session).update_section(ContentSectionKey.HOME, payload, actor)


# --------------------------------------------------------------- контакты
@router.get("/contacts", response_model=ContentSectionRead[ContactsContent], summary="Контакты")
async def get_contacts(
    session: SessionDep, _: ContentEditor
) -> ContentSectionRead[ContactsContent]:
    return await AdminContentService(session).get_section(
        ContentSectionKey.CONTACTS, ContactsContent
    )


@router.put(
    "/contacts", response_model=ContentSectionRead[ContactsContent], summary="Сохранить контакты"
)
async def put_contacts(
    payload: ContactsContent, session: SessionDep, actor: ContentEditor
) -> ContentSectionRead[ContactsContent]:
    return await AdminContentService(session).update_section(
        ContentSectionKey.CONTACTS, payload, actor
    )


# ---------------------------------------------------------------- доставка
@router.get("/delivery", response_model=ContentSectionRead[DeliveryContent], summary="Доставка")
async def get_delivery(
    session: SessionDep, _: ContentEditor
) -> ContentSectionRead[DeliveryContent]:
    return await AdminContentService(session).get_section(
        ContentSectionKey.DELIVERY, DeliveryContent
    )


@router.put(
    "/delivery", response_model=ContentSectionRead[DeliveryContent], summary="Сохранить доставку"
)
async def put_delivery(
    payload: DeliveryContent, session: SessionDep, actor: ContentEditor
) -> ContentSectionRead[DeliveryContent]:
    return await AdminContentService(session).update_section(
        ContentSectionKey.DELIVERY, payload, actor
    )


# --------------------------------------------------------------------- FAQ
@router.get("/faq", response_model=ContentSectionRead[FaqContent], summary="FAQ")
async def get_faq(session: SessionDep, _: ContentEditor) -> ContentSectionRead[FaqContent]:
    return await AdminContentService(session).get_section(ContentSectionKey.FAQ, FaqContent)


@router.put("/faq", response_model=ContentSectionRead[FaqContent], summary="Сохранить FAQ")
async def put_faq(
    payload: FaqContent, session: SessionDep, actor: ContentEditor
) -> ContentSectionRead[FaqContent]:
    """Список вопросов целиком; порядок в списке — порядок на сайте."""
    return await AdminContentService(session).update_section(ContentSectionKey.FAQ, payload, actor)


# --------------------------------------------------------------- реквизиты
@router.get(
    "/requisites", response_model=ContentSectionRead[RequisitesContent], summary="Реквизиты"
)
async def get_requisites(
    session: SessionDep, _: ContentEditor
) -> ContentSectionRead[RequisitesContent]:
    return await AdminContentService(session).get_section(
        ContentSectionKey.REQUISITES, RequisitesContent
    )


@router.put(
    "/requisites",
    response_model=ContentSectionRead[RequisitesContent],
    summary="Сохранить реквизиты",
)
async def put_requisites(
    payload: RequisitesContent, session: SessionDep, actor: ContentEditor
) -> ContentSectionRead[RequisitesContent]:
    return await AdminContentService(session).update_section(
        ContentSectionKey.REQUISITES, payload, actor
    )


# ------------------------------------------------------ общие настройки
@router.get(
    "/settings", response_model=ContentSectionRead[SiteSettingsContent], summary="Настройки сайта"
)
async def get_settings(
    session: SessionDep, _: ContentEditor
) -> ContentSectionRead[SiteSettingsContent]:
    return await AdminContentService(session).get_section(
        ContentSectionKey.SETTINGS, SiteSettingsContent
    )


@router.put(
    "/settings",
    response_model=ContentSectionRead[SiteSettingsContent],
    summary="Сохранить настройки сайта",
)
async def put_settings(
    payload: SiteSettingsContent, session: SessionDep, actor: ContentEditor
) -> ContentSectionRead[SiteSettingsContent]:
    return await AdminContentService(session).update_section(
        ContentSectionKey.SETTINGS, payload, actor
    )


# ------------------------------------------------------------------ услуги
@router.get("/services", response_model=ContentSectionRead[ServicesContent], summary="Услуги")
async def get_services(
    session: SessionDep, _: ContentEditor
) -> ContentSectionRead[ServicesContent]:
    return await AdminContentService(session).get_section(
        ContentSectionKey.SERVICES, ServicesContent
    )


@router.put(
    "/services", response_model=ContentSectionRead[ServicesContent], summary="Сохранить услуги"
)
async def put_services(
    payload: ServicesContent, session: SessionDep, actor: ContentEditor
) -> ContentSectionRead[ServicesContent]:
    return await AdminContentService(session).update_section(
        ContentSectionKey.SERVICES, payload, actor
    )
