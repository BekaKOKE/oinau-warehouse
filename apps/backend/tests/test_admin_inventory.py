"""Интеграционные тесты Admin API складов и остатков."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.modules.audit.models import AuditLog
from app.modules.geo.models import Region
from app.modules.users.enums import UserRole
from tests.conftest import Headers
from tests.helpers import count_queries

PRODUCTS = "/api/v1/admin/products"
WAREHOUSES = "/api/v1/admin/warehouses"
PUBLIC_PRODUCTS = "/api/v1/public/products"


def stock_url(product_id: int) -> str:
    return f"{PRODUCTS}/{product_id}/stock"


def availability_url(product_id: int) -> str:
    return f"{PRODUCTS}/{product_id}/availability"


@pytest.fixture
async def region(committed_session: AsyncSession) -> Region:
    item = Region(code="almaty", name="Алматы")
    committed_session.add(item)
    await committed_session.commit()
    await committed_session.refresh(item)
    return item


@pytest.fixture
async def warehouse(api: AsyncClient, admin: Headers, region: Region) -> dict:
    response = await api.post(
        WAREHOUSES,
        headers=admin,
        json={"code": "main", "name": "Основной склад", "region_id": region.id},
    )
    return response.json()


@pytest.fixture
async def product(api: AsyncClient, admin: Headers) -> dict:
    response = await api.post(
        PRODUCTS,
        headers=admin,
        json={
            "sku": "KAN-16",
            "slug": "kanat-16",
            "status": "PUBLISHED",
            "unit": "m",
            "translations": {"ru": {"name": "Канат 16 мм"}},
        },
    )
    return response.json()


# =============================================================== склады
async def test_create_and_list_warehouses(api: AsyncClient, admin: Headers, region: Region) -> None:
    created = await api.post(
        WAREHOUSES,
        headers=admin,
        json={"code": "main", "name": "Основной", "region_id": region.id},
    )
    assert created.status_code == 201

    body = created.json()
    assert body["code"] == "main"
    assert body["region_code"] == "almaty"
    assert body["region_name"] == "Алматы"
    assert body["is_active"] is True
    assert body["sync_source"] == "manual"

    listing = (await api.get(WAREHOUSES, headers=admin)).json()
    assert listing["total"] == 1


async def test_warehouse_code_is_unique(api: AsyncClient, admin: Headers, warehouse: dict) -> None:
    duplicate = await api.post(WAREHOUSES, headers=admin, json={"code": "main", "name": "Дубль"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "warehouse_code_exists"


async def test_warehouse_can_be_deactivated_not_deleted(
    api: AsyncClient, admin: Headers, warehouse: dict
) -> None:
    """Склад не удаляется: на него ссылаются остатки (FK RESTRICT)."""
    response = await api.patch(
        f"{WAREHOUSES}/{warehouse['id']}", headers=admin, json={"is_active": False}
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    active_only = (await api.get(WAREHOUSES, headers=admin, params={"is_active": True})).json()
    assert active_only["total"] == 0

    assert (await api.delete(f"{WAREHOUSES}/{warehouse['id']}", headers=admin)).status_code == 405


async def test_warehouse_code_cannot_be_changed(
    api: AsyncClient, admin: Headers, warehouse: dict
) -> None:
    """Код неизменяем: на него завязано будущее сопоставление с 1С."""
    response = await api.patch(
        f"{WAREHOUSES}/{warehouse['id']}", headers=admin, json={"code": "other", "name": "Новое"}
    )
    assert response.status_code == 200
    assert response.json()["code"] == "main"
    assert response.json()["name"] == "Новое"


async def test_unknown_warehouse_returns_404(api: AsyncClient, admin: Headers) -> None:
    assert (
        await api.patch(f"{WAREHOUSES}/999999", headers=admin, json={"name": "X"})
    ).status_code == 404


# =============================================================== остатки
async def test_product_stock_shows_active_warehouse_with_zero(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict
) -> None:
    """Активный склад без записи остатка показывается нулём, а не исчезает."""
    response = await api.get(stock_url(product["id"]), headers=admin)
    assert response.status_code == 200

    body = response.json()
    assert len(body["entries"]) == 1
    assert Decimal(body["entries"][0]["quantity"]) == 0
    assert Decimal(body["total_available"]) == 0
    assert body["public_availability"] == "OUT_OF_STOCK"


async def test_set_stock_with_fractional_quantity(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict
) -> None:
    """Канат меряется метрами: 152.5 должно храниться как 152.5."""
    response = await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "152.5"}]},
    )
    assert response.status_code == 200

    entry = response.json()["entries"][0]
    assert Decimal(entry["quantity"]) == Decimal("152.500")
    assert Decimal(entry["reserved"]) == 0
    assert Decimal(entry["available"]) == Decimal("152.500")
    assert entry["sync_source"] == "manual"
    assert response.json()["public_availability"] == "IN_STOCK"


async def test_available_is_quantity_minus_reserved(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict
) -> None:
    response = await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "100", "reserved": "30"}]},
    )
    body = response.json()

    assert Decimal(body["total_quantity"]) == 100
    assert Decimal(body["total_reserved"]) == 30
    assert Decimal(body["total_available"]) == 70


async def test_stock_update_is_idempotent(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict
) -> None:
    payload = {"items": [{"warehouse_id": warehouse["id"], "quantity": "42"}]}
    first = (await api.put(stock_url(product["id"]), headers=admin, json=payload)).json()
    second = (await api.put(stock_url(product["id"]), headers=admin, json=payload)).json()

    assert Decimal(first["total_quantity"]) == Decimal(second["total_quantity"]) == 42
    assert len(second["entries"]) == 1


async def test_unlisted_warehouse_is_not_touched(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict, region: Region
) -> None:
    """Частичный запрос не должен молча обнулять остальные склады."""
    second = (
        await api.post(
            WAREHOUSES,
            headers=admin,
            json={"code": "reserve", "name": "Резервный", "region_id": region.id},
        )
    ).json()

    await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={
            "items": [
                {"warehouse_id": warehouse["id"], "quantity": "10"},
                {"warehouse_id": second["id"], "quantity": "5"},
            ]
        },
    )
    await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "20"}]},
    )

    body = (await api.get(stock_url(product["id"]), headers=admin)).json()
    by_code = {entry["warehouse_code"]: entry for entry in body["entries"]}

    assert Decimal(by_code["main"]["quantity"]) == 20
    assert Decimal(by_code["reserve"]["quantity"]) == 5
    assert Decimal(body["total_quantity"]) == 25


async def test_multiple_warehouses_are_summed(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict, region: Region
) -> None:
    second = (
        await api.post(
            WAREHOUSES,
            headers=admin,
            json={"code": "second", "name": "Второй", "region_id": region.id},
        )
    ).json()

    body = (
        await api.put(
            stock_url(product["id"]),
            headers=admin,
            json={
                "items": [
                    {"warehouse_id": warehouse["id"], "quantity": "10", "reserved": "2"},
                    {"warehouse_id": second["id"], "quantity": "5"},
                ]
            },
        )
    ).json()

    assert len(body["entries"]) == 2
    assert Decimal(body["total_available"]) == 13


async def test_inactive_warehouse_is_excluded_from_totals(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict, region: Region
) -> None:
    """Отключённый склад виден администратору, но в наличии не участвует —
    так же, как его игнорирует публичный расчёт."""
    spare = (
        await api.post(
            WAREHOUSES,
            headers=admin,
            json={"code": "spare", "name": "Запасной", "region_id": region.id},
        )
    ).json()
    await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={
            "items": [
                {"warehouse_id": warehouse["id"], "quantity": "0"},
                {"warehouse_id": spare["id"], "quantity": "999"},
            ]
        },
    )
    await api.patch(f"{WAREHOUSES}/{spare['id']}", headers=admin, json={"is_active": False})

    body = (await api.get(stock_url(product["id"]), headers=admin)).json()
    by_code = {entry["warehouse_code"]: entry for entry in body["entries"]}

    # Остаток по-прежнему виден администратору
    assert Decimal(by_code["spare"]["quantity"]) == 999
    assert by_code["spare"]["warehouse_is_active"] is False
    # Но в итог и в наличие не входит
    assert Decimal(body["total_quantity"]) == 0
    assert body["public_availability"] == "OUT_OF_STOCK"
    assert (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()["availability"] == "OUT_OF_STOCK"


async def test_stock_on_inactive_warehouse_is_rejected(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict
) -> None:
    await api.patch(f"{WAREHOUSES}/{warehouse['id']}", headers=admin, json={"is_active": False})

    response = await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "10"}]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "warehouse_inactive"


# ============================================================= валидация
@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"quantity": "-1"}, "отрицательный остаток"),
        ({"quantity": "10", "reserved": "-1"}, "отрицательный резерв"),
        ({"quantity": "10", "reserved": "20"}, "резерв больше остатка"),
        ({"quantity": "10.0005"}, "лишний знак после запятой"),
    ],
)
async def test_invalid_stock_values(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict, payload: dict, reason: str
) -> None:
    response = await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": warehouse["id"], **payload}]},
    )
    assert response.status_code == 422, reason


async def test_duplicate_warehouse_in_payload(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict
) -> None:
    response = await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={
            "items": [
                {"warehouse_id": warehouse["id"], "quantity": "1"},
                {"warehouse_id": warehouse["id"], "quantity": "2"},
            ]
        },
    )
    assert response.status_code == 422


async def test_empty_items_are_rejected(api: AsyncClient, admin: Headers, product: dict) -> None:
    response = await api.put(stock_url(product["id"]), headers=admin, json={"items": []})
    assert response.status_code == 422


async def test_unknown_product_and_warehouse(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict
) -> None:
    assert (await api.get(stock_url(999_999), headers=admin)).status_code == 404
    unknown_warehouse = await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": 999_999, "quantity": "1"}]},
    )
    assert unknown_warehouse.status_code == 404


async def test_deleted_product_stock_follows_mutability_policy(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict
) -> None:
    """Единое правило проекта: удалённый товар только читается."""
    await api.delete(f"{PRODUCTS}/{product['id']}", headers=admin)

    assert (await api.get(stock_url(product["id"]), headers=admin)).status_code == 200

    write = await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "10"}]},
    )
    assert write.status_code == 409
    assert write.json()["error"]["code"] == "product_deleted"

    override = await api.patch(
        availability_url(product["id"]),
        headers=admin,
        json={"stock_display_override": "IN_STOCK"},
    )
    assert override.status_code == 409


# ============================================ переопределение наличия
async def test_override_changes_public_availability_without_touching_stock(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict
) -> None:
    await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "0"}]},
    )
    assert (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()["availability"] == "OUT_OF_STOCK"

    response = await api.patch(
        availability_url(product["id"]),
        headers=admin,
        json={"stock_display_override": "IN_STOCK"},
    )
    assert response.status_code == 200
    assert response.json()["public_availability"] == "IN_STOCK"

    assert (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()["availability"] == "IN_STOCK"

    # Фактический остаток не изменился
    stock = (await api.get(stock_url(product["id"]), headers=admin)).json()
    assert Decimal(stock["total_quantity"]) == 0
    assert Decimal(stock["total_available"]) == 0


async def test_removing_override_restores_calculated_availability(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict
) -> None:
    await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "5"}]},
    )
    await api.patch(
        availability_url(product["id"]),
        headers=admin,
        json={"stock_display_override": "OUT_OF_STOCK"},
    )
    assert (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()["availability"] == "OUT_OF_STOCK"

    removed = await api.patch(
        availability_url(product["id"]), headers=admin, json={"stock_display_override": None}
    )
    assert removed.status_code == 200
    assert removed.json()["stock_display_override"] is None
    assert removed.json()["public_availability"] == "IN_STOCK"
    assert (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()["availability"] == "IN_STOCK"


async def test_unknown_override_value_is_rejected(
    api: AsyncClient, admin: Headers, product: dict
) -> None:
    response = await api.patch(
        availability_url(product["id"]),
        headers=admin,
        json={"stock_display_override": "MAYBE"},
    )
    assert response.status_code == 422


# ================================================== публичная витрина
async def test_stock_changes_affect_public_availability(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict
) -> None:
    assert (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()["availability"] == "OUT_OF_STOCK"

    await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "7"}]},
    )
    assert (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()["availability"] == "IN_STOCK"

    filtered = (await api.get(PUBLIC_PRODUCTS, params={"availability": "IN_STOCK"})).json()
    assert [item["slug"] for item in filtered["items"]] == ["kanat-16"]


async def test_exact_quantity_never_appears_in_public_response(
    api: AsyncClient, admin: Headers, product: dict, warehouse: dict
) -> None:
    await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "152.5", "reserved": "2.5"}]},
    )

    detail = (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()
    listing = (await api.get(PUBLIC_PRODUCTS)).json()

    for payload in (str(detail), str(listing)):
        assert "152.5" not in payload
        assert "quantity" not in payload
        assert "reserved" not in payload
        assert "warehouse" not in payload


# ==================================================================== RBAC
@pytest.mark.parametrize(
    ("role", "read_status", "write_status"),
    [
        (UserRole.SUPERADMIN, 200, 200),
        (UserRole.ADMIN, 200, 200),
        (UserRole.CONTENT_MANAGER, 200, 200),
        (UserRole.MANAGER, 200, 403),
        (UserRole.VIEWER, 200, 403),
    ],
)
async def test_stock_permissions(
    api: AsyncClient,
    product: dict,
    warehouse: dict,
    login_as,
    role: UserRole,
    read_status: int,
    write_status: int,
) -> None:
    """Запись требует stock.write, которого у MANAGER нет."""
    headers = await login_as(role)

    assert (await api.get(stock_url(product["id"]), headers=headers)).status_code == read_status
    written = await api.put(
        stock_url(product["id"]),
        headers=headers,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "1"}]},
    )
    assert written.status_code == write_status

    override = await api.patch(
        availability_url(product["id"]),
        headers=headers,
        json={"stock_display_override": None},
    )
    assert override.status_code == write_status


async def test_manager_cannot_write_stock_but_can_read(
    api: AsyncClient, product: dict, warehouse: dict, login_as
) -> None:
    headers = await login_as(UserRole.MANAGER)

    written = await api.put(
        stock_url(product["id"]),
        headers=headers,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "1"}]},
    )
    assert written.status_code == 403
    assert written.json()["error"]["details"]["required"] == ["stock.write"]
    # Чтение остаётся доступным: см. отчёт про отсутствие stock.read
    assert (await api.get(stock_url(product["id"]), headers=headers)).status_code == 200


async def test_anonymous_access_is_rejected(
    api: AsyncClient, product: dict, warehouse: dict
) -> None:
    assert (await api.get(WAREHOUSES)).status_code == 401
    assert (await api.get(stock_url(product["id"]))).status_code == 401
    assert (await api.put(stock_url(product["id"]), json={"items": []})).status_code == 401


# =================================================================== аудит
async def test_stock_and_override_mutations_are_audited(
    api: AsyncClient,
    admin: Headers,
    product: dict,
    warehouse: dict,
    committed_session: AsyncSession,
) -> None:
    await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "10"}]},
    )
    await api.put(
        stock_url(product["id"]),
        headers=admin,
        json={"items": [{"warehouse_id": warehouse["id"], "quantity": "3", "reserved": "1"}]},
    )
    await api.patch(
        availability_url(product["id"]),
        headers=admin,
        json={"stock_display_override": "ON_REQUEST"},
    )

    entries = (
        (
            await committed_session.execute(
                select(AuditLog)
                .where(AuditLog.entity_type.in_(["product_stock", "product_availability"]))
                .order_by(AuditLog.id)
            )
        )
        .scalars()
        .all()
    )
    actions = [entry.action for entry in entries]

    assert actions == [
        "inventory.stock_updated",
        "inventory.stock_updated",
        "inventory.availability_override_updated",
    ]
    # Второе изменение остатка хранит прежние значения; «до» и «после»
    # приведены к одной точности и сравнимы между собой
    assert entries[1].changes["main"]["old"] == {"quantity": "10.000", "reserved": "0.000"}
    assert entries[1].changes["main"]["new"] == {"quantity": "3.000", "reserved": "1.000"}
    assert entries[0].changes["main"]["old"] is None
    assert entries[0].changes["main"]["new"] == {"quantity": "10.000", "reserved": "0.000"}
    assert entries[2].changes["stock_display_override"] == {"old": None, "new": "ON_REQUEST"}
    assert all(entry.user_id is not None for entry in entries)


async def test_warehouse_mutations_are_audited(
    api: AsyncClient, admin: Headers, warehouse: dict, committed_session: AsyncSession
) -> None:
    await api.patch(f"{WAREHOUSES}/{warehouse['id']}", headers=admin, json={"name": "Новое имя"})

    entries = (
        (
            await committed_session.execute(
                select(AuditLog).where(AuditLog.entity_type == "warehouse").order_by(AuditLog.id)
            )
        )
        .scalars()
        .all()
    )
    assert [entry.action for entry in entries] == [
        "inventory.warehouse_created",
        "inventory.warehouse_updated",
    ]


async def test_reads_are_not_audited(
    api: AsyncClient,
    admin: Headers,
    product: dict,
    warehouse: dict,
    committed_session: AsyncSession,
) -> None:
    await api.get(stock_url(product["id"]), headers=admin)
    await api.get(availability_url(product["id"]), headers=admin)
    await api.get(WAREHOUSES, headers=admin)

    entries = (
        (
            await committed_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type.in_(["product_stock", "product_availability"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert entries == []


# ============================================================ конкурентность
async def test_concurrent_stock_updates_are_serialized(
    api: AsyncClient,
    admin: Headers,
    product: dict,
    warehouse: dict,
    test_engine: AsyncEngine,
    make_user,
) -> None:
    """Две параллельные записи по одному складу не должны конфликтовать.

    Строка товара блокируется на время транзакции, поэтому вставка
    по составному ключу (product_id, warehouse_id) выполняется по
    очереди, а не приводит к нарушению первичного ключа.
    """
    from app.modules.inventory.schemas_admin import StockUpdate
    from app.modules.inventory.service_admin import AdminStockService

    actor = await make_user()
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def apply(quantity: str) -> None:
        payload = StockUpdate.model_validate(
            {"items": [{"warehouse_id": warehouse["id"], "quantity": quantity}]}
        )
        async with session_factory() as session:
            await AdminStockService(session).set_stock(product["id"], payload, actor)

    await asyncio.gather(apply("10"), apply("20"))

    body = (await api.get(stock_url(product["id"]), headers=admin)).json()
    assert len(body["entries"]) == 1
    assert Decimal(body["entries"][0]["quantity"]) in (Decimal(10), Decimal(20))


# ========================================================== производительность
async def test_stock_endpoint_query_count_is_fixed(
    api: AsyncClient,
    admin: Headers,
    product: dict,
    warehouse: dict,
    region: Region,
    test_engine: AsyncEngine,
) -> None:
    with count_queries(test_engine) as single:
        await api.get(stock_url(product["id"]), headers=admin)
    baseline = len(single)

    for index in range(5):
        created = (
            await api.post(
                WAREHOUSES,
                headers=admin,
                json={"code": f"wh-{index}", "name": f"Склад {index}", "region_id": region.id},
            )
        ).json()
        await api.put(
            stock_url(product["id"]),
            headers=admin,
            json={"items": [{"warehouse_id": created["id"], "quantity": "1"}]},
        )

    with count_queries(test_engine) as many:
        body = (await api.get(stock_url(product["id"]), headers=admin)).json()

    assert len(body["entries"]) == 6
    assert len(many) == baseline
