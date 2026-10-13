"""Раздел CMS «Услуги» и данные таблицы товаров раздела на витрине."""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import (
    Attribute,
    AttributeOption,
    CategoryAttribute,
    ProductAttributeValue,
)
from app.modules.users.enums import UserRole
from tests.conftest import Headers

ADMIN_SERVICES = "/api/v1/admin/content/services"
PUBLIC_SERVICES = "/api/v1/public/content/services"
PUBLIC_PRODUCTS = "/api/v1/public/products"

SERVICES = {
    "intro": {"ru": "Готовим комплектующие под проект."},
    "items": [
        {
            "slug": "obzhimka-kanatov",
            "title": {"ru": "Обжимка канатов"},
            "summary": {"ru": "Опрессовка втулками."},
            "details": [{"ru": "Алюминиевые втулки"}, {"ru": "Канат 16 мм"}],
            "price_note": {"ru": "По объёму партии"},
            "cta_label": {"ru": "Заказать обжимку"},
        },
        {"slug": "metallorezka", "title": {"ru": "Металлорезка"}},
    ],
    "seo": {"title": {"ru": "Услуги"}},
}


# ================================================================ услуги
async def test_services_are_managed_in_cms(api: AsyncClient, admin: Headers) -> None:
    empty = await api.get(PUBLIC_SERVICES)
    assert empty.status_code == 200
    assert empty.json()["items"] == []

    saved = await api.put(ADMIN_SERVICES, headers=admin, json=SERVICES)
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_configured"] is True

    body = (await api.get(PUBLIC_SERVICES)).json()
    assert body["intro"] == "Готовим комплектующие под проект."
    assert [item["slug"] for item in body["items"]] == ["obzhimka-kanatov", "metallorezka"]
    first = body["items"][0]
    assert first["title"] == "Обжимка канатов"
    assert first["details"] == ["Алюминиевые втулки", "Канат 16 мм"]
    assert first["price_note"] == "По объёму партии"
    assert first["cta_label"] == "Заказать обжимку"
    assert body["seo"]["title"] == "Услуги"


async def test_services_validation(api: AsyncClient, admin: Headers) -> None:
    duplicate = {**SERVICES, "items": [SERVICES["items"][1], SERVICES["items"][1]]}
    assert (await api.put(ADMIN_SERVICES, headers=admin, json=duplicate)).status_code == 422
    bad_slug = {"items": [{"slug": "Обжимка", "title": {"ru": "X"}}]}
    assert (await api.put(ADMIN_SERVICES, headers=admin, json=bad_slug)).status_code == 422
    html = {"items": [{"slug": "x", "title": {"ru": "<script>alert(1)</script>"}}]}
    assert (await api.put(ADMIN_SERVICES, headers=admin, json=html)).status_code == 422


async def test_services_require_content_permission(api: AsyncClient, login_as) -> None:
    headers = await login_as(UserRole.MANAGER)
    assert (await api.put(ADMIN_SERVICES, headers=headers, json=SERVICES)).status_code == 403


# ===================================================== таблица товаров раздела
async def test_list_items_carry_tiers_characteristics_and_specs(api: AsyncClient, catalog) -> None:
    body = (await api.get(PUBLIC_PRODUCTS, params={"category": "kanaty"})).json()
    [rope] = [item for item in body["items"] if item["sku"] == "KAN-16-PP"]
    assert [tier["min_quantity"] for tier in rope["price"]["tiers"]] == [
        "1.000",
        "10.000",
        "50.000",
        "100.000",
    ]
    # Дилерская цена в список не попадает
    assert "1111.00" not in [tier["price"] for tier in rope["price"]["tiers"]]
    names = {item["name"]: item["value"] for item in rope["characteristics"]}
    assert names["Диаметр"] == "16 мм"
    assert names["Материал"] == "Полипропилен"
    assert "Служебная пометка" not in names
    assert rope["specs"] == {"Страна": "Казахстан"}
    assert Decimal(rope["min_order_qty"]) == Decimal("1")


async def test_sort_by_sku(api: AsyncClient, catalog) -> None:
    body = (await api.get(PUBLIC_PRODUCTS, params={"sort": "sku"})).json()
    skus = [item["sku"] for item in body["items"]]
    assert skus == sorted(skus)


async def test_attribute_filter_and_facets(
    api: AsyncClient, catalog, committed_session: AsyncSession
) -> None:
    color = Attribute(
        code="color", name_i18n={"ru": "Цвет"}, value_type="OPTION", is_filterable=True
    )
    committed_session.add(color)
    await committed_session.flush()
    black = AttributeOption(attribute_id=color.id, slug="black", value_i18n={"ru": "Чёрный"})
    red = AttributeOption(attribute_id=color.id, slug="red", value_i18n={"ru": "Красный"})
    committed_session.add_all([black, red])
    await committed_session.flush()
    fastener = catalog.products["fastener"]
    seat = catalog.products["seat"]
    committed_session.add_all(
        [
            ProductAttributeValue(
                product_id=fastener.id, attribute_id=color.id, option_id=black.id
            ),
            ProductAttributeValue(product_id=seat.id, attribute_id=color.id, option_id=red.id),
            CategoryAttribute(
                category_id=catalog.categories["fasteners"].id, attribute_id=color.id
            ),
        ]
    )
    await committed_session.commit()

    only_black = (
        await api.get(PUBLIC_PRODUCTS, params={"category": "krepleniya", "attr": "color:black"})
    ).json()
    assert [item["sku"] for item in only_black["items"]] == ["KRP-M10"]

    both = (
        await api.get(
            PUBLIC_PRODUCTS,
            params=[("category", "krepleniya"), ("attr", "color:black"), ("attr", "color:red")],
        )
    ).json()
    assert {item["sku"] for item in both["items"]} == {"KRP-M10", "SID-01"}

    # Характеристика, которой нет у товаров, — пустая выдача, а не ошибка
    none = (await api.get(PUBLIC_PRODUCTS, params={"attr": "material:black"})).json()
    assert none["total"] == 0

    bad = await api.get(PUBLIC_PRODUCTS, params={"attr": "color;drop table"})
    assert bad.status_code == 422

    facets = (await api.get("/api/v1/public/categories/krepleniya/facets")).json()
    [facet] = [item for item in facets if item["code"] == "color"]
    assert facet["name"] == "Цвет"
    assert [(option["slug"], option["name"], option["count"]) for option in facet["options"]] == [
        ("black", "Чёрный", 1),
        ("red", "Красный", 1),
    ]
    missing = await api.get("/api/v1/public/categories/net-takoj/facets")
    assert missing.status_code == 404
