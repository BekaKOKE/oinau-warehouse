"""Публичный CMS — /api/v1/public/content.

Без авторизации, только чтение. Реквизиты отдаются в составе контактов
(они выводятся на странице контактов), отдельного эндпоинта у них нет.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.modules.catalog.router_public import LocaleQuery
from app.modules.catalog.service import resolve_locale
from app.modules.content.schemas_public import (
    PublicContacts,
    PublicDelivery,
    PublicFaq,
    PublicHome,
    PublicServices,
    PublicSiteSettings,
)
from app.modules.content.service import ContentService

router = APIRouter(prefix="/content", tags=["content"])


@router.get("/home", response_model=PublicHome, summary="Главная страница")
async def get_home(session: SessionDep, locale: LocaleQuery = None) -> PublicHome:
    primary, fallback = resolve_locale(locale)
    return await ContentService(session).get_home(primary, fallback)


@router.get("/contacts", response_model=PublicContacts, summary="Контакты и реквизиты")
async def get_contacts(session: SessionDep, locale: LocaleQuery = None) -> PublicContacts:
    primary, fallback = resolve_locale(locale)
    return await ContentService(session).get_contacts(primary, fallback)


@router.get("/delivery", response_model=PublicDelivery, summary="Доставка и оплата")
async def get_delivery(session: SessionDep, locale: LocaleQuery = None) -> PublicDelivery:
    primary, fallback = resolve_locale(locale)
    return await ContentService(session).get_delivery(primary, fallback)


@router.get("/services", response_model=PublicServices, summary="Услуги")
async def get_services(session: SessionDep, locale: LocaleQuery = None) -> PublicServices:
    primary, fallback = resolve_locale(locale)
    return await ContentService(session).get_services(primary, fallback)


@router.get("/faq", response_model=PublicFaq, summary="Частые вопросы")
async def get_faq(session: SessionDep, locale: LocaleQuery = None) -> PublicFaq:
    primary, fallback = resolve_locale(locale)
    return await ContentService(session).get_faq(primary, fallback)


@router.get("/settings", response_model=PublicSiteSettings, summary="Настройки сайта")
async def get_settings(session: SessionDep, locale: LocaleQuery = None) -> PublicSiteSettings:
    """Название, SEO по умолчанию, соцсети и основные контакты — всё,
    что нужно шапке и подвалу, одним запросом."""
    primary, fallback = resolve_locale(locale)
    return await ContentService(session).get_settings(primary, fallback)
