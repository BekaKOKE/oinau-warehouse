"""Схемы разделов CMS — они же формат хранения в content_sections.data.

У каждого раздела фиксированный набор полей. `extra="forbid"` на всех
уровнях: неизвестное поле — ошибка, а не молча сохранённый мусор. Так
CMS остаётся структурированным и не превращается в конструктор блоков.

Локализуемые поля — словари {"ru": "..."}: русский обязателен, прочие
локали (kk) можно заполнять заранее. Изображения — UUID файлов
медиатеки; ссылка на CDN строится при выдаче, в данных её нет.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.db.types import LEN_EMAIL
from app.modules.content.enums import ContentSectionKey, SocialNetwork
from app.modules.content.fields import (
    Bik,
    Bin,
    HttpsUrl,
    Iban,
    Kbe,
    Link,
    LocalizedLine,
    LocalizedQuestion,
    LocalizedSeoText,
    LocalizedShortText,
    LocalizedText,
    PhoneNumber,
)


class ContentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -------------------------------------------------------------------- SEO


class SeoMeta(ContentModel):
    """SEO страницы. Пустое поле на странице заменяется значением
    по умолчанию из общих настроек сайта.

    Ключевых слов (meta keywords) нет: поисковые системы их не
    учитывают, а заполнять бесполезное поле никто не должен.
    """

    title: LocalizedLine | None = None
    description: LocalizedSeoText | None = None
    og_title: LocalizedLine | None = None
    og_description: LocalizedSeoText | None = None
    og_image: UUID | None = None


# ---------------------------------------------------------------- главная


class HomeHero(ContentModel):
    title: LocalizedLine
    subtitle: LocalizedShortText | None = None
    cta_label: LocalizedLine | None = None
    cta_url: Link | None = None
    image: UUID | None = None

    @model_validator(mode="after")
    def _cta_pair(self) -> HomeHero:
        if (self.cta_label is None) != (self.cta_url is None):
            raise ValueError("Текст и ссылка кнопки задаются вместе")
        return self


class HomeAdvantage(ContentModel):
    title: LocalizedLine
    text: LocalizedShortText | None = None


class HomeAbout(ContentModel):
    title: LocalizedLine | None = None
    text: LocalizedText


class HomeContent(ContentModel):
    hero: HomeHero | None = None
    advantages: list[HomeAdvantage] = Field(default_factory=list, max_length=12)
    about: HomeAbout | None = None
    seo: SeoMeta = Field(default_factory=SeoMeta)


# --------------------------------------------------------------- контакты


class ContactPhone(ContentModel):
    number: PhoneNumber
    label: LocalizedLine | None = None


class ContactEmail(ContentModel):
    email: EmailStr
    label: LocalizedLine | None = None

    @field_validator("email")
    @classmethod
    def _check_length(cls, value: str) -> str:
        if len(value) > LEN_EMAIL:
            raise ValueError(f"Email длиннее {LEN_EMAIL} символов")
        return value


class WhatsappContact(ContentModel):
    number: PhoneNumber
    # Текст, который подставляется в чат при переходе по ссылке.
    message: LocalizedShortText | None = None


class MapPoint(ContentModel):
    """Точка на карте. Код встраивания карты (iframe) не хранится:
    это произвольный HTML, а карту фронтенд рисует сам по координатам."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ContactsContent(ContentModel):
    # Первый номер — основной: он же выводится в шапке сайта.
    phones: list[ContactPhone] = Field(default_factory=list, max_length=10)
    emails: list[ContactEmail] = Field(default_factory=list, max_length=10)
    whatsapp: WhatsappContact | None = None
    address: LocalizedShortText | None = None
    working_hours: LocalizedShortText | None = None
    map: MapPoint | None = None
    seo: SeoMeta = Field(default_factory=SeoMeta)


# ---------------------------------------------------------------- доставка


class DeliveryMethod(ContentModel):
    title: LocalizedLine
    text: LocalizedText | None = None


class DeliveryContent(ContentModel):
    intro: LocalizedText | None = None
    methods: list[DeliveryMethod] = Field(default_factory=list, max_length=20)
    payment: LocalizedText | None = None
    seo: SeoMeta = Field(default_factory=SeoMeta)


# --------------------------------------------------------------------- FAQ


class FaqItem(ContentModel):
    question: LocalizedQuestion
    answer: LocalizedText


class FaqContent(ContentModel):
    # Порядок вопросов — порядок в списке.
    items: list[FaqItem] = Field(default_factory=list, max_length=100)
    seo: SeoMeta = Field(default_factory=SeoMeta)


# ------------------------------------------------------------------ услуги

# Якорь услуги на странице (/services#obzhimka-kanatov) и ключ в React.
ServiceSlug = Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[a-z0-9-]+$")]


class ServiceItem(ContentModel):
    """Услуга: обжимка и обрезка канатов, металлорезка и т. п.

    Структура, а не произвольный текст: страница услуг — такой же
    строгий B2B-каталог, как товары. «Что делаем» — короткий список,
    каждая строка — одна операция или условие.
    """

    slug: ServiceSlug
    title: LocalizedLine
    summary: LocalizedShortText | None = None
    details: list[LocalizedLine] = Field(default_factory=list, max_length=20)
    # «от 500 ₸ за обжимку», «срок — 1 рабочий день». Цена услуги в CMS —
    # текст: она зависит от объёма и считается менеджером.
    price_note: LocalizedLine | None = None
    image: UUID | None = None
    cta_label: LocalizedLine | None = None


class ServicesContent(ContentModel):
    intro: LocalizedText | None = None
    items: list[ServiceItem] = Field(default_factory=list, max_length=30)
    seo: SeoMeta = Field(default_factory=SeoMeta)

    @field_validator("items")
    @classmethod
    def _unique_slugs(cls, value: list[ServiceItem]) -> list[ServiceItem]:
        slugs = [item.slug for item in value]
        if len(slugs) != len(set(slugs)):
            raise ValueError("Адрес (slug) каждой услуги должен быть уникальным")
        return value


# --------------------------------------------------------------- реквизиты


class RequisitesContent(ContentModel):
    company_name: LocalizedLine | None = None
    bin: Bin | None = None
    iban: Iban | None = None
    bank_name: LocalizedLine | None = None
    bik: Bik | None = None
    kbe: Kbe | None = None
    legal_address: LocalizedShortText | None = None


# ------------------------------------------------------ общие настройки


class SocialLink(ContentModel):
    network: SocialNetwork
    url: HttpsUrl


class SiteSettingsContent(ContentModel):
    site_name: LocalizedLine | None = None
    # SEO по умолчанию: подставляется на страницах, где своё не задано.
    seo: SeoMeta = Field(default_factory=SeoMeta)
    social_links: list[SocialLink] = Field(default_factory=list, max_length=10)

    @field_validator("social_links")
    @classmethod
    def _unique_networks(cls, value: list[SocialLink]) -> list[SocialLink]:
        networks = [item.network for item in value]
        if len(networks) != len(set(networks)):
            raise ValueError("Каждая соцсеть указывается один раз")
        return value


# ----------------------------------------------------------------- реестр

SECTION_SCHEMAS: dict[ContentSectionKey, type[ContentModel]] = {
    ContentSectionKey.HOME: HomeContent,
    ContentSectionKey.CONTACTS: ContactsContent,
    ContentSectionKey.DELIVERY: DeliveryContent,
    ContentSectionKey.FAQ: FaqContent,
    ContentSectionKey.REQUISITES: RequisitesContent,
    ContentSectionKey.SETTINGS: SiteSettingsContent,
    ContentSectionKey.SERVICES: ServicesContent,
}


def collect_media_refs(value: Any) -> set[UUID]:
    """Все UUID файлов медиатеки, упомянутые в разделе.

    В схемах контента тип UUID используется только для ссылок на
    медиатеку, поэтому достаточно собрать все значения этого типа.
    """
    if isinstance(value, UUID):
        return {value}
    if isinstance(value, BaseModel):
        refs: set[UUID] = set()
        for name in type(value).model_fields:
            refs |= collect_media_refs(getattr(value, name))
        return refs
    if isinstance(value, list | tuple):
        return set().union(*(collect_media_refs(item) for item in value)) if value else set()
    return set()


# ----------------------------------------------------------- ответы админки


class ContentSectionRead[DataT: ContentModel](BaseModel):
    key: ContentSectionKey
    data: DataT
    # false — раздел ещё ни разу не сохраняли, `data` — пустые значения.
    is_configured: bool
    updated_at: datetime | None = None
    updated_by_id: int | None = None


class ContentSectionSummary(BaseModel):
    key: ContentSectionKey
    is_configured: bool
    updated_at: datetime | None = None
    updated_by_id: int | None = None
