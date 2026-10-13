"""Публичные ответы CMS.

Только готовые к выводу значения на запрошенном языке. Нет ни UUID
файлов, ни ключей объектов в хранилище, ни автора и времени правки:
изображения приходят готовыми ссылками CDN, тексты — строками.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.content.enums import SocialNetwork


class PublicImage(BaseModel):
    url: str
    width: int | None = None
    height: int | None = None
    variants: dict[str, str] = Field(default_factory=dict)


class PublicSeo(BaseModel):
    """Итоговые мета-теги страницы: своё значение страницы, иначе —
    значение по умолчанию из общих настроек."""

    title: str | None = None
    description: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    og_image: PublicImage | None = None


# ---------------------------------------------------------------- главная


class PublicHero(BaseModel):
    title: str
    subtitle: str | None = None
    cta_label: str | None = None
    cta_url: str | None = None
    image: PublicImage | None = None


class PublicAdvantage(BaseModel):
    title: str
    text: str | None = None


class PublicAbout(BaseModel):
    title: str | None = None
    text: str


class PublicHome(BaseModel):
    hero: PublicHero | None = None
    advantages: list[PublicAdvantage] = Field(default_factory=list)
    about: PublicAbout | None = None
    seo: PublicSeo


# --------------------------------------------------------------- контакты


class PublicPhone(BaseModel):
    label: str | None = None
    display: str
    # Готовое значение для href="tel:...".
    tel: str


class PublicEmail(BaseModel):
    label: str | None = None
    email: str


class PublicWhatsapp(BaseModel):
    display: str
    # Готовая ссылка https://wa.me/... с текстом сообщения.
    url: str


class PublicMapPoint(BaseModel):
    latitude: float
    longitude: float


class PublicRequisites(BaseModel):
    company_name: str | None = None
    bin: str | None = None
    iban: str | None = None
    bank_name: str | None = None
    bik: str | None = None
    kbe: str | None = None
    legal_address: str | None = None


class PublicContacts(BaseModel):
    phones: list[PublicPhone] = Field(default_factory=list)
    emails: list[PublicEmail] = Field(default_factory=list)
    whatsapp: PublicWhatsapp | None = None
    address: str | None = None
    working_hours: str | None = None
    map: PublicMapPoint | None = None
    requisites: PublicRequisites | None = None
    seo: PublicSeo


# ---------------------------------------------------------------- доставка


class PublicDeliveryMethod(BaseModel):
    title: str
    text: str | None = None


class PublicDelivery(BaseModel):
    intro: str | None = None
    methods: list[PublicDeliveryMethod] = Field(default_factory=list)
    payment: str | None = None
    seo: PublicSeo


# --------------------------------------------------------------------- FAQ


class PublicFaqItem(BaseModel):
    question: str
    answer: str


class PublicFaq(BaseModel):
    items: list[PublicFaqItem] = Field(default_factory=list)
    seo: PublicSeo


# ------------------------------------------------------ общие настройки


class PublicService(BaseModel):
    slug: str
    title: str
    summary: str | None = None
    details: list[str] = Field(default_factory=list)
    price_note: str | None = None
    image: PublicImage | None = None
    cta_label: str | None = None


class PublicServices(BaseModel):
    intro: str | None = None
    items: list[PublicService] = Field(default_factory=list)
    seo: PublicSeo


class PublicSocialLink(BaseModel):
    network: SocialNetwork
    url: str


class PublicSiteSettings(BaseModel):
    """Данные для шапки и подвала — один запрос на всё оформление сайта."""

    site_name: str | None = None
    seo: PublicSeo
    social_links: list[PublicSocialLink] = Field(default_factory=list)
    phone: PublicPhone | None = None
    email: PublicEmail | None = None
    whatsapp: PublicWhatsapp | None = None
