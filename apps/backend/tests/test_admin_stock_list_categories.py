"""Основная категория товара в списке остатков (G9, этап 8F).

Странице «Склад» нужна колонка категории. Без поля в строке списка её
пришлось бы добирать отдельным запросом на каждый товар.
"""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.catalog.models import ProductCategory
from app.modules.inventory.models import Stock
from tests.catalog_fixtures import CatalogFixture
from tests.conftest import Headers
from tests.factories import make_product
from tests.helpers import count_queries

STOCK = "/api/v1/admin/stock"


async def _items(api: AsyncClient, headers: Headers, **params: object) -> dict[str, dict]:
    response = await api.get(STOCK, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return {item["sku"]: item for item in response.json()["items"]}


async def test_row_has_primary_category_in_product_list_shape(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    items = await _items(api, admin)
    rope = items["KAN-16-PP"]["primary_category"]
    assert rope == {
        "category_id": catalog.categories["ropes"].id,
        "slug": "kanaty",
        "name": "Канаты",
        "is_primary": True,
        "sort_order": 0,
        "is_active": True,
    }
    assert items["SID-01"]["primary_category"]["slug"] == "krepleniya"

    # Та же категория, что показывает список товаров.
    products = (await api.get("/api/v1/admin/products", headers=admin)).json()["items"]
    by_sku = {item["sku"]: item for item in products}
    assert by_sku["KAN-16-PP"]["primary_category"] == rope


async def test_product_without_primary_category_has_null(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    orphan = await make_product(committed_session, sku="NOCAT-1")
    await committed_session.commit()
    assert orphan.id

    items = await _items(api, admin, search="NOCAT-1")
    assert items["NOCAT-1"]["primary_category"] is None


async def test_secondary_category_is_not_reported_as_primary(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    product = await make_product(committed_session, sku="SECOND-1")
    committed_session.add(
        ProductCategory(
            product_id=product.id,
            category_id=catalog.categories["hidden"].id,
            is_primary=False,
        )
    )
    await committed_session.commit()

    items = await _items(api, admin, search="SECOND-1")
    assert items["SECOND-1"]["primary_category"] is None


async def test_category_does_not_add_queries_per_row(
    api: AsyncClient,
    admin: Headers,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
    test_engine: AsyncEngine,
) -> None:
    with count_queries(test_engine) as small:
        await api.get(STOCK, headers=admin)

    categories = list(catalog.categories.values())
    for index in range(20):
        product = await make_product(committed_session)
        category = categories[index % len(categories)]
        committed_session.add_all(
            [
                ProductCategory(product_id=product.id, category_id=category.id, is_primary=True),
                Stock(
                    product_id=product.id,
                    warehouse_id=catalog.warehouse.id,
                    quantity=Decimal("1"),
                ),
            ]
        )
    await committed_session.commit()

    with count_queries(test_engine) as large:
        body = (await api.get(STOCK, headers=admin)).json()

    assert len(body["items"]) == 24
    assert all(item["primary_category"] for item in body["items"] if item["sku"] != "SID-01")
    assert len(large) == len(small)
