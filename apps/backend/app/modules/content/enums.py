"""Перечисления CMS."""

from __future__ import annotations

from enum import StrEnum


class ContentSectionKey(StrEnum):
    """Фиксированный набор разделов контента.

    Новый раздел — это новое значение здесь, схема данных в
    schemas_admin.py и эндпоинты. Произвольных «страниц» и «блоков»
    нет намеренно: CMS структурированный, а не конструктор.

    Значения в нижнем регистре: они же служат сегментом URL.
    """

    HOME = "home"
    CONTACTS = "contacts"
    DELIVERY = "delivery"
    FAQ = "faq"
    REQUISITES = "requisites"
    SETTINGS = "settings"
    SERVICES = "services"


class SocialNetwork(StrEnum):
    INSTAGRAM = "INSTAGRAM"
    TELEGRAM = "TELEGRAM"
    WHATSAPP = "WHATSAPP"
    FACEBOOK = "FACEBOOK"
    YOUTUBE = "YOUTUBE"
    TIKTOK = "TIKTOK"
    VK = "VK"
