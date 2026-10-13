"""Цвета товаров: справочник, остатки и надбавки по цветам, витрина и заявки."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.colors.models import Color, ProductColor
from app.modules.notifications.messages import build_message
from app.modules.notifications.models import NotificationOutbox
from app.modules.requests.models import RequestItem
from app.modules.users.enums import UserRole
from tests.catalog_fixtures import CatalogFixture
from tests.conftest import Headers
from tests.request_helpers import ADMIN_REQUESTS, PUBLIC_REQUESTS, request_payload

COLORS = "/api/v1/admin/colors"
PRODUCTS = "/api/v1/admin/products"
PUBLIC_PRODUCTS = "/api/v1/public/products"
QUICK = "/api/v1/public/quick-requests"

ROPE = "KAN-16-PP"  # TIERED: 1–9 → 3500, 10–49 → 3200, 50–99 → 2900, 100+ → 2600
ROPE_SLUG = "kanat-16-pp"


def colors_url(product_id: int) -> str:
    return f"{PRODUCTS}/{product_id}/colors"


@pytest.fixture(autouse=True)
async def empty_palette(committed_session: AsyncSession) -> None:
    """Миграция заполняет базовую палитру, а тесты чистят таблицы только
    после себя: первый тест увидел бы её. Каждый тест начинает с пустого
    справочника и создаёт нужные цвета сам."""
    await committed_session.execute(delete(ProductColor))
    await committed_session.execute(delete(Color))
    await committed_session.commit()


async def _color(api: AsyncClient, headers: Headers, code: str, name: str, hex_value: str) -> dict:
    response = await api.post(
        COLORS, headers=headers, json={"code": code, "name": name, "hex": hex_value}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def palette(api: AsyncClient, admin: Headers) -> dict[str, dict]:
    return {
        "black": await _color(api, admin, "black", "Чёрный", "#1F1F1F"),
        "red": await _color(api, admin, "red", "Красный", "#d32f2f"),
        "blue": await _color(api, admin, "blue", "Синий", "#1976d2"),
    }


async def _set_colors(
    api: AsyncClient, headers: Headers, product_id: int, items: list[dict[str, Any]]
) -> dict:
    response = await api.put(colors_url(product_id), headers=headers, json={"items": items})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
async def rope_colors(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, palette: dict[str, dict]
) -> dict:
    """Канат: чёрный 100 м, красный 0 м с надбавкой 200 ₸, синий 50 м."""
    return await _set_colors(
        api,
        admin,
        catalog.products["rope"].id,
        [
            {"color_id": palette["black"]["id"], "quantity": "100"},
            {"color_id": palette["red"]["id"], "quantity": "0", "price_delta": "200"},
            {"color_id": palette["blue"]["id"], "quantity": "50"},
        ],
    )


# ============================================================== справочник
async def test_color_dictionary_crud(api: AsyncClient, admin: Headers) -> None:
    created = await _color(api, admin, "orange", "Оранжевый", "#F57C00")
    # Образец хранится строчными
    assert created["hex"] == "#f57c00"
    assert created["is_active"] is True
    assert created["products_count"] == 0

    duplicate = await api.post(
        COLORS, headers=admin, json={"code": "orange", "name": "Ещё", "hex": "#000000"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "color_code_exists"

    updated = await api.patch(
        f"{COLORS}/{created['id']}",
        headers=admin,
        json={"name": "Апельсиновый", "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Апельсиновый"
    assert updated.json()["is_active"] is False

    listed = await api.get(COLORS, headers=admin, params={"is_active": "false"})
    assert [item["code"] for item in listed.json()] == ["orange"]

    deleted = await api.delete(f"{COLORS}/{created['id']}", headers=admin)
    assert deleted.status_code == 204
    assert (await api.get(COLORS, headers=admin)).json() == []


async def test_color_validation(api: AsyncClient, admin: Headers) -> None:
    for body in (
        {"code": "Black", "name": "Чёрный", "hex": "#000000"},
        {"code": "black", "name": "Чёрный", "hex": "black"},
        {"code": "black", "name": "", "hex": "#000000"},
    ):
        response = await api.post(COLORS, headers=admin, json=body)
        assert response.status_code == 422, body
    # Код цвета не меняется: он записан в заявках
    color = await _color(api, admin, "black", "Чёрный", "#000000")
    response = await api.patch(f"{COLORS}/{color['id']}", headers=admin, json={"code": "noir"})
    assert response.status_code == 200
    assert response.json()["code"] == "black"


async def test_used_color_is_not_deleted(
    api: AsyncClient, admin: Headers, palette: dict[str, dict], rope_colors: dict
) -> None:
    response = await api.delete(f"{COLORS}/{palette['black']['id']}", headers=admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "color_in_use"
    listed = {item["code"]: item for item in (await api.get(COLORS, headers=admin)).json()}
    assert listed["black"]["products_count"] == 1


async def test_dictionary_permissions(api: AsyncClient, login_as) -> None:
    manager = await login_as(UserRole.MANAGER)
    assert (await api.get(COLORS, headers=manager)).status_code == 200
    response = await api.post(
        COLORS, headers=manager, json={"code": "x", "name": "X", "hex": "#000000"}
    )
    assert response.status_code == 403


# ============================================================ цвета товара
async def test_product_colors_totals_and_availability(
    rope_colors: dict, catalog: CatalogFixture
) -> None:
    assert rope_colors["sku"] == ROPE
    assert [item["code"] for item in rope_colors["items"]] == ["black", "red", "blue"]
    black, red, blue = rope_colors["items"]
    assert black["quantity"] == "100.000"
    assert black["public_availability"] == "IN_STOCK"
    assert red["price_delta"] == "200.00"
    assert red["public_availability"] == "OUT_OF_STOCK"
    assert blue["public_availability"] == "IN_STOCK"
    # Разбивка по цветам рядом с общим остатком по складам (152,5 м)
    assert Decimal(rope_colors["colors_total"]) == Decimal("150")
    assert Decimal(rope_colors["stock_total"]) == Decimal("152.5")


async def test_product_colors_replace_set_and_audit(
    api: AsyncClient,
    admin: Headers,
    catalog: CatalogFixture,
    palette: dict[str, dict],
    rope_colors: dict,
    committed_session: AsyncSession,
) -> None:
    product_id = catalog.products["rope"].id
    body = await _set_colors(
        api, admin, product_id, [{"color_id": palette["red"]["id"], "quantity": "5"}]
    )
    assert [item["code"] for item in body["items"]] == ["red"]
    assert body["items"][0]["price_delta"] == "0.00"
    assert (await api.get(colors_url(product_id), headers=admin)).json() == body

    entries = (
        (
            await committed_session.execute(
                select(AuditLog).where(AuditLog.action == "product.colors_updated")
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 2
    assert entries[-1].changes["new"] == [
        {"color": "red", "quantity": "5.000", "price_delta": "0.00"}
    ]

    # Повтор того же набора не пишет аудит
    await _set_colors(api, admin, product_id, [{"color_id": palette["red"]["id"], "quantity": "5"}])
    count = len(
        (
            await committed_session.execute(
                select(AuditLog).where(AuditLog.action == "product.colors_updated")
            )
        )
        .scalars()
        .all()
    )
    assert count == 2

    cleared = await _set_colors(api, admin, product_id, [])
    assert cleared["items"] == []


async def test_product_colors_validation(
    api: AsyncClient,
    admin: Headers,
    catalog: CatalogFixture,
    palette: dict[str, dict],
    committed_session: AsyncSession,
) -> None:
    url = colors_url(catalog.products["rope"].id)
    black = palette["black"]["id"]

    duplicate = await api.put(
        url, headers=admin, json={"items": [{"color_id": black}, {"color_id": black}]}
    )
    assert duplicate.status_code == 422

    negative = await api.put(
        url, headers=admin, json={"items": [{"color_id": black, "quantity": "-1"}]}
    )
    assert negative.status_code == 422

    missing = await api.put(url, headers=admin, json={"items": [{"color_id": 999_999}]})
    assert missing.status_code == 404

    unknown_product = await api.put(colors_url(999_999), headers=admin, json={"items": []})
    assert unknown_product.status_code == 404


async def test_inactive_color_kept_but_not_added(
    api: AsyncClient,
    admin: Headers,
    catalog: CatalogFixture,
    palette: dict[str, dict],
) -> None:
    rope = catalog.products["rope"].id
    fastener = catalog.products["fastener"].id
    await _set_colors(api, admin, rope, [{"color_id": palette["black"]["id"], "quantity": "1"}])
    await api.patch(f"{COLORS}/{palette['black']['id']}", headers=admin, json={"is_active": False})

    # Уже привязанный отключённый цвет сохраняется при повторной отправке
    kept = await _set_colors(
        api, admin, rope, [{"color_id": palette["black"]["id"], "quantity": "2"}]
    )
    assert kept["items"][0]["color_is_active"] is False

    # А новому товару его не добавить
    response = await api.put(
        colors_url(fastener), headers=admin, json={"items": [{"color_id": palette["black"]["id"]}]}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "color_inactive"


async def test_product_colors_permissions(
    api: AsyncClient, login_as, catalog: CatalogFixture, palette: dict[str, dict]
) -> None:
    manager = await login_as(UserRole.MANAGER)
    url = colors_url(catalog.products["rope"].id)
    assert (await api.get(url, headers=manager)).status_code == 200
    response = await api.put(
        url, headers=manager, json={"items": [{"color_id": palette["black"]["id"]}]}
    )
    assert response.status_code == 403
    content = await login_as(UserRole.CONTENT_MANAGER)
    response = await api.put(
        url, headers=content, json={"items": [{"color_id": palette["black"]["id"]}]}
    )
    assert response.status_code == 200


# ================================================================= витрина
async def test_public_list_shows_color_swatches_without_quantities(
    api: AsyncClient, rope_colors: dict
) -> None:
    response = await api.get(PUBLIC_PRODUCTS, params={"search": ROPE})
    item = next(row for row in response.json()["items"] if row["sku"] == ROPE)
    assert item["colors"] == [
        {"code": "black", "name": "Чёрный", "hex": "#1f1f1f", "availability": "IN_STOCK"},
        {"code": "red", "name": "Красный", "hex": "#d32f2f", "availability": "OUT_OF_STOCK"},
        {"code": "blue", "name": "Синий", "hex": "#1976d2", "availability": "IN_STOCK"},
    ]
    # Точный остаток цвета наружу не уходит
    assert "quantity" not in str(item["colors"])

    others = [row for row in response.json()["items"] if row["sku"] != ROPE]
    assert all(row["colors"] == [] for row in others)


async def test_public_detail_color_price_includes_surcharge(
    api: AsyncClient, rope_colors: dict
) -> None:
    body = (await api.get(f"{PUBLIC_PRODUCTS}/{ROPE_SLUG}")).json()
    colors = {item["code"]: item for item in body["colors"]}
    assert colors["black"]["price"] == body["price"]
    red_tiers = [Decimal(tier["price"]) for tier in colors["red"]["price"]["tiers"]]
    base_tiers = [Decimal(tier["price"]) for tier in body["price"]["tiers"]]
    assert red_tiers == [price + 200 for price in base_tiers]
    assert (
        Decimal(colors["red"]["price"]["from_price"]) == Decimal(body["price"]["from_price"]) + 200
    )


async def test_inactive_colors_are_hidden_on_storefront(
    api: AsyncClient, admin: Headers, palette: dict[str, dict], rope_colors: dict
) -> None:
    await api.patch(f"{COLORS}/{palette['red']['id']}", headers=admin, json={"is_active": False})
    body = (await api.get(f"{PUBLIC_PRODUCTS}/{ROPE_SLUG}")).json()
    assert [item["code"] for item in body["colors"]] == ["black", "blue"]


async def test_color_follows_availability_override(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, rope_colors: dict
) -> None:
    await api.patch(
        f"{PRODUCTS}/{catalog.products['rope'].id}/availability",
        headers=admin,
        json={"stock_display_override": "ON_REQUEST"},
    )
    body = (await api.get(f"{PUBLIC_PRODUCTS}/{ROPE_SLUG}")).json()
    assert {item["availability"] for item in body["colors"]} == {"ON_REQUEST"}


# ================================================================== заявки
async def _items(session: AsyncSession) -> list[RequestItem]:
    query = (
        select(RequestItem)
        .order_by(RequestItem.sort_order)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(query)).scalars().all())


async def test_request_with_colors_prices_and_snapshots(
    api: AsyncClient,
    catalog: CatalogFixture,
    rope_colors: dict,
    committed_session: AsyncSession,
    admin: Headers,
) -> None:
    payload = request_payload(
        catalog,
        items=[
            {"sku": ROPE, "quantity": "10", "color": "black"},
            # Тот же товар в другом цвете — отдельная позиция
            {"sku": ROPE, "quantity": "10", "color": "red"},
        ],
    )
    response = await api.post(PUBLIC_REQUESTS, json=payload)
    assert response.status_code == 201, response.text
    body = response.json()

    black, red = body["items"]
    assert (black["color"], black["color_name"], black["unit_price"]) == (
        "black",
        "Чёрный",
        "3200.00",
    )
    # Надбавка цвета прибавляется к ступени
    assert (red["color"], red["unit_price"], red["line_total"]) == ("red", "3400.00", "34000.00")
    assert Decimal(body["total_estimate"]) == Decimal("66000.00")

    items = await _items(committed_session)
    assert [(item.color_code_snapshot, item.color_name_snapshot) for item in items] == [
        ("black", "Чёрный"),
        ("red", "Красный"),
    ]

    # Переименование цвета не меняет отправленную заявку
    await api.patch(
        f"{COLORS}/{rope_colors['items'][0]['color_id']}", headers=admin, json={"name": "Угольный"}
    )
    request_id = items[0].request_id
    detail = (await api.get(f"{ADMIN_REQUESTS}/{request_id}", headers=admin)).json()
    assert [item["color_name"] for item in detail["items"]] == ["Чёрный", "Красный"]


async def test_request_rejects_unknown_or_inactive_color(
    api: AsyncClient,
    admin: Headers,
    catalog: CatalogFixture,
    palette: dict[str, dict],
    rope_colors: dict,
) -> None:
    unknown = await api.post(
        PUBLIC_REQUESTS,
        json=request_payload(catalog, items=[{"sku": ROPE, "quantity": "10", "color": "green"}]),
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "color_unavailable"
    assert unknown.json()["error"]["details"]["items"] == [{"sku": ROPE, "color": "green"}]

    await api.patch(f"{COLORS}/{palette['red']['id']}", headers=admin, json={"is_active": False})
    inactive = await api.post(
        PUBLIC_REQUESTS,
        json=request_payload(catalog, items=[{"sku": ROPE, "quantity": "10", "color": "red"}]),
    )
    assert inactive.status_code == 422


async def test_request_without_color_is_accepted(
    api: AsyncClient, catalog: CatalogFixture, rope_colors: dict
) -> None:
    """Цвет уточнит менеджер: так приходят списки артикулов и старые корзины."""
    response = await api.post(
        PUBLIC_REQUESTS, json=request_payload(catalog, items=[{"sku": ROPE, "quantity": "10"}])
    )
    assert response.status_code == 201
    item = response.json()["items"][0]
    assert (item["color"], item["unit_price"]) == (None, "3200.00")


async def test_request_rejects_duplicate_color_line(
    api: AsyncClient, catalog: CatalogFixture, rope_colors: dict
) -> None:
    line = {"sku": ROPE, "quantity": "10", "color": "black"}
    response = await api.post(PUBLIC_REQUESTS, json=request_payload(catalog, items=[line, line]))
    assert response.status_code == 422


async def test_notification_payload_mentions_color(
    api: AsyncClient,
    catalog: CatalogFixture,
    rope_colors: dict,
    committed_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", ["-1001"])
    monkeypatch.setattr(settings, "NOTIFY_EMAILS", ["sales@oinau-pro.kz"])
    await api.post(
        PUBLIC_REQUESTS,
        json=request_payload(
            catalog,
            items=[
                {"sku": ROPE, "quantity": "10", "color": "red"},
                {"sku": "KRP-M10", "quantity": "1"},
            ],
        ),
    )
    events = (await committed_session.execute(select(NotificationOutbox))).scalars().all()
    assert {event.channel for event in events} == {"telegram", "email"}
    for event in events:
        colored, plain = event.payload["items"]
        assert colored["color"] == "Красный"
        # Позиция без цвета выглядит в уведомлении как раньше
        assert "color" not in plain
        message = build_message(
            event=event.event,
            channel=event.channel,
            recipient=event.recipient,
            payload=event.payload,
        )
        assert "Канат полипропиленовый 16 мм, цвет: Красный" in message.text


async def test_one_click_with_color(
    api: AsyncClient, catalog: CatalogFixture, rope_colors: dict
) -> None:
    form = {
        "mode": "CALLBACK",
        "name": "Иван",
        "phone": "+77011234567",
        "product_sku": ROPE,
        "product_color": "red",
        "quantity": "10",
    }
    parts = [(key, (None, value)) for key, value in form.items()]
    response = await api.post(QUICK, files=parts)
    assert response.status_code == 201, response.text
    item = response.json()["items"][0]
    assert (item["color"], item["unit_price"]) == ("red", "3400.00")

    form["product_color"] = "green"
    parts = [(key, (None, value)) for key, value in form.items()]
    rejected = await api.post(QUICK, files=parts)
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "color_unavailable"


async def test_color_on_quick_form_requires_product(api: AsyncClient) -> None:
    form = {"mode": "CALLBACK", "name": "Иван", "phone": "+77011234567", "product_color": "red"}
    response = await api.post(QUICK, files=[(key, (None, value)) for key, value in form.items()])
    assert response.status_code == 422
