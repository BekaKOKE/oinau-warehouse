"""Подтверждение импорта: запись в каталог одной транзакцией."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.catalog.exceptions import AttributeValueTypeMismatchError
from app.modules.catalog.models import Category, CategoryAttribute, Product
from app.modules.imports.models import ImportJob
from app.modules.imports.snapshot import CatalogSnapshotLoader, ProductRef
from app.modules.inventory.models import Stock
from app.modules.pricing.models import PriceTier
from tests.conftest import Headers
from tests.import_helpers import (
    ATTRIBUTES,
    IMPORTS,
    PRODUCTS,
    PUBLIC_PRODUCTS,
    attribute_row,
    build_workbook,
    category_row,
    commit_url,
    count_rows,
    preview,
    preview_and_commit,
    product_row,
    upload,
)


async def product_by_sku(api: AsyncClient, headers: Headers, sku: str) -> dict[str, Any]:
    listing = (await api.get(PRODUCTS, headers=headers, params={"search": sku})).json()
    matches = [item for item in listing["items"] if item["sku"] == sku]
    assert len(matches) == 1, listing
    return (await api.get(f"{PRODUCTS}/{matches[0]['id']}", headers=headers)).json()


async def pricing_of(api: AsyncClient, headers: Headers, product_id: int) -> dict[str, Any]:
    return (await api.get(f"{PRODUCTS}/{product_id}/pricing", headers=headers)).json()


async def attribute_by_code(api: AsyncClient, headers: Headers, code: str) -> dict[str, Any]:
    listing = (await api.get(ATTRIBUTES, headers=headers, params={"search": code})).json()
    return next(item for item in listing["items"] if item["code"] == code)


def full_new_product_file() -> bytes:
    return build_workbook(
        {
            "Categories": [
                category_row("igrovye", parent_slug="komplektuyushchie", sort_order=5),
                category_row("kachely", parent_slug="igrovye", description_ru="Всё для качелей"),
            ],
            "CategoryAttributes": [
                {
                    "category_slug": "kachely",
                    "attribute_code": "color",
                    "sort_order": 1,
                    "is_required": True,
                },
                {
                    "category_slug": "kachely",
                    "attribute_code": "diameter",
                    "sort_order": 0,
                    "is_required": False,
                },
            ],
            "Attributes": [attribute_row("color", "OPTION", sort_order=3)],
            "AttributeOptions": [
                {"attribute_code": "color", "slug": "red", "value_ru": "Красный", "sort_order": 0},
                {"attribute_code": "color", "slug": "blue", "value_ru": "Синий", "sort_order": 1},
            ],
            "Products": [
                product_row(
                    "SW-100",
                    slug="kacheli-100",
                    name_ru="Качели «Гнездо» 100 см",
                    short_description_ru="Круглые качели",
                    description_ru="Строка 1\nСтрока 2",
                    categories="kachely; kanaty",
                    unit="set",
                    min_order_qty=2.5,
                    pricing_type="TIERED",
                    brand="OINAU",
                    external_id="1c-sw-100",
                    is_featured=True,
                ),
            ],
            "Prices": [
                {"sku": "SW-100", "min_qty": 1, "max_qty": 9.999, "price": 45999.99},
                {"sku": "SW-100", "min_qty": 10, "max_qty": None, "price": 0.1},
            ],
            "ProductAttributes": [
                {"sku": "SW-100", "attribute_code": "color", "value": "red"},
                {"sku": "SW-100", "attribute_code": "color", "value": "blue"},
                {"sku": "SW-100", "attribute_code": "diameter", "value": 100.125},
                {"sku": "SW-100", "attribute_code": "certified", "value": "да"},
                {"sku": "SW-100", "attribute_code": "internal_note", "value": "склад Б"},
            ],
            "ProductSpecs": [
                {"sku": "SW-100", "name": "Страна", "value": "Казахстан"},
                {"sku": "SW-100", "name": "Гарантия, мес", "value": 12},
            ],
        }
    )


# ================================================================ создание
async def test_commit_creates_product_with_all_relations(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    _, response = await preview_and_commit(api, admin, full_new_product_file())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job"]["status"] == "COMMITTED"
    assert body["job"]["can_commit"] is False
    assert body["job"]["committed_at"] is not None
    assert body["summary"]["products"] == {"create": 1, "update": 0, "unchanged": 0}

    product = await product_by_sku(api, admin, "SW-100")
    assert product["slug"] == "kacheli-100"
    assert product["status"] == "PUBLISHED"
    assert product["is_featured"] is True
    assert product["unit"] == "set"
    assert product["brand"] == "OINAU"
    assert product["external_id"] == "1c-sw-100"
    assert Decimal(product["min_order_qty"]) == Decimal("2.5")
    assert product["translations"]["ru"]["name"] == "Качели «Гнездо» 100 см"
    assert product["translations"]["ru"]["description"] == "Строка 1\nСтрока 2"
    assert product["specs"] == {"Страна": "Казахстан", "Гарантия, мес": "12"}
    assert product["sync_source"] == "excel"

    # Первая категория в списке — основная.
    assert [(item["slug"], item["is_primary"]) for item in product["categories"]] == [
        ("kachely", True),
        ("kanaty", False),
    ]

    values = {(item["code"], item["option_slug"] or ""): item for item in product["attributes"]}
    assert set(values) == {
        ("color", "red"),
        ("color", "blue"),
        ("diameter", ""),
        ("certified", ""),
        ("internal_note", ""),
    }
    assert Decimal(values[("diameter", "")]["value_numeric"]) == Decimal("100.125")
    assert values[("certified", "")]["value_bool"] is True
    assert values[("internal_note", "")]["value_string"] == "склад Б"

    pricing = await pricing_of(api, admin, product["id"])
    assert pricing["pricing_type"] == "TIERED"
    assert [
        (
            Decimal(tier["min_qty"]),
            tier["max_qty"] and Decimal(tier["max_qty"]),
            Decimal(tier["price"]),
        )
        for tier in pricing["tiers"]
    ] == [
        (Decimal("1"), Decimal("9.999"), Decimal("45999.99")),
        (Decimal("10"), None, Decimal("0.10")),
    ]

    categories = {
        category.slug: category
        for category in (await committed_session.execute(select(Category))).scalars().all()
    }
    root, parent, child = (
        categories["komplektuyushchie"],
        categories["igrovye"],
        categories["kachely"],
    )
    assert child.parent_id == parent.id
    assert parent.path == f"{root.id}.{parent.id}" and parent.depth == 1
    assert child.path == f"{root.id}.{parent.id}.{child.id}" and child.depth == 2
    assert parent.sort_order == 5
    assert child.sync_source == "excel"

    links = (
        (
            await committed_session.execute(
                select(CategoryAttribute).where(CategoryAttribute.category_id == child.id)
            )
        )
        .scalars()
        .all()
    )
    assert {(link.sort_order, link.is_required) for link in links} == {(0, False), (1, True)}

    # Товар сразу виден на витрине в новой категории.
    public = (await api.get(f"{PUBLIC_PRODUCTS}/kacheli-100")).json()
    assert [item["slug"] for item in public["breadcrumbs"]] == [
        "komplektuyushchie",
        "igrovye",
        "kachely",
    ]


# ============================================================== обновление
async def test_commit_updates_existing_product(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    data = build_workbook(
        {
            "Products": [
                product_row(
                    "KAN-16-PP",
                    slug="kanat-16-pp",
                    name_ru="Канат ПП 16 мм",
                    short_description_ru="Армированный канат для лазательных элементов",
                    description_ru="Подробное описание каната.",
                    categories="krepleniya; kanaty",
                    unit="m",
                    min_order_qty=5,
                    pricing_type="FROM",
                    is_featured=True,
                )
            ],
            "Prices": [
                {"sku": "KAN-16-PP", "min_qty": 1, "max_qty": 99, "price": 3600},
                {"sku": "KAN-16-PP", "min_qty": 100, "price": 2500},
            ],
            "ProductAttributes": [
                {"sku": "KAN-16-PP", "attribute_code": "diameter", "value": 16},
                {"sku": "KAN-16-PP", "attribute_code": "material", "value": "pp"},
            ],
            "ProductSpecs": [{"sku": "KAN-16-PP", "name": "Страна", "value": "Россия"}],
        }
    )
    report, response = await preview_and_commit(api, admin, data)
    assert response.status_code == 200, response.text
    assert report["changes"][0]["changed"] == [
        "min_order_qty",
        "translations",
        "categories",
        "attributes",
        "specs",
        "pricing",
    ]

    product = await product_by_sku(api, admin, "KAN-16-PP")
    assert product["translations"]["ru"]["name"] == "Канат ПП 16 мм"
    assert Decimal(product["min_order_qty"]) == Decimal("5")
    assert [(item["slug"], item["is_primary"]) for item in product["categories"]] == [
        ("krepleniya", True),
        ("kanaty", False),
    ]
    # Характеристики заменены целиком: служебной пометки и признака больше нет.
    assert sorted(item["code"] for item in product["attributes"]) == ["diameter", "material"]
    assert product["specs"] == {"Страна": "Россия"}

    pricing = await pricing_of(api, admin, product["id"])
    assert pricing["pricing_type"] == "FROM"
    assert [Decimal(tier["price"]) for tier in pricing["tiers"]] == [
        Decimal("3600.00"),
        Decimal("2500.00"),
    ]

    # Дилерский прайс и остатки импорт не трогает.
    dealer = (
        (
            await committed_session.execute(
                select(PriceTier.price).where(
                    PriceTier.price_list_id == catalog.dealer_price_list.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert dealer == [Decimal("1111.00")]
    stock = (
        await committed_session.execute(
            select(Stock.quantity).where(Stock.product_id == catalog.products["rope"].id)
        )
    ).scalar_one()
    assert stock == Decimal("152.500")


async def test_translations_of_other_fields_are_replaced_by_file(
    api: AsyncClient, admin: Headers, catalog
) -> None:
    """Пустая ячейка описания — пустое описание: файл полностью описывает товар."""
    data = build_workbook(
        {
            "Products": [
                product_row(
                    "KAN-16-PP",
                    slug="kanat-16-pp",
                    name_ru="Канат полипропиленовый 16 мм",
                    categories="kanaty",
                    unit="m",
                    pricing_type="TIERED",
                    is_featured=True,
                )
            ],
            "Prices": [
                {"sku": "KAN-16-PP", "min_qty": 1, "max_qty": 9, "price": 3500},
                {"sku": "KAN-16-PP", "min_qty": 10, "max_qty": 49, "price": 3200},
                {"sku": "KAN-16-PP", "min_qty": 50, "max_qty": 99, "price": 2900},
                {"sku": "KAN-16-PP", "min_qty": 100, "price": 2600},
            ],
        }
    )
    report, response = await preview_and_commit(api, admin, data)
    assert response.status_code == 200
    assert report["changes"][0]["changed"] == ["translations", "attributes", "specs"]

    product = await product_by_sku(api, admin, "KAN-16-PP")
    assert product["translations"]["ru"]["short_description"] is None
    assert product["translations"]["ru"]["description"] is None


async def test_pricing_transitions(api: AsyncClient, admin: Headers, catalog) -> None:
    data = build_workbook(
        {
            "Products": [
                product_row(
                    "KAN-16-PP",
                    slug="kanat-16-pp",
                    name_ru="Канат полипропиленовый 16 мм",
                    short_description_ru="Армированный канат для лазательных элементов",
                    description_ru="Подробное описание каната.",
                    categories="kanaty",
                    unit="m",
                    pricing_type="ON_REQUEST",
                    is_featured=True,
                ),
                product_row(
                    "SID-01",
                    slug="sidenie-kachelej",
                    name_ru="Сиденье качелей HDPE",
                    categories="krepleniya",
                    pricing_type="FIXED",
                ),
            ],
            "Prices": [{"sku": "SID-01", "min_qty": 1, "price": 7777.7}],
            "ProductAttributes": [
                {"sku": "KAN-16-PP", "attribute_code": "diameter", "value": 16},
                {"sku": "KAN-16-PP", "attribute_code": "material", "value": "pp"},
                {"sku": "KAN-16-PP", "attribute_code": "certified", "value": True},
                {"sku": "KAN-16-PP", "attribute_code": "internal_note", "value": "не показывать"},
            ],
            "ProductSpecs": [{"sku": "KAN-16-PP", "name": "Страна", "value": "Казахстан"}],
        }
    )
    report, response = await preview_and_commit(api, admin, data)
    assert response.status_code == 200, response.text
    assert {item["sku"]: item["changed"] for item in report["changes"]} == {
        "KAN-16-PP": ["pricing"],
        "SID-01": ["pricing"],
    }

    rope = (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16-pp")).json()["price"]
    assert rope["type"] == "ON_REQUEST" and rope["tiers"] == []
    seat = (await api.get(f"{PUBLIC_PRODUCTS}/sidenie-kachelej")).json()["price"]
    assert seat["type"] == "FIXED"
    assert Decimal(seat["price"]) == Decimal("7777.70")


async def test_existing_attributes_and_options_are_updated(
    api: AsyncClient, admin: Headers, catalog
) -> None:
    data = build_workbook(
        {
            "Attributes": [
                attribute_row("material", "OPTION", name_ru="Материал изделия", sort_order=7)
            ],
            "AttributeOptions": [
                {"attribute_code": "material", "slug": "pp", "value_ru": "ПП", "sort_order": 2},
                {
                    "attribute_code": "material",
                    "slug": "pe",
                    "value_ru": "Полиэтилен",
                    "sort_order": 3,
                },
            ],
        }
    )
    report, response = await preview_and_commit(api, admin, data)
    assert response.status_code == 200, response.text
    assert report["summary"]["attributes"] == {"create": 0, "update": 1, "unchanged": 0}
    assert report["summary"]["attribute_options"] == {"create": 1, "update": 1, "unchanged": 0}

    attribute = await attribute_by_code(api, admin, "material")
    assert attribute["names"] == {"ru": "Материал изделия"}
    assert attribute["sort_order"] == 7
    assert [(item["slug"], item["values"]["ru"]) for item in attribute["options"]] == [
        ("pp", "ПП"),
        ("pe", "Полиэтилен"),
    ]


async def test_category_move_rebuilds_subtree_paths(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    # Ветка «Канаты» переезжает под «Скрытую», вместе с новой подкатегорией.
    data = build_workbook(
        {
            "Categories": [
                category_row("kanaty", parent_slug="skrytaya", name_ru="Канаты"),
                category_row("kanaty-pp", parent_slug="kanaty"),
            ]
        }
    )
    report, response = await preview_and_commit(api, admin, data)
    assert response.status_code == 200, response.text
    assert report["summary"]["categories"] == {"create": 1, "update": 1, "unchanged": 0}

    committed_session.expire_all()
    categories = {
        category.slug: category
        for category in (await committed_session.execute(select(Category))).scalars().all()
    }
    hidden, ropes, child = categories["skrytaya"], categories["kanaty"], categories["kanaty-pp"]
    assert ropes.parent_id == hidden.id
    assert ropes.path == f"{hidden.id}.{ropes.id}" and ropes.depth == 1
    assert child.path == f"{hidden.id}.{ropes.id}.{child.id}" and child.depth == 2
    # Соседняя ветка не тронута.
    fasteners = categories["krepleniya"]
    assert fasteners.path == f"{categories['komplektuyushchie'].id}.{fasteners.id}"


async def test_category_attribute_links_are_replaced(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    ropes_id = catalog.categories["ropes"].id
    diameter = await attribute_by_code(api, admin, "diameter")
    assigned = await api.put(
        f"/api/v1/admin/categories/{ropes_id}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": diameter["id"]}]},
    )
    assert assigned.status_code == 200
    data = build_workbook(
        {
            "Categories": [
                category_row("kanaty", parent_slug="komplektuyushchie", name_ru="Канаты")
            ],
            "CategoryAttributes": [
                {
                    "category_slug": "kanaty",
                    "attribute_code": "material",
                    "sort_order": 0,
                    "is_required": True,
                }
            ],
        }
    )
    _, response = await preview_and_commit(api, admin, data)
    assert response.status_code == 200, response.text

    links = (await api.get(f"/api/v1/admin/categories/{ropes_id}/attributes", headers=admin)).json()
    assert [(item["code"], item["is_required"]) for item in links] == [("material", True)]


async def test_unchanged_products_are_not_touched(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    fastener_id = catalog.products["fastener"].id
    before = (
        await committed_session.execute(select(Product.updated_at).where(Product.id == fastener_id))
    ).scalar_one()

    data = build_workbook(
        {
            "Products": [
                product_row(
                    "KRP-M10",
                    slug="kreplenie-m10",
                    name_ru="Крепление М10 оцинкованное",
                    categories="krepleniya",
                    pricing_type="FIXED",
                ),
                product_row("NEW-2", categories="kanaty"),
            ],
            "Prices": [{"sku": "KRP-M10", "min_qty": 1, "price": 1200}],
        }
    )
    report, response = await preview_and_commit(api, admin, data)
    assert response.status_code == 200
    assert report["summary"]["products"] == {"create": 1, "update": 0, "unchanged": 1}

    committed_session.expire_all()
    after = (
        await committed_session.execute(
            select(Product.updated_at, Product.sync_source).where(Product.id == fastener_id)
        )
    ).one()
    assert after.updated_at == before
    assert after.sync_source == "manual"
    events = (
        (
            await committed_session.execute(
                select(AuditLog.action).where(
                    AuditLog.entity_type == "product", AuditLog.entity_id == fastener_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert events == []


# ============================================================== атомарность
async def test_failure_in_the_middle_rolls_back_everything(
    api: AsyncClient,
    admin: Headers,
    catalog,
    committed_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сбой на 87-м товаре не оставляет в каталоге первые 86."""
    count = 100
    data = build_workbook(
        {
            "Categories": [category_row("atomarnaya", parent_slug="komplektuyushchie")],
            "Products": [
                product_row(f"AT-{index:03d}", categories="atomarnaya") for index in range(count)
            ]
            + [
                product_row(
                    "KRP-M10",
                    slug="kreplenie-m10",
                    name_ru="Изменено",
                    categories="krepleniya",
                    pricing_type="FIXED",
                )
            ],
            "Prices": [{"sku": "KRP-M10", "min_qty": 1, "price": 1}],
            "ProductAttributes": [
                {"sku": f"AT-{index:03d}", "attribute_code": "diameter", "value": index}
                for index in range(count)
            ],
        }
    )
    report = await preview(api, admin, data)
    assert report["valid"], report["errors"]

    products_before = await count_rows(committed_session, Product)
    categories_before = await count_rows(committed_session, Category)

    import app.modules.imports.applier as applier_module

    original = applier_module.validate_attribute_value
    calls = {"count": 0}

    def failing(*args: Any, **kwargs: Any) -> None:
        calls["count"] += 1
        if calls["count"] == 87:
            raise AttributeValueTypeMismatchError
        original(*args, **kwargs)

    monkeypatch.setattr(applier_module, "validate_attribute_value", failing)

    response = await upload(api, commit_url(report["job"]["uuid"]), admin, data)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "attribute_value_type_mismatch"
    assert calls["count"] == 87

    committed_session.expire_all()
    assert await count_rows(committed_session, Product) == products_before
    assert await count_rows(committed_session, Category) == categories_before
    fastener = await product_by_sku(api, admin, "KRP-M10")
    assert fastener["translations"]["ru"]["name"] == "Крепление М10 оцинкованное"
    assert Decimal((await pricing_of(api, admin, fastener["id"]))["tiers"][0]["price"]) == Decimal(
        "1200.00"
    )

    job = (await api.get(f"{IMPORTS}/{report['job']['uuid']}", headers=admin)).json()
    assert job["status"] == "FAILED"
    assert job["failure_code"] == "attribute_value_type_mismatch"
    assert job["can_commit"] is False


async def test_unique_violation_race_is_translated_and_rolled_back(
    api: AsyncClient,
    admin: Headers,
    catalog,
    committed_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Конкурент занял slug уже после повторной проверки — отвечает база."""
    data = build_workbook(
        {
            "Products": [
                product_row("RACE-1", categories="kanaty"),
                product_row("RACE-2", slug="svobodnyj", categories="kanaty"),
            ]
        }
    )
    report = await preview(api, admin, data)
    assert report["valid"]

    # «Конкурент» создаёт товар с тем же slug через админку...
    created = await api.post(
        PRODUCTS,
        headers=admin,
        json={"sku": "OTHER-1", "slug": "svobodnyj", "translations": {"ru": {"name": "Другой"}}},
    )
    assert created.status_code == 201
    # ...а снимок каталога его «не видит»: так выглядит гонка между
    # проверкой и записью.
    original = CatalogSnapshotLoader._load_product_refs

    async def stale(self: CatalogSnapshotLoader, snapshot: Any) -> None:
        await original(self, snapshot)
        snapshot.product_refs = [ref for ref in snapshot.product_refs if ref.sku != "OTHER-1"]
        assert all(isinstance(ref, ProductRef) for ref in snapshot.product_refs)

    monkeypatch.setattr(CatalogSnapshotLoader, "_load_product_refs", stale)

    response = await upload(api, commit_url(report["job"]["uuid"]), admin, data)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "product_slug_exists"

    committed_session.expire_all()
    skus = set((await committed_session.execute(select(Product.sku))).scalars().all())
    assert "RACE-1" not in skus and "RACE-2" not in skus

    job = (await api.get(f"{IMPORTS}/{report['job']['uuid']}", headers=admin)).json()
    assert (job["status"], job["failure_code"]) == ("FAILED", "product_slug_exists")


# ================================================== повторная проверка и порядок
async def test_commit_revalidates_against_current_catalog(
    api: AsyncClient, admin: Headers, catalog
) -> None:
    data = build_workbook(
        {"Products": [product_row("REV-1", slug="zanyatyj", categories="kanaty")]}
    )
    report = await preview(api, admin, data)
    assert report["valid"]

    await api.post(
        PRODUCTS,
        headers=admin,
        json={"sku": "OTHER-2", "slug": "zanyatyj", "translations": {"ru": {"name": "Другой"}}},
    )

    response = await upload(api, commit_url(report["job"]["uuid"]), admin, data)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "import_validation_failed"
    assert error["details"]["error_count"] == 1
    assert error["details"]["errors"][0]["code"] == "slug_taken"

    job = (await api.get(f"{IMPORTS}/{report['job']['uuid']}", headers=admin)).json()
    assert job["status"] == "FAILED"
    assert job["failure_code"] == "import_validation_failed"
    assert job["errors"][0]["code"] == "slug_taken"

    again = await upload(api, commit_url(report["job"]["uuid"]), admin, data)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "import_failed"


async def test_repeated_commit_is_rejected(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    data = build_workbook({"Products": [product_row("ONCE-1", categories="kanaty")]})
    report, first = await preview_and_commit(api, admin, data)
    assert first.status_code == 200

    second = await upload(api, commit_url(report["job"]["uuid"]), admin, data)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "import_already_committed"

    committed_session.expire_all()
    skus = (
        await committed_session.execute(select(Product.sku).where(Product.sku == "ONCE-1"))
    ).all()
    assert len(skus) == 1


async def test_commit_requires_the_previewed_file(
    api: AsyncClient, admin: Headers, catalog
) -> None:
    data = build_workbook({"Products": [product_row("SAME-1", categories="kanaty")]})
    other = build_workbook({"Products": [product_row("SAME-2", categories="kanaty")]})
    report = await preview(api, admin, data)

    response = await upload(api, commit_url(report["job"]["uuid"]), admin, other)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "import_file_mismatch"

    # Предпросмотр остаётся действующим — с правильным файлом всё пройдёт.
    response = await upload(api, commit_url(report["job"]["uuid"]), admin, data)
    assert response.status_code == 200


async def test_invalid_preview_cannot_be_committed(api: AsyncClient, admin: Headers) -> None:
    data = build_workbook({"Products": [product_row("bad sku")]})
    report = await preview(api, admin, data)
    assert report["valid"] is False

    response = await upload(api, commit_url(report["job"]["uuid"]), admin, data)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "import_not_valid"


async def test_expired_preview_cannot_be_committed(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    data = build_workbook({"Products": [product_row("OLD-1", categories="kanaty")]})
    report = await preview(api, admin, data)
    await committed_session.execute(
        update(ImportJob)
        .where(ImportJob.uuid == report["job"]["uuid"])
        .values(created_at=datetime.now(UTC) - timedelta(hours=25))
    )
    await committed_session.commit()

    response = await upload(api, commit_url(report["job"]["uuid"]), admin, data)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "import_preview_expired"


async def test_commit_of_unknown_job(api: AsyncClient, admin: Headers) -> None:
    data = build_workbook({"Products": [product_row("X-1")]})
    response = await upload(api, commit_url("00000000-0000-0000-0000-000000000000"), admin, data)
    assert response.status_code == 404


async def test_concurrent_commits_apply_once(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    data = build_workbook(
        {"Products": [product_row(f"CC-{index}", categories="kanaty") for index in range(20)]}
    )
    report = await preview(api, admin, data)
    url = commit_url(report["job"]["uuid"])

    first, second = await asyncio.gather(
        upload(api, url, admin, data), upload(api, url, admin, data)
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]

    committed_session.expire_all()
    created = (
        (await committed_session.execute(select(Product.sku).where(Product.sku.like("CC-%"))))
        .scalars()
        .all()
    )
    assert len(created) == 20


# ===================================================================== аудит
async def test_commit_is_audited(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    data = build_workbook(
        {
            "Products": [
                product_row("AUD-1", categories="kanaty", pricing_type="FIXED"),
                product_row(
                    "KRP-M10",
                    slug="kreplenie-m10",
                    name_ru="Крепление М10 (аудит)",
                    categories="krepleniya",
                    pricing_type="FIXED",
                ),
            ],
            "Prices": [
                {"sku": "AUD-1", "min_qty": 1, "price": 10},
                {"sku": "KRP-M10", "min_qty": 1, "price": 1200},
            ],
        }
    )
    report, response = await preview_and_commit(api, admin, data)
    assert response.status_code == 200
    job_uuid = report["job"]["uuid"]

    entries = (
        (
            await committed_session.execute(
                select(AuditLog).where(~AuditLog.action.like("auth.%")).order_by(AuditLog.id)
            )
        )
        .scalars()
        .all()
    )
    by_action: dict[str, list[AuditLog]] = {}
    for entry in entries:
        by_action.setdefault(entry.action, []).append(entry)

    assert set(by_action) == {
        "catalog_import.previewed",
        "catalog_import.committed",
        "catalog.product_created",
        "catalog.product_updated",
        "pricing.updated",
    }
    committed = by_action["catalog_import.committed"][0]
    assert committed.entity_type == "import_job"
    assert committed.changes["products"] == {"create": 1, "update": 1, "unchanged": 0}
    assert committed.user_id is not None

    created = by_action["catalog.product_created"][0]
    assert created.actor == "import"
    assert created.changes["sku"] == {"old": None, "new": "AUD-1"}
    assert created.changes["import_job"] == job_uuid

    updated = by_action["catalog.product_updated"][0]
    assert updated.changes["translations"] == {"old": None, "new": ["ru"]}
    # Цена крепления не менялась — события о ней нет; у нового товара есть.
    pricing = by_action["pricing.updated"]
    assert len(pricing) == 1
    assert pricing[0].changes["new"]["tiers"] == [
        {"min_qty": "1.000", "max_qty": None, "price": "10.00"}
    ]
