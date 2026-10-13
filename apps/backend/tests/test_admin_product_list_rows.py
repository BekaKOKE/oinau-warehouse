"""Строки списка товаров админки: обложка, цена и наличие (G6).

Поля добавлены к существующему ответу GET /admin/products; прежние поля
и фильтры не меняются — это проверяют тесты test_admin_products.py.
"""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.inventory.models import Stock
from app.modules.media.enums import MediaStatus
from app.modules.media.models import ProductImage
from app.modules.pricing.models import PriceTier
from app.modules.users.enums import UserRole
from tests.catalog_fixtures import CatalogFixture
from tests.conftest import Headers
from tests.factories import make_product
from tests.helpers import count_queries
from tests.media_helpers import make_media

PRODUCTS = "/api/v1/admin/products"


async def _rows(api: AsyncClient, headers: Headers, **params: object) -> dict[str, dict]:
    response = await api.get(PRODUCTS, headers=headers, params={"page_size": 60, **params})
    assert response.status_code == 200, response.text
    return {item["sku"]: item for item in response.json()["items"]}


async def test_rows_carry_price_from_public_price_list(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    rows = await _rows(api, admin)

    rope = rows["KAN-16-PP"]
    assert rope["pricing_type"] == "TIERED"
    assert rope["currency"] == "KZT"
    # Дилерская ступень 1111.00 в минимум не попадает.
    assert rope["min_price"] == "2600.00"
    assert rope["max_price"] == "3500.00"

    assert rows["KRP-M10"]["min_price"] == "1200.00"
    assert rows["SID-01"]["pricing_type"] == "ON_REQUEST"
    assert rows["SID-01"]["min_price"] is None
    # FIXED без ступеней — цены нет, а не ноль.
    assert rows["DRAFT-1"]["min_price"] is None


async def test_rows_carry_public_availability_matching_resolver(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    draft = catalog.products["draft"]
    draft.stock_display_override = "IN_STOCK"
    committed_session.add(draft)
    await committed_session.commit()

    rows = await _rows(api, admin)
    assert rows["KAN-16-PP"]["public_availability"] == "IN_STOCK"
    assert rows["KRP-M10"]["public_availability"] == "OUT_OF_STOCK"
    assert rows["SID-01"]["public_availability"] == "ON_REQUEST"
    assert rows["DRAFT-1"]["public_availability"] == "IN_STOCK"
    assert rows["DRAFT-1"]["stock_display_override"] == "IN_STOCK"

    for row in rows.values():
        single = (await api.get(f"{PRODUCTS}/{row['id']}/availability", headers=admin)).json()
        assert row["public_availability"] == single["public_availability"], row["sku"]


async def test_rows_carry_ready_main_image_thumbnail_only(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    ready = await make_media(committed_session)
    extra = await make_media(committed_session)
    processing = await make_media(committed_session, status=MediaStatus.PROCESSING)
    rope, fastener = catalog.products["rope"], catalog.products["fastener"]
    committed_session.add_all(
        [
            ProductImage(product_id=rope.id, media_file_id=ready.id, is_main=True, sort_order=0),
            ProductImage(product_id=rope.id, media_file_id=extra.id, sort_order=1),
            ProductImage(product_id=fastener.id, media_file_id=processing.id, is_main=True),
        ]
    )
    await committed_session.commit()

    rows = await _rows(api, admin)
    assert rows["KAN-16-PP"]["images_count"] == 2
    url = rows["KAN-16-PP"]["main_image_url"]
    assert url is not None
    assert url.endswith(f"products/{ready.uuid}/variants/thumb.webp")
    assert "original" not in url
    # Главное фото ещё обрабатывается: ссылки нет, но счётчик есть.
    assert rows["KRP-M10"]["images_count"] == 1
    assert rows["KRP-M10"]["main_image_url"] is None
    assert rows["SID-01"]["images_count"] == 0
    assert rows["SID-01"]["main_image_url"] is None


async def test_rows_still_carry_existing_fields_and_filters(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    body = (
        await api.get(PRODUCTS, headers=admin, params={"include_deleted": True, "sku": "x"})
    ).json()
    removed = next(item for item in body["items"] if item["sku"] == "DEL-1")
    assert removed["deleted_at"] is not None
    for field in ("slug", "name", "status", "is_publicly_visible", "primary_category", "unit"):
        assert field in removed
    assert removed["public_availability"] in ("IN_STOCK", "OUT_OF_STOCK", "ON_REQUEST")


async def test_extras_do_not_add_queries_per_row(
    api: AsyncClient,
    admin: Headers,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
    test_engine: AsyncEngine,
) -> None:
    with count_queries(test_engine) as small:
        await api.get(PRODUCTS, headers=admin, params={"page_size": 60})

    for index in range(20):
        product = await make_product(committed_session, sku=f"BULK-{index}", slug=f"bulk-{index}")
        media = await make_media(committed_session)
        committed_session.add_all(
            [
                ProductImage(product_id=product.id, media_file_id=media.id, is_main=True),
                PriceTier(
                    product_id=product.id,
                    price_list_id=catalog.public_price_list.id,
                    min_qty=Decimal("1"),
                    price=Decimal("10.50"),
                ),
                Stock(
                    product_id=product.id,
                    warehouse_id=catalog.warehouse.id,
                    quantity=Decimal("3"),
                ),
            ]
        )
    await committed_session.commit()

    with count_queries(test_engine) as large:
        body = (await api.get(PRODUCTS, headers=admin, params={"page_size": 60})).json()

    assert body["total"] == 25
    assert len(large) == len(small)


async def test_empty_page_does_not_fail(api: AsyncClient, admin: Headers) -> None:
    response = await api.get(PRODUCTS, headers=admin, params={"search": "нет-такого"})
    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_manager_reads_rows_but_cannot_write(api: AsyncClient, login_as) -> None:
    headers = await login_as(UserRole.MANAGER)
    assert (await api.get(PRODUCTS, headers=headers)).status_code == 200
    created = await api.post(
        PRODUCTS,
        headers=headers,
        json={"sku": "M-1", "slug": "m-1", "translations": {"ru": {"name": "М"}}},
    )
    assert created.status_code == 403
