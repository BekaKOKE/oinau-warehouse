"""Интеграционные тесты структурированного CMS: admin и публичный API."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.modules.audit.models import AuditLog
from app.modules.media.enums import MediaStatus
from app.modules.users.enums import UserRole
from tests.conftest import Headers
from tests.helpers import count_queries
from tests.media_helpers import make_media

ADMIN = "/api/v1/admin/content"
PUBLIC = "/api/v1/public/content"

SECTIONS = ["home", "contacts", "delivery", "faq", "requisites", "settings", "services"]
PUBLIC_SECTIONS = ["home", "contacts", "delivery", "faq", "settings", "services"]

VALID_IBAN = "KZ86125KZT5004100100"

HOME = {
    "hero": {
        "title": {"ru": "Комплектующие для детских площадок"},
        "subtitle": {"ru": "Канаты, крепления и сиденья\nот производителя"},
        "cta_label": {"ru": "Перейти в каталог"},
        "cta_url": "/catalog",
    },
    "advantages": [
        {"title": {"ru": "Склад в Алматы"}, "text": {"ru": "Отгрузка в день заявки"}},
        {"title": {"ru": "Сертификаты"}},
    ],
    "about": {"title": {"ru": "О компании"}, "text": {"ru": "Работаем с 2012 года."}},
    "seo": {
        "title": {"ru": "OINAU-PRO — комплектующие"},
        "description": {"ru": "Оптом и в розницу"},
    },
}

CONTACTS = {
    "phones": [
        {"number": "+7 (701) 123-45-67", "label": {"ru": "Отдел продаж"}},
        {"number": "8 727 300 00 00"},
    ],
    "emails": [{"email": "sales@oinau-pro.kz", "label": {"ru": "Заявки"}}],
    "whatsapp": {"number": "+7 701 123 45 67", "message": {"ru": "Здравствуйте! Вопрос по товару"}},
    "address": {"ru": "г. Алматы, ул. Примерная, 1"},
    "working_hours": {"ru": "Пн–Пт 9:00–18:00\nСб 10:00–15:00"},
    "map": {"latitude": 43.238949, "longitude": 76.889709},
}

REQUISITES = {
    "company_name": {"ru": "ТОО «OINAU-PRO»"},
    "bin": "123456789012",
    "iban": "kz86 125k zt50 0410 0100",
    "bank_name": {"ru": "АО «Банк»"},
    "bik": "hsbkkzkx",
    "kbe": "17",
    "legal_address": {"ru": "г. Алматы, ул. Примерная, 1"},
}

SETTINGS = {
    "site_name": {"ru": "OINAU-PRO"},
    "seo": {
        "title": {"ru": "OINAU-PRO"},
        "description": {"ru": "Комплектующие для площадок"},
    },
    "social_links": [
        {"network": "INSTAGRAM", "url": "https://instagram.com/oinau"},
        {"network": "TELEGRAM", "url": "https://t.me/oinau"},
    ],
}

DELIVERY = {
    "intro": {"ru": "Доставляем по всему Казахстану."},
    "methods": [
        {"title": {"ru": "Самовывоз"}, "text": {"ru": "Со склада в Алматы"}},
        {"title": {"ru": "Транспортная компания"}},
    ],
    "payment": {"ru": "Безналичный расчёт для юрлиц."},
}


def faq(count: int) -> dict[str, Any]:
    return {
        "items": [
            {"question": {"ru": f"Вопрос {index}?"}, "answer": {"ru": f"Ответ {index}."}}
            for index in range(count)
        ]
    }


async def section_audit(engine: AsyncEngine) -> list[AuditLog]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        rows = await session.execute(
            select(AuditLog).where(AuditLog.entity_type == "content_section").order_by(AuditLog.id)
        )
        return list(rows.scalars().all())


# ============================================================ admin: чтение
async def test_unconfigured_sections_return_empty_documents(
    api: AsyncClient, admin: Headers
) -> None:
    summary = (await api.get(ADMIN, headers=admin)).json()
    assert [item["key"] for item in summary] == SECTIONS
    assert all(item["is_configured"] is False for item in summary)

    home = (await api.get(f"{ADMIN}/home", headers=admin)).json()
    assert home["key"] == "home"
    assert home["is_configured"] is False
    assert home["updated_at"] is None
    assert home["data"]["hero"] is None
    assert home["data"]["advantages"] == []


async def test_public_sections_are_empty_before_first_save(api: AsyncClient) -> None:
    """Пустой контент — не 404: фронтенд рисует страницу с заглушками."""
    for key in PUBLIC_SECTIONS:
        response = await api.get(f"{PUBLIC}/{key}")
        assert response.status_code == 200, key

    home = (await api.get(f"{PUBLIC}/home")).json()
    assert home["hero"] is None
    assert home["seo"]["title"] is None
    assert (await api.get(f"{PUBLIC}/contacts")).json()["requisites"] is None


# =========================================================== admin: запись
async def test_save_and_read_home(api: AsyncClient, admin: Headers, login_as) -> None:
    response = await api.put(f"{ADMIN}/home", headers=admin, json=HOME)
    assert response.status_code == 200

    body = response.json()
    assert body["is_configured"] is True
    assert body["updated_at"] is not None
    assert body["updated_by_id"] is not None
    assert body["data"]["hero"]["title"] == {"ru": "Комплектующие для детских площадок"}
    assert body["data"]["advantages"][1]["text"] is None

    again = (await api.get(f"{ADMIN}/home", headers=admin)).json()
    assert again["data"] == body["data"]

    summary = {item["key"]: item for item in (await api.get(ADMIN, headers=admin)).json()}
    assert summary["home"]["is_configured"] is True
    assert summary["faq"]["is_configured"] is False


async def test_put_replaces_whole_document(api: AsyncClient, admin: Headers) -> None:
    await api.put(f"{ADMIN}/home", headers=admin, json=HOME)
    response = await api.put(
        f"{ADMIN}/home", headers=admin, json={"hero": {"title": {"ru": "Новый заголовок"}}}
    )
    data = response.json()["data"]
    assert data["hero"]["subtitle"] is None
    assert data["advantages"] == []
    assert data["about"] is None


async def test_all_sections_roundtrip(api: AsyncClient, admin: Headers) -> None:
    payloads = {
        "home": HOME,
        "contacts": CONTACTS,
        "delivery": DELIVERY,
        "faq": faq(3),
        "requisites": REQUISITES,
        "settings": SETTINGS,
    }
    for key, payload in payloads.items():
        response = await api.put(f"{ADMIN}/{key}", headers=admin, json=payload)
        assert response.status_code == 200, (key, response.text)

    requisites = (await api.get(f"{ADMIN}/requisites", headers=admin)).json()["data"]
    # Реквизиты нормализуются: без пробелов, в верхнем регистре.
    assert requisites["iban"] == VALID_IBAN
    assert requisites["bik"] == "HSBKKZKX"


# ============================================================== валидация
def _home_with(**hero: Any) -> dict[str, Any]:
    return {"hero": {"title": {"ru": "Заголовок"}, **hero}}


@pytest.mark.parametrize(
    ("key", "payload"),
    [
        # HTML и скрипты — простой текст не допускает разметки
        ("home", _home_with(subtitle={"ru": "<script>alert(1)</script>"})),
        ("home", _home_with(subtitle={"ru": "Текст <b>жирный</b>"})),
        ("home", _home_with(subtitle={"ru": "<!-- комментарий -->"})),
        ("faq", {"items": [{"question": {"ru": "Как?"}, "answer": {"ru": "<a href=x>тут</a>"}}]}),
        # управляющие символы и подмена направления текста
        ("home", _home_with(subtitle={"ru": "abc\x00def"})),
        ("home", _home_with(subtitle={"ru": "abc‮def"})),
        # русская версия обязательна
        ("home", {"hero": {"title": {"kk": "Тек қазақша"}}}),
        ("home", {"hero": {"title": {"ru": "   "}}}),
        ("home", {"hero": {"title": {"russian": "Заголовок"}}}),
        # однострочное поле
        ("home", {"hero": {"title": {"ru": "две\nстроки"}}}),
        # длина
        ("home", {"hero": {"title": {"ru": "x" * 256}}}),
        ("faq", {"items": [{"question": {"ru": "?"}, "answer": {"ru": "x" * 5001}}]}),
        # ссылки
        ("home", _home_with(cta_label={"ru": "Жми"}, cta_url="javascript:alert(1)")),
        ("home", _home_with(cta_label={"ru": "Жми"}, cta_url="//evil.example")),
        ("home", _home_with(cta_label={"ru": "Жми"}, cta_url="data:text/html,x")),
        ("home", _home_with(cta_label={"ru": "Жми"}, cta_url="https://user:pw@evil.example")),
        ("home", _home_with(cta_label={"ru": "Жми"})),  # кнопка без ссылки
        ("settings", {"social_links": [{"network": "INSTAGRAM", "url": "http://insta.example"}]}),
        (
            "settings",
            {
                "social_links": [
                    {"network": "TELEGRAM", "url": "https://t.me/a"},
                    {"network": "TELEGRAM", "url": "https://t.me/b"},
                ]
            },
        ),
        # структура: неизвестные поля и произвольные блоки не принимаются
        ("home", {"blocks": [{"type": "html", "html": "<div/>"}]}),
        ("home", {"hero": {"title": {"ru": "Заголовок"}, "css": "body{}"}}),
        ("faq", faq(101)),
        # контакты и реквизиты
        ("contacts", {"phones": [{"number": "позвоните нам"}]}),
        ("contacts", {"emails": [{"email": "not-an-email"}]}),
        ("contacts", {"map": {"latitude": 91, "longitude": 0}}),
        ("requisites", {"iban": "KZ87125KZT5004100100"}),  # контрольная сумма
        ("requisites", {"bin": "12345"}),
        ("requisites", {"kbe": "1A"}),
    ],
)
async def test_validation(
    api: AsyncClient, admin: Headers, key: str, payload: dict[str, Any]
) -> None:
    response = await api.put(f"{ADMIN}/{key}", headers=admin, json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"


async def test_rejected_payload_changes_nothing(api: AsyncClient, admin: Headers) -> None:
    await api.put(f"{ADMIN}/home", headers=admin, json=HOME)
    await api.put(f"{ADMIN}/home", headers=admin, json=_home_with(subtitle={"ru": "<i>x</i>"}))
    data = (await api.get(f"{ADMIN}/home", headers=admin)).json()["data"]
    assert data["hero"]["subtitle"] == HOME["hero"]["subtitle"]


async def test_text_is_normalized(api: AsyncClient, admin: Headers) -> None:
    """Пробелы по краям срезаются, \\r\\n приводится к \\n, пустые локали отбрасываются,
    а знаки «меньше/больше» в обычном тексте допустимы."""
    response = await api.put(
        f"{ADMIN}/home",
        headers=admin,
        json=_home_with(subtitle={"ru": "  Диаметр < 16 мм\r\nи > 10 мм  ", "kk": " "}),
    )
    assert response.status_code == 200
    assert response.json()["data"]["hero"]["subtitle"] == {"ru": "Диаметр < 16 мм\nи > 10 мм"}


# ============================================================ изображения
async def test_content_image_references(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    ready = await make_media(committed_session)
    processing = await make_media(committed_session, status=MediaStatus.PROCESSING)
    failed = await make_media(committed_session, status=MediaStatus.FAILED)
    await committed_session.commit()

    unknown = await api.put(
        f"{ADMIN}/home",
        headers=admin,
        json=_home_with(image="00000000-0000-0000-0000-000000000000"),
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "media_not_found"

    rejected = await api.put(
        f"{ADMIN}/home", headers=admin, json=_home_with(image=str(failed.uuid))
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "media_failed"

    # Неготовый файл сохранить можно — витрина покажет его после обработки.
    saved = await api.put(
        f"{ADMIN}/home",
        headers=admin,
        json={**_home_with(image=str(processing.uuid)), "seo": {"og_image": str(ready.uuid)}},
    )
    assert saved.status_code == 200

    public = (await api.get(f"{PUBLIC}/home")).json()
    assert public["hero"]["image"] is None
    og_image = public["seo"]["og_image"]
    cdn = settings.CDN_BASE_URL.rstrip("/")
    assert og_image["url"] == f"{cdn}/products/{ready.uuid}/variants/large.webp"
    assert (og_image["width"], og_image["height"]) == (64, 48)
    assert str(processing.uuid) not in str(public)


# ============================================================== публичный
async def test_public_home(api: AsyncClient, admin: Headers) -> None:
    await api.put(f"{ADMIN}/home", headers=admin, json=HOME)
    response = await api.get(f"{PUBLIC}/home")
    assert response.status_code == 200

    body = response.json()
    assert body["hero"] == {
        "title": "Комплектующие для детских площадок",
        "subtitle": "Канаты, крепления и сиденья\nот производителя",
        "cta_label": "Перейти в каталог",
        "cta_url": "/catalog",
        "image": None,
    }
    assert [item["title"] for item in body["advantages"]] == ["Склад в Алматы", "Сертификаты"]
    assert body["about"] == {"title": "О компании", "text": "Работаем с 2012 года."}
    assert body["seo"]["title"] == "OINAU-PRO — комплектующие"
    # og-поля без собственного значения берут обычные заголовок и описание
    assert body["seo"]["og_title"] == "OINAU-PRO — комплектующие"
    assert body["seo"]["og_description"] == "Оптом и в розницу"


async def test_public_responses_have_no_internal_fields(api: AsyncClient, admin: Headers) -> None:
    for key, payload in [("home", HOME), ("contacts", CONTACTS), ("settings", SETTINGS)]:
        await api.put(f"{ADMIN}/{key}", headers=admin, json=payload)

    for key in PUBLIC_SECTIONS:
        text = (await api.get(f"{PUBLIC}/{key}")).text
        for internal in ("updated_by", "updated_at", "is_configured", "storage_key", '"id"'):
            assert internal not in text, (key, internal)
        # Локализованные словари разворачиваются в строки
        assert '"ru"' not in text, key


async def test_public_contacts_with_requisites(api: AsyncClient, admin: Headers) -> None:
    await api.put(f"{ADMIN}/contacts", headers=admin, json=CONTACTS)
    await api.put(f"{ADMIN}/requisites", headers=admin, json=REQUISITES)

    body = (await api.get(f"{PUBLIC}/contacts")).json()
    assert body["phones"] == [
        {"label": "Отдел продаж", "display": "+7 (701) 123-45-67", "tel": "+77011234567"},
        {"label": None, "display": "8 727 300 00 00", "tel": "87273000000"},
    ]
    assert body["emails"] == [{"label": "Заявки", "email": "sales@oinau-pro.kz"}]
    assert body["whatsapp"]["display"] == "+7 701 123 45 67"
    assert body["whatsapp"]["url"].startswith("https://wa.me/77011234567?text=")
    assert " " not in body["whatsapp"]["url"]
    assert body["working_hours"] == "Пн–Пт 9:00–18:00\nСб 10:00–15:00"
    assert body["map"] == {"latitude": 43.238949, "longitude": 76.889709}
    assert body["requisites"]["iban"] == VALID_IBAN
    assert body["requisites"]["company_name"] == "ТОО «OINAU-PRO»"


async def test_public_delivery_and_faq_order(api: AsyncClient, admin: Headers) -> None:
    await api.put(f"{ADMIN}/delivery", headers=admin, json=DELIVERY)
    await api.put(f"{ADMIN}/faq", headers=admin, json=faq(3))

    delivery = (await api.get(f"{PUBLIC}/delivery")).json()
    assert [item["title"] for item in delivery["methods"]] == ["Самовывоз", "Транспортная компания"]
    assert delivery["payment"] == "Безналичный расчёт для юрлиц."

    items = (await api.get(f"{PUBLIC}/faq")).json()["items"]
    assert [item["question"] for item in items] == ["Вопрос 0?", "Вопрос 1?", "Вопрос 2?"]


async def test_public_settings_for_layout(api: AsyncClient, admin: Headers) -> None:
    await api.put(f"{ADMIN}/settings", headers=admin, json=SETTINGS)
    await api.put(f"{ADMIN}/contacts", headers=admin, json=CONTACTS)

    body = (await api.get(f"{PUBLIC}/settings")).json()
    assert body["site_name"] == "OINAU-PRO"
    assert body["seo"]["title"] == "OINAU-PRO"
    assert body["social_links"] == SETTINGS["social_links"]
    # Основной телефон и email — первые из раздела контактов
    assert body["phone"]["tel"] == "+77011234567"
    assert body["email"]["email"] == "sales@oinau-pro.kz"
    assert body["whatsapp"]["url"].startswith("https://wa.me/")


async def test_page_seo_falls_back_to_site_defaults(api: AsyncClient, admin: Headers) -> None:
    await api.put(f"{ADMIN}/settings", headers=admin, json=SETTINGS)
    await api.put(
        f"{ADMIN}/faq",
        headers=admin,
        json={**faq(1), "seo": {"title": {"ru": "Вопросы и ответы"}}},
    )

    seo = (await api.get(f"{PUBLIC}/faq")).json()["seo"]
    assert seo["title"] == "Вопросы и ответы"
    assert seo["description"] == "Комплектующие для площадок"  # из общих настроек
    assert seo["og_title"] == "Вопросы и ответы"

    delivery_seo = (await api.get(f"{PUBLIC}/delivery")).json()["seo"]
    assert delivery_seo["title"] == "OINAU-PRO"


# ============================================================ локализация
async def test_kazakh_can_be_prepared_before_enabling(
    api: AsyncClient, admin: Headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    """kk хранится заранее, но на сайт выходит только после включения языка.
    Поля без перевода показываются по-русски."""
    payload = {
        "hero": {
            "title": {"ru": "Комплектующие", "kk": "Жинақтаушы бөлшектер"},
            "subtitle": {"ru": "Только по-русски"},
        }
    }
    assert (await api.put(f"{ADMIN}/home", headers=admin, json=payload)).status_code == 200

    hidden = (await api.get(f"{PUBLIC}/home", params={"locale": "kk"})).json()
    assert hidden["hero"]["title"] == "Комплектующие"

    monkeypatch.setattr(settings, "SUPPORTED_LOCALES", ["ru", "kk"])
    kk = (await api.get(f"{PUBLIC}/home", params={"locale": "kk"})).json()
    assert kk["hero"]["title"] == "Жинақтаушы бөлшектер"
    assert kk["hero"]["subtitle"] == "Только по-русски"

    ru = (await api.get(f"{PUBLIC}/home", params={"locale": "ru"})).json()
    assert ru["hero"]["title"] == "Комплектующие"


async def test_unsupported_locale_falls_back_to_ru(api: AsyncClient, admin: Headers) -> None:
    await api.put(f"{ADMIN}/faq", headers=admin, json=faq(1))
    body = (await api.get(f"{PUBLIC}/faq", params={"locale": "en"})).json()
    assert body["items"][0]["question"] == "Вопрос 0?"


# ================================================================== аудит
async def test_updates_are_audited(
    api: AsyncClient, admin: Headers, test_engine: AsyncEngine
) -> None:
    await api.put(f"{ADMIN}/requisites", headers=admin, json=REQUISITES)
    await api.put(f"{ADMIN}/requisites", headers=admin, json=REQUISITES)  # без изменений
    changed = {**REQUISITES, "iban": "KZ86 125K ZT50 0410 0100", "kbe": "19"}
    await api.put(f"{ADMIN}/requisites", headers=admin, json=changed)

    entries = await section_audit(test_engine)
    assert [entry.action for entry in entries] == [
        "content.section_updated",
        "content.section_updated",
    ]
    first, second = entries
    assert first.changes["section"] == "requisites"
    assert first.changes["created"] is True
    assert first.user_id is not None
    # Вторая запись — только изменившееся поле, со старым и новым значением
    assert second.changes["created"] is False
    assert second.changes["kbe"] == {"old": "17", "new": "19"}
    assert "iban" not in second.changes


async def test_long_values_are_not_copied_into_audit(
    api: AsyncClient, admin: Headers, test_engine: AsyncEngine
) -> None:
    long_answer = {"items": [{"question": {"ru": "Вопрос?"}, "answer": {"ru": "а" * 5000}}]}
    await api.put(f"{ADMIN}/faq", headers=admin, json=long_answer)

    [entry] = await section_audit(test_engine)
    assert entry.changes["items"]["new"]["omitted"] is True


# ================================================================== права
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (UserRole.SUPERADMIN, 200),
        (UserRole.ADMIN, 200),
        (UserRole.CONTENT_MANAGER, 200),
        (UserRole.MANAGER, 403),
        (UserRole.VIEWER, 403),
    ],
)
async def test_permission_matrix(api: AsyncClient, login_as, role: UserRole, expected: int) -> None:
    headers = await login_as(role)
    assert (await api.get(ADMIN, headers=headers)).status_code == expected
    for key in SECTIONS:
        assert (await api.get(f"{ADMIN}/{key}", headers=headers)).status_code == expected
    assert (await api.put(f"{ADMIN}/faq", headers=headers, json=faq(1))).status_code == expected


async def test_manager_cannot_change_content(
    api: AsyncClient, admin: Headers, login_as, test_engine: AsyncEngine
) -> None:
    await api.put(f"{ADMIN}/contacts", headers=admin, json=CONTACTS)
    manager = await login_as(UserRole.MANAGER)

    response = await api.put(
        f"{ADMIN}/contacts", headers=manager, json={"phones": [{"number": "+7 700 000 00 00"}]}
    )
    assert response.status_code == 403
    assert response.json()["error"]["details"]["required"] == ["content.write"]

    phones = (await api.get(f"{PUBLIC}/contacts")).json()["phones"]
    assert phones[0]["display"] == "+7 (701) 123-45-67"
    assert len(await section_audit(test_engine)) == 1


async def test_admin_content_requires_authentication(api: AsyncClient) -> None:
    assert (await api.get(f"{ADMIN}/home")).status_code == 401
    assert (await api.put(f"{ADMIN}/home", json=HOME)).status_code == 401


# ====================================================== производительность
async def test_public_faq_has_no_n_plus_one(
    api: AsyncClient, admin: Headers, test_engine: AsyncEngine
) -> None:
    await api.put(f"{ADMIN}/faq", headers=admin, json=faq(1))
    with count_queries(test_engine) as single:
        assert (await api.get(f"{PUBLIC}/faq")).status_code == 200

    await api.put(f"{ADMIN}/faq", headers=admin, json=faq(100))
    with count_queries(test_engine) as many:
        body = (await api.get(f"{PUBLIC}/faq")).json()

    assert len(body["items"]) == 100
    assert len(many) == len(single)


async def test_public_home_images_have_no_n_plus_one(
    api: AsyncClient,
    admin: Headers,
    committed_session: AsyncSession,
    test_engine: AsyncEngine,
) -> None:
    """Изображения страницы и SEO по умолчанию — одним запросом на все."""
    media = [await make_media(committed_session) for _ in range(3)]
    await committed_session.commit()

    await api.put(f"{ADMIN}/home", headers=admin, json=_home_with(image=str(media[0].uuid)))
    with count_queries(test_engine) as single:
        assert (await api.get(f"{PUBLIC}/home")).status_code == 200

    await api.put(
        f"{ADMIN}/settings", headers=admin, json={"seo": {"og_image": str(media[2].uuid)}}
    )
    await api.put(
        f"{ADMIN}/home",
        headers=admin,
        json={**_home_with(image=str(media[0].uuid)), "seo": {"og_image": str(media[1].uuid)}},
    )
    with count_queries(test_engine) as many:
        body = (await api.get(f"{PUBLIC}/home")).json()

    assert body["hero"]["image"] is not None
    assert body["seo"]["og_image"]["url"].endswith(f"{media[1].uuid}/variants/large.webp")
    assert len(many) == len(single)
