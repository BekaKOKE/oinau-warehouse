"""Сводка каталога для дашборда: счётчики, правило наличия, права, число запросов."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.catalog.enums import ProductStatus
from app.modules.inventory.models import Stock, Warehouse
from app.modules.media.enums import MediaStatus
from app.modules.media.models import ProductImage
from app.modules.pricing.enums import PricingType
from app.modules.pricing.models import PriceTier
from app.modules.users.enums import UserRole
from tests.catalog_fixtures import CatalogFixture
from tests.conftest import Headers
from tests.factories import make_product
from tests.helpers import count_queries
from tests.media_helpers import make_media

SUMMARY = "/api/v1/admin/catalog/summary"
PRODUCTS = "/api/v1/admin/products"

# Роли с правом catalog.read. У кладовщика (WAREHOUSE) его нет.
CATALOG_READERS = [
    UserRole.SUPERADMIN,
    UserRole.ADMIN,
    UserRole.MANAGER,
    UserRole.CONTENT_MANAGER,
    UserRole.VIEWER,
]


async def test_empty_catalog_returns_zeros(api: AsyncClient, admin: Headers) -> None:
    response = await api.get(SUMMARY, headers=admin)
    assert response.status_code == 200
    body = response.json()
    for section in body.values():
        assert all(value == 0 for value in section.values()), section


async def test_counts_products_categories_and_availability(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    """Фикстура: канат (TIERED, остаток 152.5, избранный), крепление
    (FIXED, остаток 0), сиденье (ON_REQUEST), черновик, отключённый
    и удалённый товары; четыре категории, одна из них отключена."""
    body = (await api.get(SUMMARY, headers=admin)).json()

    assert body["products"] == {
        "total": 5,
        "active": 4,
        "inactive": 1,
        "publicly_visible": 3,
        "featured": 1,
        "draft": 1,
        "published": 4,
        "archived": 0,
        "deleted": 1,
    }
    assert body["content"] == {
        "without_images": 5,
        "without_ready_images": 5,
        # Черновик и отключённый — FIXED без ступеней; удалённый не считается.
        "without_price": 2,
        "price_on_request": 1,
    }
    assert body["availability"] == {
        "in_stock": 1,
        "out_of_stock": 3,
        "on_request": 1,
        "overridden": 0,
    }
    assert body["categories"] == {"total": 4, "active": 3, "deleted": 0}


async def test_images_count_only_ready_files_as_visible(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    ready = await make_media(committed_session)
    processing = await make_media(committed_session, status=MediaStatus.PROCESSING)
    committed_session.add_all(
        [
            ProductImage(
                product_id=catalog.products["rope"].id, media_file_id=ready.id, is_main=True
            ),
            ProductImage(
                product_id=catalog.products["fastener"].id,
                media_file_id=processing.id,
                is_main=True,
            ),
            # Изображение удалённого товара не влияет на счётчики.
            ProductImage(product_id=catalog.products["removed"].id, media_file_id=ready.id),
        ]
    )
    await committed_session.commit()

    content = (await api.get(SUMMARY, headers=admin)).json()["content"]
    assert content["without_images"] == 3
    # У крепления файл ещё обрабатывается — посетитель картинку не видит.
    assert content["without_ready_images"] == 4


async def test_price_counts_only_public_price_list(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    """Дилерская ступень не делает товар «с ценой» для витрины."""
    dealer_only = await make_product(committed_session, pricing_type=PricingType.FIXED.value)
    committed_session.add(
        PriceTier(
            product_id=dealer_only.id,
            price_list_id=catalog.dealer_price_list.id,
            min_qty=Decimal("1"),
            price=Decimal("999.99"),
        )
    )
    await committed_session.commit()
    assert (await api.get(SUMMARY, headers=admin)).json()["content"]["without_price"] == 3

    catalog.public_price_list.is_active = False
    committed_session.add(catalog.public_price_list)
    await committed_session.commit()
    # Публичный прайс отключён — без цены все, кроме «по запросу».
    assert (await api.get(SUMMARY, headers=admin)).json()["content"]["without_price"] == 5


async def test_availability_follows_override_reserve_and_inactive_warehouse(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    products = catalog.products
    # Черновик вручную показан «в наличии».
    draft = products["draft"]
    draft.stock_display_override = "IN_STOCK"
    committed_session.add(draft)
    # Весь остаток каната зарезервирован — свободного нет.
    rope_stock = await committed_session.get(Stock, (products["rope"].id, catalog.warehouse.id))
    assert rope_stock is not None
    rope_stock.reserved = rope_stock.quantity
    # У крепления остаток есть, но только на отключённом складе.
    closed = Warehouse(code="closed", name="Закрытый склад", is_active=False)
    committed_session.add(closed)
    await committed_session.flush()
    committed_session.add(
        Stock(product_id=products["fastener"].id, warehouse_id=closed.id, quantity=Decimal("40"))
    )
    await committed_session.commit()

    assert (await api.get(SUMMARY, headers=admin)).json()["availability"] == {
        "in_stock": 1,
        "out_of_stock": 3,
        "on_request": 1,
        "overridden": 1,
    }


async def test_availability_matches_per_product_resolver(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    """SQL-правило сводки обязано совпадать с resolve_availability,
    которым считает статус карточка остатков (и витрина)."""
    products = catalog.products
    products["seat"].stock_display_override = "OUT_OF_STOCK"
    committed_session.add(products["seat"])
    committed_session.add(
        Stock(
            product_id=products["draft"].id,
            warehouse_id=catalog.warehouse.id,
            quantity=Decimal("0.001"),
        )
    )
    await committed_session.commit()

    expected = {"IN_STOCK": 0, "OUT_OF_STOCK": 0, "ON_REQUEST": 0}
    for key, product in products.items():
        if key == "removed":
            continue
        availability = (
            await api.get(f"{PRODUCTS}/{product.id}/availability", headers=admin)
        ).json()["public_availability"]
        expected[availability] += 1

    summary = (await api.get(SUMMARY, headers=admin)).json()["availability"]
    assert {
        "IN_STOCK": summary["in_stock"],
        "OUT_OF_STOCK": summary["out_of_stock"],
        "ON_REQUEST": summary["on_request"],
    } == expected


async def test_archived_and_deleted_categories(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    await make_product(committed_session, status=ProductStatus.ARCHIVED.value)
    await committed_session.commit()
    deleted = await api.delete(
        f"/api/v1/admin/categories/{catalog.categories['hidden'].id}", headers=admin
    )
    assert deleted.status_code == 204

    body = (await api.get(SUMMARY, headers=admin)).json()
    assert body["products"]["archived"] == 1
    assert body["categories"] == {"total": 3, "active": 3, "deleted": 1}


async def test_summary_is_one_query_regardless_of_catalog_size(
    api: AsyncClient,
    admin: Headers,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
    test_engine: AsyncEngine,
) -> None:
    """Счётчики считаются в базе: без выгрузки товаров и N+1."""
    with count_queries(test_engine) as small:
        await api.get(SUMMARY, headers=admin)

    for _ in range(25):
        await make_product(committed_session)
    await committed_session.commit()

    with count_queries(test_engine) as large:
        body = (await api.get(SUMMARY, headers=admin)).json()

    assert body["products"]["total"] == 30
    assert len(large) == len(small)
    aggregate = [statement for statement in large if "FILTER (WHERE" in statement]
    assert len(aggregate) == 1
    # Помимо проверки сотрудника по токену — ровно один запрос сводки.
    assert all("products" not in s for s in large if s not in aggregate)


async def test_summary_exposes_no_exact_quantities(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    text = (await api.get(SUMMARY, headers=admin)).text
    assert "152.5" not in text
    assert "quantity" not in text


# ================================================================== права
@pytest.mark.parametrize("role", CATALOG_READERS)
async def test_summary_available_to_every_catalog_reader(
    api: AsyncClient, login_as, role: UserRole
) -> None:
    """catalog.read есть у этих пяти ролей — сводка доступна каждой из них."""
    headers = await login_as(role)
    assert (await api.get(SUMMARY, headers=headers)).status_code == 200


async def test_summary_requires_authentication(api: AsyncClient, customer_headers) -> None:
    assert (await api.get(SUMMARY)).status_code == 401
    _, customer = await customer_headers()
    assert (await api.get(SUMMARY, headers=customer)).status_code == 401


async def test_summary_does_not_shadow_excel_routes(api: AsyncClient, admin: Headers) -> None:
    """/catalog/summary живёт рядом с /catalog/export и /catalog/imports."""
    listing = await api.get("/api/v1/admin/catalog/imports", headers=admin)
    assert listing.status_code == 200
