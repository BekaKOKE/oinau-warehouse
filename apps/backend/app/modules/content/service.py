"""Сборка публичных ответов CMS.

Каждый ответ собирается фиксированным числом запросов: разделы —
одним SELECT по списку ключей, упомянутые в них изображения — одним
SELECT по списку UUID. Размер FAQ или число преимуществ на главной
на число запросов не влияют.
"""

from __future__ import annotations

import re
from urllib.parse import quote
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.service import BaseService
from app.modules.content.enums import ContentSectionKey, SocialNetwork
from app.modules.content.models import ContentSection
from app.modules.content.repository import ContentRepository
from app.modules.content.schemas_admin import (
    ContactEmail,
    ContactPhone,
    ContactsContent,
    ContentModel,
    DeliveryContent,
    FaqContent,
    HomeContent,
    RequisitesContent,
    SeoMeta,
    ServicesContent,
    SiteSettingsContent,
    WhatsappContact,
    collect_media_refs,
)
from app.modules.content.schemas_public import (
    PublicAbout,
    PublicAdvantage,
    PublicContacts,
    PublicDelivery,
    PublicDeliveryMethod,
    PublicEmail,
    PublicFaq,
    PublicFaqItem,
    PublicHero,
    PublicHome,
    PublicImage,
    PublicMapPoint,
    PublicPhone,
    PublicRequisites,
    PublicSeo,
    PublicService,
    PublicServices,
    PublicSiteSettings,
    PublicSocialLink,
    PublicWhatsapp,
)
from app.modules.content.service_admin import parse_section
from app.modules.media.models import MediaFile
from app.modules.media.urls import primary_size, primary_url, variant_urls
from app.modules.requests.schemas_public import normalize_phone


def _text(value: dict[str, str] | None, locale: str, fallback: str) -> str | None:
    """Текст на запрошенном языке, иначе — на языке по умолчанию."""
    if not value:
        return None
    return value.get(locale) or value.get(fallback)


class _Context:
    """Язык ответа и загруженные изображения — чтобы не таскать их
    через каждую функцию сборки по отдельности."""

    def __init__(self, locale: str, fallback: str, media: dict[UUID, MediaFile]) -> None:
        self.locale = locale
        self.fallback = fallback
        self.media = media

    def text(self, value: dict[str, str] | None) -> str | None:
        return _text(value, self.locale, self.fallback)

    def required_text(self, value: dict[str, str]) -> str:
        return self.text(value) or ""

    def image(self, media_uuid: UUID | None) -> PublicImage | None:
        """Только READY: ссылка на неготовый файл вела бы в 404."""
        media = self.media.get(media_uuid) if media_uuid else None
        url = primary_url(media)
        if url is None:
            return None
        width, height = primary_size(media)
        return PublicImage(url=url, width=width, height=height, variants=variant_urls(media))


class ContentService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = ContentRepository(session)

    # -------------------------------------------------------------- страницы
    async def get_home(self, locale: str, fallback: str) -> PublicHome:
        home, site, ctx = await self._load(ContentSectionKey.HOME, HomeContent, locale, fallback)
        hero = home.hero
        return PublicHome(
            hero=PublicHero(
                title=ctx.required_text(hero.title),
                subtitle=ctx.text(hero.subtitle),
                cta_label=ctx.text(hero.cta_label),
                cta_url=hero.cta_url,
                image=ctx.image(hero.image),
            )
            if hero
            else None,
            advantages=[
                PublicAdvantage(title=ctx.required_text(item.title), text=ctx.text(item.text))
                for item in home.advantages
            ],
            about=PublicAbout(
                title=ctx.text(home.about.title), text=ctx.required_text(home.about.text)
            )
            if home.about
            else None,
            seo=self._seo(home.seo, site.seo, ctx),
        )

    async def get_delivery(self, locale: str, fallback: str) -> PublicDelivery:
        delivery, site, ctx = await self._load(
            ContentSectionKey.DELIVERY, DeliveryContent, locale, fallback
        )
        return PublicDelivery(
            intro=ctx.text(delivery.intro),
            methods=[
                PublicDeliveryMethod(title=ctx.required_text(item.title), text=ctx.text(item.text))
                for item in delivery.methods
            ],
            payment=ctx.text(delivery.payment),
            seo=self._seo(delivery.seo, site.seo, ctx),
        )

    async def get_services(self, locale: str, fallback: str) -> PublicServices:
        services, site, ctx = await self._load(
            ContentSectionKey.SERVICES, ServicesContent, locale, fallback
        )
        return PublicServices(
            intro=ctx.text(services.intro),
            items=[
                PublicService(
                    slug=item.slug,
                    title=ctx.required_text(item.title),
                    summary=ctx.text(item.summary),
                    details=[
                        text for text in (ctx.text(detail) for detail in item.details) if text
                    ],
                    price_note=ctx.text(item.price_note),
                    image=ctx.image(item.image),
                    cta_label=ctx.text(item.cta_label),
                )
                for item in services.items
            ],
            seo=self._seo(services.seo, site.seo, ctx),
        )

    async def get_faq(self, locale: str, fallback: str) -> PublicFaq:
        faq, site, ctx = await self._load(ContentSectionKey.FAQ, FaqContent, locale, fallback)
        return PublicFaq(
            items=[
                PublicFaqItem(
                    question=ctx.required_text(item.question),
                    answer=ctx.required_text(item.answer),
                )
                for item in faq.items
            ],
            seo=self._seo(faq.seo, site.seo, ctx),
        )

    async def get_contacts(self, locale: str, fallback: str) -> PublicContacts:
        sections = await self._sections(
            [ContentSectionKey.CONTACTS, ContentSectionKey.REQUISITES, ContentSectionKey.SETTINGS]
        )
        contacts = parse_section(sections.get(ContentSectionKey.CONTACTS), ContactsContent)
        requisites = parse_section(sections.get(ContentSectionKey.REQUISITES), RequisitesContent)
        site = parse_section(sections.get(ContentSectionKey.SETTINGS), SiteSettingsContent)
        ctx = await self._context([contacts, site], locale, fallback)

        return PublicContacts(
            phones=[self._phone(item, ctx) for item in contacts.phones],
            emails=[self._email(item, ctx) for item in contacts.emails],
            whatsapp=self._whatsapp(contacts.whatsapp, ctx),
            address=ctx.text(contacts.address),
            working_hours=ctx.text(contacts.working_hours),
            map=PublicMapPoint(latitude=contacts.map.latitude, longitude=contacts.map.longitude)
            if contacts.map
            else None,
            requisites=self._requisites(requisites, ctx),
            seo=self._seo(contacts.seo, site.seo, ctx),
        )

    async def get_settings(self, locale: str, fallback: str) -> PublicSiteSettings:
        sections = await self._sections([ContentSectionKey.SETTINGS, ContentSectionKey.CONTACTS])
        site = parse_section(sections.get(ContentSectionKey.SETTINGS), SiteSettingsContent)
        contacts = parse_section(sections.get(ContentSectionKey.CONTACTS), ContactsContent)
        ctx = await self._context([site], locale, fallback)

        return PublicSiteSettings(
            site_name=ctx.text(site.site_name),
            seo=self._seo(site.seo, SeoMeta(), ctx),
            social_links=[
                PublicSocialLink(network=SocialNetwork(item.network), url=item.url)
                for item in site.social_links
            ],
            phone=self._phone(contacts.phones[0], ctx) if contacts.phones else None,
            email=self._email(contacts.emails[0], ctx) if contacts.emails else None,
            whatsapp=self._whatsapp(contacts.whatsapp, ctx),
        )

    # ---------------------------------------------------------- загрузка
    async def _sections(
        self, keys: list[ContentSectionKey]
    ) -> dict[ContentSectionKey, ContentSection | None]:
        stored = await self.repository.get_sections(keys)
        return {key: stored.get(key.value) for key in keys}

    async def _load[DataT: ContentModel](
        self, key: ContentSectionKey, schema: type[DataT], locale: str, fallback: str
    ) -> tuple[DataT, SiteSettingsContent, _Context]:
        """Раздел страницы вместе с общими настройками (SEO по умолчанию)."""
        sections = await self._sections([key, ContentSectionKey.SETTINGS])
        page = parse_section(sections.get(key), schema)
        site = parse_section(sections.get(ContentSectionKey.SETTINGS), SiteSettingsContent)
        return page, site, await self._context([page, site], locale, fallback)

    async def _context(self, models: list[ContentModel], locale: str, fallback: str) -> _Context:
        refs: set[UUID] = set()
        for model in models:
            refs |= collect_media_refs(model)
        media = await self.repository.get_media(sorted(refs))
        return _Context(locale, fallback, media)

    # ------------------------------------------------------------- сборка
    def _seo(self, page: SeoMeta, default: SeoMeta, ctx: _Context) -> PublicSeo:
        """Своё значение страницы, иначе — значение по умолчанию.

        Для Open Graph дополнительно действует запасной вариант
        «как у обычного заголовка/описания»: отдельно заполнять og-поля
        на каждой странице никто не станет.
        """
        title = ctx.text(page.title) or ctx.text(default.title)
        description = ctx.text(page.description) or ctx.text(default.description)
        return PublicSeo(
            title=title,
            description=description,
            og_title=ctx.text(page.og_title)
            or ctx.text(page.title)
            or ctx.text(default.og_title)
            or title,
            og_description=ctx.text(page.og_description)
            or ctx.text(page.description)
            or ctx.text(default.og_description)
            or description,
            og_image=ctx.image(page.og_image) or ctx.image(default.og_image),
        )

    def _phone(self, phone: ContactPhone, ctx: _Context) -> PublicPhone:
        return PublicPhone(
            label=ctx.text(phone.label),
            display=phone.number,
            tel=normalize_phone(phone.number),
        )

    def _email(self, email: ContactEmail, ctx: _Context) -> PublicEmail:
        return PublicEmail(label=ctx.text(email.label), email=str(email.email))

    def _whatsapp(self, whatsapp: WhatsappContact | None, ctx: _Context) -> PublicWhatsapp | None:
        """Ссылка wa.me: только цифры номера и закодированный текст."""
        if whatsapp is None:
            return None
        digits = re.sub(r"\D", "", whatsapp.number)
        url = f"https://wa.me/{digits}"
        message = ctx.text(whatsapp.message)
        if message:
            url += f"?text={quote(message, safe='')}"
        return PublicWhatsapp(display=whatsapp.number, url=url)

    def _requisites(self, requisites: RequisitesContent, ctx: _Context) -> PublicRequisites | None:
        result = PublicRequisites(
            company_name=ctx.text(requisites.company_name),
            bin=requisites.bin,
            iban=requisites.iban,
            bank_name=ctx.text(requisites.bank_name),
            bik=requisites.bik,
            kbe=requisites.kbe,
            legal_address=ctx.text(requisites.legal_address),
        )
        # Незаполненные реквизиты — отсутствие блока, а не блок из пустот.
        return result if any(result.model_dump().values()) else None
