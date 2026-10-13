"""Интеграционные тесты Admin API товаров."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.users.enums import UserRole
from tests.conftest import Headers
from tests.helpers import count_queries

CATEGORIES = "/api/v1/admin/categories"

PRODUCTS = "/api/v1/admin/products"
ATTRIBUTES = "/api/v1/admin/attributes"


def product_payload(sku: str, slug: str, name: str, **extra: object) -> dict:
    return {"sku": sku, "slug": slug, "translations": {"ru": {"name": name}}, **extra}


async def make_category(api: AsyncClient, admin: Headers, slug: str, name: str) -> dict:
    response = await api.post(
        CATEGORIES, headers=admin, json={"slug": slug, "translations": {"ru": {"name": name}}}
    )
    return response.json()


async def make_attribute(
    api: AsyncClient, admin: Headers, code: str, value_type: str, **extra: object
) -> dict:
    payload = {"code": code, "value_type": value_type, "names": {"ru": code}, **extra}
    return (await api.post(ATTRIBUTES, headers=admin, json=payload)).json()


# =============================================================== создание
async def test_create_minimal_product(api: AsyncClient, admin: Headers) -> None:
    response = await api.post(
        PRODUCTS, headers=admin, json=product_payload("KAN-16", "kanat-16", "Канат 16 мм")
    )
    assert response.status_code == 201

    body = response.json()
    assert body["sku"] == "KAN-16"
    assert body["name"] == "Канат 16 мм"
    assert body["status"] == "DRAFT"
    assert body["unit"] == "pcs"
    assert Decimal(body["min_order_qty"]) == 1
    # Черновик не виден на витрине, хотя is_active=true
    assert body["is_publicly_visible"] is False


async def test_create_with_all_fields(api: AsyncClient, admin: Headers) -> None:
    category = await make_category(api, admin, "kanaty", "Канаты")
    attribute = await make_attribute(api, admin, "diametr", "NUMBER", unit="мм")

    response = await api.post(
        PRODUCTS,
        headers=admin,
        json={
            "sku": "KAN-16-PP",
            "slug": "kanat-16-pp",
            "status": "PUBLISHED",
            "is_active": True,
            "is_featured": True,
            "unit": "m",
            "min_order_qty": "2.5",
            "brand": "OinauPro",
            "specs": {"Страна": "Казахстан"},
            "external_id": "1c-guid-001",
            "translations": {
                "ru": {
                    "name": "Канат полипропиленовый",
                    "short_description": "Кратко",
                    "description": "Подробно",
                    "seo_title": "Канат купить",
                }
            },
            "categories": [{"category_id": category["id"]}],
            "attributes": [{"attribute_id": attribute["id"], "value_numeric": "16"}],
        },
    )
    assert response.status_code == 201

    body = response.json()
    assert body["is_publicly_visible"] is True
    assert body["specs"] == {"Страна": "Казахстан"}
    assert body["translations"]["ru"]["short_description"] == "Кратко"
    assert body["categories"][0]["is_primary"] is True
    assert Decimal(body["attributes"][0]["value_numeric"]) == 16


@pytest.mark.parametrize(
    "payload",
    [
        {"sku": "", "slug": "ok-slug"},
        {"sku": "ARTIKUL 16", "slug": "ok-slug"},  # пробел
        {"sku": "OK-1", "slug": "Kanat-16"},  # верхний регистр в slug
        {"sku": "OK-1", "slug": "kanat_16"},  # подчёркивание
        {"sku": "OK-1", "slug": ""},
    ],
)
async def test_invalid_sku_or_slug(api: AsyncClient, admin: Headers, payload: dict) -> None:
    response = await api.post(
        PRODUCTS,
        headers=admin,
        json={**payload, "translations": {"ru": {"name": "Товар"}}},
    )
    assert response.status_code == 422


async def test_default_locale_translation_is_required(api: AsyncClient, admin: Headers) -> None:
    response = await api.post(
        PRODUCTS,
        headers=admin,
        json={"sku": "NO-RU", "slug": "no-ru", "translations": {"kk": {"name": "Арқан"}}},
    )
    assert response.status_code == 422


async def test_duplicate_sku_is_rejected(api: AsyncClient, admin: Headers) -> None:
    await api.post(PRODUCTS, headers=admin, json=product_payload("DUP-1", "prvyj", "Первый"))
    response = await api.post(
        PRODUCTS, headers=admin, json=product_payload("DUP-1", "vtoroj", "Второй")
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "sku_exists"


async def test_duplicate_slug_is_rejected(api: AsyncClient, admin: Headers) -> None:
    await api.post(PRODUCTS, headers=admin, json=product_payload("SLG-1", "odin", "Первый"))
    response = await api.post(
        PRODUCTS, headers=admin, json=product_payload("SLG-2", "odin", "Второй")
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "product_slug_exists"


# =============================================================== изменение
async def test_partial_update_does_not_touch_other_fields(api: AsyncClient, admin: Headers) -> None:
    created = (
        await api.post(
            PRODUCTS,
            headers=admin,
            json=product_payload("UPD-1", "obnovlyaemyj", "Название", brand="Бренд", unit="m"),
        )
    ).json()

    response = await api.patch(
        f"{PRODUCTS}/{created['id']}", headers=admin, json={"is_featured": True}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["is_featured"] is True
    assert body["brand"] == "Бренд"
    assert body["unit"] == "m"
    assert body["name"] == "Название"


async def test_translations_merge_and_keep_existing(api: AsyncClient, admin: Headers) -> None:
    """Добавление казахской версии не должно стирать русскую."""
    created = (
        await api.post(
            PRODUCTS, headers=admin, json=product_payload("I18N-1", "dvuyazychnyj", "Канат")
        )
    ).json()

    response = await api.patch(
        f"{PRODUCTS}/{created['id']}",
        headers=admin,
        json={"translations": {"kk": {"name": "Арқан"}}},
    )
    assert response.status_code == 200

    body = response.json()
    assert set(body["translations"]) == {"ru", "kk"}
    assert body["translations"]["ru"]["name"] == "Канат"
    assert body["name"] == "Канат"  # отображается локаль по умолчанию


async def test_publication_makes_product_visible(api: AsyncClient, admin: Headers) -> None:
    """Правило видимости одно для админки и витрины."""
    created = (
        await api.post(
            PRODUCTS, headers=admin, json=product_payload("PUB-1", "publikuemyj", "Публикуемый")
        )
    ).json()
    assert (await api.get("/api/v1/public/products/publikuemyj")).status_code == 404

    published = await api.patch(
        f"{PRODUCTS}/{created['id']}", headers=admin, json={"status": "PUBLISHED"}
    )
    assert published.json()["is_publicly_visible"] is True
    assert (await api.get("/api/v1/public/products/publikuemyj")).status_code == 200

    deactivated = await api.patch(
        f"{PRODUCTS}/{created['id']}", headers=admin, json={"is_active": False}
    )
    assert deactivated.json()["is_publicly_visible"] is False
    assert (await api.get("/api/v1/public/products/publikuemyj")).status_code == 404


async def test_archived_product_is_hidden_from_public(api: AsyncClient, admin: Headers) -> None:
    created = (
        await api.post(
            PRODUCTS,
            headers=admin,
            json=product_payload("ARC-1", "arhiviruemyj", "Архивный", status="PUBLISHED"),
        )
    ).json()
    await api.patch(f"{PRODUCTS}/{created['id']}", headers=admin, json={"status": "ARCHIVED"})
    assert (await api.get("/api/v1/public/products/arhiviruemyj")).status_code == 404


async def test_unknown_product_returns_404(api: AsyncClient, admin: Headers) -> None:
    assert (await api.get(f"{PRODUCTS}/999999", headers=admin)).status_code == 404


# =============================================================== удаление
async def test_soft_delete_and_restore(api: AsyncClient, admin: Headers) -> None:
    created = (
        await api.post(
            PRODUCTS,
            headers=admin,
            json=product_payload("DEL-1", "udalyaemyj", "Удаляемый", status="PUBLISHED"),
        )
    ).json()

    assert (await api.delete(f"{PRODUCTS}/{created['id']}", headers=admin)).status_code == 204
    assert (await api.get("/api/v1/public/products/udalyaemyj")).status_code == 404

    listing = (await api.get(PRODUCTS, headers=admin)).json()
    assert created["id"] not in {item["id"] for item in listing["items"]}

    with_deleted = (await api.get(PRODUCTS, headers=admin, params={"include_deleted": True})).json()
    assert created["id"] in {item["id"] for item in with_deleted["items"]}

    restored = await api.post(f"{PRODUCTS}/{created['id']}/restore", headers=admin)
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert restored.json()["is_active"] is False  # публикацию возвращает человек


async def test_deleted_product_frees_sku(api: AsyncClient, admin: Headers) -> None:
    created = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("FREE-1", "svobodnyj", "А"))
    ).json()
    await api.delete(f"{PRODUCTS}/{created['id']}", headers=admin)

    replacement = await api.post(
        PRODUCTS, headers=admin, json=product_payload("FREE-1", "novyj-svobodnyj", "Б")
    )
    assert replacement.status_code == 201


async def test_restore_of_living_product_is_rejected(api: AsyncClient, admin: Headers) -> None:
    created = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("LIVE-1", "zhivoj", "Живой"))
    ).json()
    response = await api.post(f"{PRODUCTS}/{created['id']}/restore", headers=admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "product_not_deleted"


# ============================================================== категории
async def test_replace_categories_and_primary(api: AsyncClient, admin: Headers) -> None:
    first = await make_category(api, admin, "pervaya", "Первая")
    second = await make_category(api, admin, "vtoraya", "Вторая")
    product = (
        await api.post(
            PRODUCTS, headers=admin, json=product_payload("CAT-1", "s-kategoriyami", "Т")
        )
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/categories",
        headers=admin,
        json={
            "items": [
                {"category_id": first["id"]},
                {"category_id": second["id"], "is_primary": True},
            ]
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["categories_count"] == 2
    assert body["primary_category"]["category_id"] == second["id"]

    replaced = await api.put(
        f"{PRODUCTS}/{product['id']}/categories",
        headers=admin,
        json={"items": [{"category_id": first["id"]}]},
    )
    assert replaced.json()["categories_count"] == 1
    # Основную не указали — ею стала единственная категория
    assert replaced.json()["primary_category"]["category_id"] == first["id"]


async def test_duplicate_category_is_rejected(api: AsyncClient, admin: Headers) -> None:
    category = await make_category(api, admin, "dublikat", "Дубликат")
    product = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("CAT-2", "dubli", "Т"))
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/categories",
        headers=admin,
        json={"items": [{"category_id": category["id"]}, {"category_id": category["id"]}]},
    )
    assert response.status_code == 422


async def test_two_primary_categories_are_rejected(api: AsyncClient, admin: Headers) -> None:
    first = await make_category(api, admin, "osnovnaya-1", "Первая")
    second = await make_category(api, admin, "osnovnaya-2", "Вторая")
    product = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("CAT-3", "dve-osnovnyh", "Т"))
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/categories",
        headers=admin,
        json={
            "items": [
                {"category_id": first["id"], "is_primary": True},
                {"category_id": second["id"], "is_primary": True},
            ]
        },
    )
    assert response.status_code == 422


async def test_deleted_category_cannot_be_assigned(api: AsyncClient, admin: Headers) -> None:
    category = await make_category(api, admin, "udalennaya", "Удалённая")
    await api.delete(f"{CATEGORIES}/{category['id']}", headers=admin)
    product = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("CAT-4", "bez-razdela", "Т"))
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/categories",
        headers=admin,
        json={"items": [{"category_id": category["id"]}]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_deleted"


async def test_unknown_category_returns_404(api: AsyncClient, admin: Headers) -> None:
    product = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("CAT-5", "nesushch", "Т"))
    ).json()
    response = await api.put(
        f"{PRODUCTS}/{product['id']}/categories",
        headers=admin,
        json={"items": [{"category_id": 999_999}]},
    )
    assert response.status_code == 404


# ========================================================== характеристики
@pytest.mark.parametrize(
    ("value_type", "field", "value", "expected"),
    [
        ("STRING", "value_string", "Полиамид", "Полиамид"),
        ("NUMBER", "value_numeric", "16.5", "16.500"),
        ("BOOLEAN", "value_bool", True, True),
    ],
)
async def test_scalar_attribute_values(
    api: AsyncClient, admin: Headers, value_type: str, field: str, value: object, expected: object
) -> None:
    attribute = await make_attribute(api, admin, f"attr_{value_type.lower()}", value_type)
    product = (
        await api.post(
            PRODUCTS,
            headers=admin,
            json=product_payload(f"AT-{value_type}", f"at-{value_type.lower()}", "Т"),
        )
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": attribute["id"], field: value}]},
    )
    assert response.status_code == 200
    assert response.json()["attributes"][0][field] == expected


async def test_option_attribute_value(api: AsyncClient, admin: Headers) -> None:
    attribute = await make_attribute(
        api,
        admin,
        "material",
        "OPTION",
        options=[{"slug": "pp", "values": {"ru": "Полипропилен"}}],
    )
    option_id = attribute["options"][0]["id"]
    product = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("OPT-1", "s-opciej", "Т"))
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": attribute["id"], "option_id": option_id}]},
    )
    assert response.status_code == 200

    value = response.json()["attributes"][0]
    assert value["option_id"] == option_id
    assert value["option_value"] == "Полипропилен"


async def test_value_must_match_attribute_type(api: AsyncClient, admin: Headers) -> None:
    attribute = await make_attribute(api, admin, "chislovaya", "NUMBER")
    product = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("MIS-1", "nesootvet", "Т"))
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": attribute["id"], "value_string": "шестнадцать"}]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "attribute_value_type_mismatch"


async def test_option_must_belong_to_attribute(api: AsyncClient, admin: Headers) -> None:
    owner = await make_attribute(
        api, admin, "cvet", "OPTION", options=[{"slug": "red", "values": {"ru": "Красный"}}]
    )
    other = await make_attribute(
        api, admin, "pokrytie", "OPTION", options=[{"slug": "cink", "values": {"ru": "Цинк"}}]
    )
    product = (
        await api.post(
            PRODUCTS, headers=admin, json=product_payload("OWN-1", "chuzhaya-opciya", "Т")
        )
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": owner["id"], "option_id": other["options"][0]["id"]}]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "attribute_option_owner_mismatch"


async def test_several_values_at_once_are_rejected(api: AsyncClient, admin: Headers) -> None:
    attribute = await make_attribute(api, admin, "mnogo", "STRING")
    product = (
        await api.post(
            PRODUCTS, headers=admin, json=product_payload("MUL-1", "mnogo-znachenij", "Т")
        )
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/attributes",
        headers=admin,
        json={
            "items": [{"attribute_id": attribute["id"], "value_string": "А", "value_numeric": "1"}]
        },
    )
    assert response.status_code == 422


async def test_empty_value_is_rejected(api: AsyncClient, admin: Headers) -> None:
    attribute = await make_attribute(api, admin, "pustaya", "STRING")
    product = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("EMP-1", "pusto", "Т"))
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": attribute["id"]}]},
    )
    assert response.status_code == 422


async def test_duplicate_attribute_value_is_rejected(api: AsyncClient, admin: Headers) -> None:
    attribute = await make_attribute(api, admin, "dubl_attr", "STRING")
    product = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("DUB-A", "dubl-attr", "Т"))
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/attributes",
        headers=admin,
        json={
            "items": [
                {"attribute_id": attribute["id"], "value_string": "А"},
                {"attribute_id": attribute["id"], "value_string": "Б"},
            ]
        },
    )
    assert response.status_code == 422


async def test_several_options_of_one_attribute_are_allowed(
    api: AsyncClient, admin: Headers
) -> None:
    """Схема сознательно допускает многозначность для OPTION —
    товар бывает в нескольких цветах."""
    attribute = await make_attribute(
        api,
        admin,
        "cveta",
        "OPTION",
        options=[
            {"slug": "red", "values": {"ru": "Красный"}},
            {"slug": "blue", "values": {"ru": "Синий"}},
        ],
    )
    product = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("MC-1", "mnogocvetnyj", "Т"))
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/attributes",
        headers=admin,
        json={
            "items": [
                {"attribute_id": attribute["id"], "option_id": attribute["options"][0]["id"]},
                {"attribute_id": attribute["id"], "option_id": attribute["options"][1]["id"]},
            ]
        },
    )
    assert response.status_code == 200
    assert len(response.json()["attributes"]) == 2


async def test_inactive_attribute_can_still_hold_values(api: AsyncClient, admin: Headers) -> None:
    """is_active скрывает характеристику из фильтров витрины,
    но не делает недействительными уже заведённые данные."""
    attribute = await make_attribute(api, admin, "otklyuchennaya", "STRING")
    await api.patch(f"{ATTRIBUTES}/{attribute['id']}", headers=admin, json={"is_active": False})
    product = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("INA-1", "s-otkl", "Т"))
    ).json()

    response = await api.put(
        f"{PRODUCTS}/{product['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": attribute["id"], "value_string": "Значение"}]},
    )
    assert response.status_code == 200


async def test_attributes_are_replaced_not_merged(api: AsyncClient, admin: Headers) -> None:
    first = await make_attribute(api, admin, "zamena_a", "STRING")
    second = await make_attribute(api, admin, "zamena_b", "STRING")
    product = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("REP-1", "zamena", "Т"))
    ).json()

    await api.put(
        f"{PRODUCTS}/{product['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": first["id"], "value_string": "А"}]},
    )
    response = await api.put(
        f"{PRODUCTS}/{product['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": second["id"], "value_string": "Б"}]},
    )

    codes = {item["code"] for item in response.json()["attributes"]}
    assert codes == {"zamena_b"}


# ================================================================= список
async def test_list_pagination_and_sorting_whitelist(api: AsyncClient, admin: Headers) -> None:
    for index in range(5):
        await api.post(
            PRODUCTS,
            headers=admin,
            json=product_payload(f"LST-{index}", f"list-{index}", f"Товар {index}"),
        )

    page = (await api.get(PRODUCTS, headers=admin, params={"page_size": 2, "sort": "sku"})).json()
    assert page["total"] == 5
    assert page["pages"] == 3
    assert [item["sku"] for item in page["items"]] == ["LST-0", "LST-1"]

    invalid = await api.get(PRODUCTS, headers=admin, params={"sort": "price; DROP TABLE products"})
    assert invalid.status_code == 422

    too_big = await api.get(PRODUCTS, headers=admin, params={"page_size": 10_000})
    assert too_big.status_code == 422


async def test_list_search_by_sku_slug_and_name(api: AsyncClient, admin: Headers) -> None:
    await api.post(
        PRODUCTS, headers=admin, json=product_payload("SRCH-XYZ", "poisk-slug", "Канат особый")
    )
    await api.post(PRODUCTS, headers=admin, json=product_payload("OTHER-1", "drugoj", "Крепление"))

    by_sku = (await api.get(PRODUCTS, headers=admin, params={"search": "XYZ"})).json()
    by_slug = (await api.get(PRODUCTS, headers=admin, params={"search": "poisk"})).json()
    by_name = (await api.get(PRODUCTS, headers=admin, params={"search": "особый"})).json()

    for result in (by_sku, by_slug, by_name):
        assert [item["sku"] for item in result["items"]] == ["SRCH-XYZ"]


async def test_list_filters(api: AsyncClient, admin: Headers) -> None:
    category = await make_category(api, admin, "filtruemaya", "Фильтруемая")
    published = (
        await api.post(
            PRODUCTS,
            headers=admin,
            json=product_payload(
                "FLT-1",
                "opublikovannyj",
                "Опубликованный",
                status="PUBLISHED",
                is_featured=True,
                external_id="1c-flt-1",
                categories=[{"category_id": category["id"]}],
            ),
        )
    ).json()
    await api.post(PRODUCTS, headers=admin, json=product_payload("FLT-2", "chernovik", "Черновик"))

    by_status = (await api.get(PRODUCTS, headers=admin, params={"status": "PUBLISHED"})).json()
    by_featured = (await api.get(PRODUCTS, headers=admin, params={"is_featured": True})).json()
    by_category = (
        await api.get(PRODUCTS, headers=admin, params={"category_id": category["id"]})
    ).json()
    by_external = (
        await api.get(PRODUCTS, headers=admin, params={"external_id": "1c-flt-1"})
    ).json()

    for result in (by_status, by_featured, by_category, by_external):
        assert [item["id"] for item in result["items"]] == [published["id"]]


# ================================================================== RBAC
@pytest.mark.parametrize(
    ("role", "read_status", "write_status"),
    [
        (UserRole.SUPERADMIN, 200, 201),
        (UserRole.ADMIN, 200, 201),
        (UserRole.CONTENT_MANAGER, 200, 201),
        (UserRole.MANAGER, 200, 403),
        (UserRole.VIEWER, 200, 403),
    ],
)
async def test_product_permissions(
    api: AsyncClient,
    login_as,
    role: UserRole,
    read_status: int,
    write_status: int,
) -> None:
    headers = await login_as(role)
    suffix = role.value.lower().replace("_", "-")

    assert (await api.get(PRODUCTS, headers=headers)).status_code == read_status
    created = await api.post(
        PRODUCTS, headers=headers, json=product_payload(f"RBAC-{suffix}", f"rbac-{suffix}", "RBAC")
    )
    assert created.status_code == write_status


async def test_anonymous_access_is_rejected(api: AsyncClient) -> None:
    assert (await api.get(PRODUCTS)).status_code == 401
    assert (
        await api.post(PRODUCTS, json=product_payload("ANON-1", "anon", "Аноним"))
    ).status_code == 401


# ================================================================= аудит
async def test_mutations_are_audited(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    category = await make_category(api, admin, "auditnaya", "Аудит")
    attribute = await make_attribute(api, admin, "audit_attr", "STRING")
    created = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("AUD-1", "auditnyj", "Аудит"))
    ).json()

    await api.patch(f"{PRODUCTS}/{created['id']}", headers=admin, json={"is_featured": True})
    await api.put(
        f"{PRODUCTS}/{created['id']}/categories",
        headers=admin,
        json={"items": [{"category_id": category["id"]}]},
    )
    await api.put(
        f"{PRODUCTS}/{created['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": attribute["id"], "value_string": "А"}]},
    )
    await api.delete(f"{PRODUCTS}/{created['id']}", headers=admin)
    await api.post(f"{PRODUCTS}/{created['id']}/restore", headers=admin)

    entries = (
        (
            await committed_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "product", AuditLog.entity_id == created["id"]
                )
            )
        )
        .scalars()
        .all()
    )
    actions = {entry.action for entry in entries}

    assert actions == {
        "catalog.product_created",
        "catalog.product_updated",
        "catalog.product_categories_replaced",
        "catalog.product_attributes_replaced",
        "catalog.product_deleted",
        "catalog.product_restored",
    }
    assert all(entry.user_id is not None for entry in entries)


async def test_reads_are_not_audited(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    created = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("RD-1", "chitaemyj", "Ч"))
    ).json()
    await api.get(PRODUCTS, headers=admin)
    await api.get(f"{PRODUCTS}/{created['id']}", headers=admin)

    entries = (
        (await committed_session.execute(select(AuditLog).where(AuditLog.entity_type == "product")))
        .scalars()
        .all()
    )
    assert {entry.action for entry in entries} == {"catalog.product_created"}


# ======================================================== производительность
async def test_product_list_has_no_n_plus_one(
    api: AsyncClient, admin: Headers, test_engine: AsyncEngine
) -> None:
    category = await make_category(api, admin, "perf", "Перф")
    attribute = await make_attribute(api, admin, "perf_attr", "STRING")

    async def create(index: int) -> None:
        await api.post(
            PRODUCTS,
            headers=admin,
            json=product_payload(
                f"PERF-{index}",
                f"perf-{index}",
                f"Товар {index}",
                categories=[{"category_id": category["id"]}],
                attributes=[{"attribute_id": attribute["id"], "value_string": "А"}],
            ),
        )

    await create(0)
    with count_queries(test_engine) as small:
        assert (await api.get(PRODUCTS, headers=admin, params={"page_size": 60})).status_code == 200
    baseline = len(small)

    for index in range(1, 13):
        await create(index)

    with count_queries(test_engine) as large:
        body = (await api.get(PRODUCTS, headers=admin, params={"page_size": 60})).json()

    assert body["total"] == 13
    assert len(large) == baseline


async def test_product_detail_query_count_is_fixed(
    api: AsyncClient, admin: Headers, test_engine: AsyncEngine
) -> None:
    """Число запросов карточки не зависит от количества связей.

    Сравниваются два непустых товара: с одной категорией и одной
    характеристикой против трёх и трёх. Товар вообще без связей брать
    нельзя — для пустой коллекции SQLAlchemy закономерно не выполняет
    вложенный selectinload, и счётчики разошлись бы не из-за N+1.
    """
    categories = [
        await make_category(api, admin, f"det-{index}", f"Раздел {index}") for index in range(3)
    ]
    attributes = [
        await make_attribute(api, admin, f"det_attr_{index}", "STRING") for index in range(3)
    ]

    small = (
        await api.post(
            PRODUCTS,
            headers=admin,
            json=product_payload(
                "DET-1",
                "malo-svyazej",
                "Мало связей",
                categories=[{"category_id": categories[0]["id"]}],
                attributes=[{"attribute_id": attributes[0]["id"], "value_string": "А"}],
            ),
        )
    ).json()
    large = (
        await api.post(
            PRODUCTS,
            headers=admin,
            json=product_payload(
                "DET-2",
                "mnogo-svyazej",
                "Много связей",
                categories=[{"category_id": item["id"]} for item in categories],
                attributes=[
                    {"attribute_id": item["id"], "value_string": "А"} for item in attributes
                ],
                translations={"ru": {"name": "Много связей"}, "kk": {"name": "Көп"}},
            ),
        )
    ).json()

    with count_queries(test_engine) as first:
        assert (await api.get(f"{PRODUCTS}/{small['id']}", headers=admin)).status_code == 200
    with count_queries(test_engine) as second:
        body = (await api.get(f"{PRODUCTS}/{large['id']}", headers=admin)).json()

    assert body["categories_count"] == 3
    assert len(body["attributes"]) == 3
    assert len(first) == len(second)


# ============================================ мутации удалённого товара
@pytest.fixture
async def deleted_product(api: AsyncClient, admin: Headers) -> dict:
    """Удалённый товар для проверки единого правила изменяемости."""
    created = (
        await api.post(
            PRODUCTS,
            headers=admin,
            json=product_payload("GONE-1", "udalennyj-tovar", "Удалённый", status="PUBLISHED"),
        )
    ).json()
    await api.delete(f"{PRODUCTS}/{created['id']}", headers=admin)
    return created


async def test_deleted_product_is_readable(
    api: AsyncClient, admin: Headers, deleted_product: dict
) -> None:
    """Чтение остаётся доступным: без него нельзя ни разобрать историю,
    ни нажать «восстановить»."""
    response = await api.get(f"{PRODUCTS}/{deleted_product['id']}", headers=admin)
    assert response.status_code == 200
    assert response.json()["deleted_at"] is not None


async def test_deleted_product_cannot_be_patched(
    api: AsyncClient, admin: Headers, deleted_product: dict
) -> None:
    response = await api.patch(
        f"{PRODUCTS}/{deleted_product['id']}", headers=admin, json={"is_featured": True}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "product_deleted"


async def test_deleted_product_categories_cannot_be_changed(
    api: AsyncClient, admin: Headers, deleted_product: dict
) -> None:
    category = await make_category(api, admin, "dlya-udalennogo", "Для удалённого")
    response = await api.put(
        f"{PRODUCTS}/{deleted_product['id']}/categories",
        headers=admin,
        json={"items": [{"category_id": category["id"]}]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "product_deleted"


async def test_deleted_product_attributes_cannot_be_changed(
    api: AsyncClient, admin: Headers, deleted_product: dict
) -> None:
    attribute = await make_attribute(api, admin, "dlya_udalennogo", "STRING")
    response = await api.put(
        f"{PRODUCTS}/{deleted_product['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": attribute["id"], "value_string": "А"}]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "product_deleted"


async def test_deleted_product_cannot_be_deleted_again(
    api: AsyncClient, admin: Headers, deleted_product: dict
) -> None:
    response = await api.delete(f"{PRODUCTS}/{deleted_product['id']}", headers=admin)
    assert response.status_code == 404


async def test_restore_is_the_only_allowed_mutation(
    api: AsyncClient, admin: Headers, deleted_product: dict
) -> None:
    restored = await api.post(f"{PRODUCTS}/{deleted_product['id']}/restore", headers=admin)
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None

    # После восстановления обычное редактирование снова работает
    patched = await api.patch(
        f"{PRODUCTS}/{deleted_product['id']}", headers=admin, json={"is_featured": True}
    )
    assert patched.status_code == 200
    assert patched.json()["is_featured"] is True


async def test_living_product_is_still_editable(api: AsyncClient, admin: Headers) -> None:
    """Единое правило не должно задеть обычный сценарий."""
    category = await make_category(api, admin, "zhivaya-kat", "Живая")
    attribute = await make_attribute(api, admin, "zhivoj_attr", "STRING")
    created = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("ALIVE-1", "zhivoj", "Живой"))
    ).json()

    assert (
        await api.patch(f"{PRODUCTS}/{created['id']}", headers=admin, json={"brand": "Бренд"})
    ).status_code == 200
    assert (
        await api.put(
            f"{PRODUCTS}/{created['id']}/categories",
            headers=admin,
            json={"items": [{"category_id": category["id"]}]},
        )
    ).status_code == 200
    assert (
        await api.put(
            f"{PRODUCTS}/{created['id']}/attributes",
            headers=admin,
            json={"items": [{"attribute_id": attribute["id"], "value_string": "А"}]},
        )
    ).status_code == 200
