"""Список остатков по товарам для страницы «Склад» админки."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.inventory.models import Stock, Warehouse
from app.modules.users.enums import UserRole
from tests.catalog_fixtures import CatalogFixture
from tests.conftest import Headers
from tests.factories import make_product
from tests.helpers import count_queries

STOCK = "/api/v1/admin/stock"
PRODUCTS = "/api/v1/admin/products"


def skus(body: dict) -> list[str]:
    return [item["sku"] for item in body["items"]]


async def _list(api: AsyncClient, headers: Headers, **params: object) -> dict:
    response = await api.get(STOCK, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ============================================================== содержимое
async def test_lists_live_products_with_exact_admin_stock(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    body = await _list(api, admin)

    # Удалённый товар в списке не показывается; порядок по артикулу.
    assert skus(body) == ["DRAFT-1", "KAN-16-PP", "KRP-M10", "OFF-1", "SID-01"]
    assert body["total"] == 5

    rope = next(item for item in body["items"] if item["sku"] == "KAN-16-PP")
    assert rope["name"] == "Канат полипропиленовый 16 мм"
    assert rope["status"] == "PUBLISHED"
    assert rope["is_active"] is True
    assert rope["pricing_type"] == "TIERED"
    assert rope["unit"] == "m"
    assert rope["public_availability"] == "IN_STOCK"
    assert rope["stock_updated_at"] is not None

    [entry] = rope["entries"]
    assert entry["warehouse_code"] == "main"
    assert entry["warehouse_is_active"] is True
    # Decimal уходит строкой с точностью колонки — никаких float.
    assert entry["quantity"] == "152.500"
    assert entry["reserved"] == "0.000"
    assert entry["available"] == "152.500"
    assert entry["sync_source"] == "manual"
    assert {"synced_at", "external_id", "updated_at"} <= set(entry)
    assert isinstance(rope["total_available"], str)
    assert Decimal(rope["total_available"]) == Decimal("152.5")


async def test_product_without_stock_rows_shows_active_warehouses_with_zero(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    seat = next(item for item in (await _list(api, admin))["items"] if item["sku"] == "SID-01")
    assert [entry["warehouse_code"] for entry in seat["entries"]] == ["main"]
    assert Decimal(seat["entries"][0]["quantity"]) == 0
    assert seat["entries"][0]["sync_source"] is None
    assert seat["stock_updated_at"] is None
    assert seat["public_availability"] == "ON_REQUEST"


async def test_list_items_match_per_product_stock_endpoint(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    """Список и карточка остатков считают одинаково: разные склады,
    резерв, отключённый склад с остатком, переопределение."""
    closed = Warehouse(code="closed", name="Закрытый", is_active=False, external_id="1c-wh-9")
    reserve = Warehouse(code="reserve", name="Резервный")
    committed_session.add_all([closed, reserve])
    await committed_session.flush()
    rope_id = catalog.products["rope"].id
    committed_session.add_all(
        [
            Stock(product_id=rope_id, warehouse_id=closed.id, quantity=Decimal("40")),
            Stock(
                product_id=rope_id,
                warehouse_id=reserve.id,
                quantity=Decimal("10.250"),
                reserved=Decimal("2.125"),
                sync_source="1c",
                external_id="1c-stock-1",
                synced_at=datetime.now(UTC),
            ),
        ]
    )
    catalog.products["inactive"].stock_display_override = "ON_REQUEST"
    committed_session.add(catalog.products["inactive"])
    await committed_session.commit()

    for item in (await _list(api, admin))["items"]:
        single = (await api.get(f"{PRODUCTS}/{item['product_id']}/stock", headers=admin)).json()
        assert {key: item[key] for key in single} == single, item["sku"]

    rope = next(i for i in (await _list(api, admin))["items"] if i["product_id"] == rope_id)
    # Отключённый склад виден, потому что на нём лежит товар, но в итоги не входит.
    assert [e["warehouse_code"] for e in rope["entries"]] == ["closed", "main", "reserve"]
    assert rope["total_quantity"] == "162.750"
    assert rope["total_reserved"] == "2.125"
    assert rope["total_available"] == "160.625"
    reserve_entry = rope["entries"][2]
    assert reserve_entry["sync_source"] == "1c"
    assert reserve_entry["external_id"] == "1c-stock-1"
    assert reserve_entry["available"] == "8.125"


# ================================================================ фильтры
async def test_filter_by_public_availability(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    draft = catalog.products["draft"]
    draft.stock_display_override = "IN_STOCK"
    committed_session.add(draft)
    await committed_session.commit()

    assert skus(await _list(api, admin, availability="IN_STOCK")) == ["DRAFT-1", "KAN-16-PP"]
    assert skus(await _list(api, admin, availability="OUT_OF_STOCK")) == ["KRP-M10", "OFF-1"]
    assert skus(await _list(api, admin, availability="ON_REQUEST")) == ["SID-01"]


async def test_fully_reserved_stock_is_out_of_stock(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    await api.put(
        f"{PRODUCTS}/{catalog.products['rope'].id}/stock",
        headers=admin,
        json={
            "items": [
                {"warehouse_id": catalog.warehouse.id, "quantity": "5", "reserved": "5"},
            ]
        },
    )
    assert "KAN-16-PP" in skus(await _list(api, admin, availability="OUT_OF_STOCK"))


async def test_filter_by_search_warehouse_source_and_active(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    other = Warehouse(code="astana", name="Астана")
    committed_session.add(other)
    await committed_session.flush()
    seat = catalog.products["seat"]
    seat.external_id = "1C-00042"
    committed_session.add(seat)
    committed_session.add(
        Stock(product_id=seat.id, warehouse_id=other.id, quantity=Decimal("3"), sync_source="excel")
    )
    await committed_session.commit()

    assert skus(await _list(api, admin, search="Крепление М10")) == ["KRP-M10"]
    assert skus(await _list(api, admin, search="kan-16")) == ["KAN-16-PP"]
    assert skus(await _list(api, admin, search="1c-000")) == ["SID-01"]
    assert skus(await _list(api, admin, warehouse_id=other.id)) == ["SID-01"]
    assert skus(await _list(api, admin, sync_source="excel")) == ["SID-01"]
    assert skus(await _list(api, admin, sync_source="1c")) == []
    assert skus(await _list(api, admin, is_active=False)) == ["OFF-1"]


# ======================================================= сортировка, страницы
async def test_sort_by_available_name_and_updated(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    fastener_stock = await committed_session.get(
        Stock, (catalog.products["fastener"].id, catalog.warehouse.id)
    )
    assert fastener_stock is not None
    fastener_stock.quantity = Decimal("7")
    fastener_stock.updated_at = datetime.now(UTC) + timedelta(minutes=5)
    await committed_session.commit()

    by_available = skus(await _list(api, admin, sort="available_desc"))
    assert by_available[:2] == ["KAN-16-PP", "KRP-M10"]
    assert skus(await _list(api, admin, sort="available_asc"))[-2:] == ["KRP-M10", "KAN-16-PP"]
    assert skus(await _list(api, admin, sort="updated"))[:2] == ["KRP-M10", "KAN-16-PP"]
    assert skus(await _list(api, admin, sort="name")) == [
        "KAN-16-PP",
        "KRP-M10",
        "OFF-1",
        "SID-01",
        "DRAFT-1",
    ]


async def test_pagination(api: AsyncClient, admin: Headers, catalog: CatalogFixture) -> None:
    first = await _list(api, admin, page_size=2)
    third = await _list(api, admin, page_size=2, page=3)
    assert first["total"] == 5
    assert first["pages"] == 3
    assert len(first["items"]) == 2
    assert skus(third) == ["SID-01"]


async def test_rejects_invalid_parameters(api: AsyncClient, admin: Headers) -> None:
    for params in (
        {"availability": "MAYBE"},
        {"sync_source": "ftp"},
        {"sort": "price"},
        {"warehouse_id": 0},
        {"page_size": 61},
    ):
        assert (await api.get(STOCK, headers=admin, params=params)).status_code == 422, params


async def test_list_is_read_only(api: AsyncClient, admin: Headers) -> None:
    """Правка остатков — только поштучно через PUT /products/{id}/stock."""
    assert (await api.post(STOCK, headers=admin, json={})).status_code == 405
    assert (await api.put(STOCK, headers=admin, json={})).status_code == 405


async def test_query_count_is_fixed(
    api: AsyncClient,
    admin: Headers,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
    test_engine: AsyncEngine,
) -> None:
    """Товары, склады и строки остатков — по одному запросу на страницу."""
    with count_queries(test_engine) as small:
        await api.get(STOCK, headers=admin)

    extra = [Warehouse(code=f"wh-{index}", name=f"Склад {index}") for index in range(4)]
    committed_session.add_all(extra)
    await committed_session.flush()
    for _ in range(20):
        product = await make_product(committed_session)
        committed_session.add_all(
            Stock(product_id=product.id, warehouse_id=warehouse.id, quantity=Decimal("1"))
            for warehouse in extra
        )
    await committed_session.commit()

    with count_queries(test_engine) as large:
        body = (await api.get(STOCK, headers=admin)).json()

    assert len(body["items"]) == 24
    assert len(large) == len(small)


# ================================================================== права
@pytest.mark.parametrize("role", list(UserRole))
async def test_every_catalog_reader_can_read_stock(
    api: AsyncClient, login_as, role: UserRole
) -> None:
    """Чтение — catalog.read, как у GET /products/{id}/stock. Менять
    остатки по-прежнему может только stock.write, и не через этот список."""
    headers = await login_as(role)
    assert (await api.get(STOCK, headers=headers)).status_code == 200


async def test_stock_list_requires_admin_authentication(api: AsyncClient, customer_headers) -> None:
    assert (await api.get(STOCK)).status_code == 401
    _, customer = await customer_headers()
    assert (await api.get(STOCK, headers=customer)).status_code == 401


async def test_public_catalog_still_hides_exact_stock(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    """Новый admin-список не меняет публичный контракт: там только статус."""
    body = (await api.get("/api/v1/public/products")).json()
    text = str(body)
    assert "152.5" not in text
    assert "quantity" not in text
