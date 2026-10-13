"""Интеграционные тесты Admin API ценообразования.

Публичное представление цены проверяется через настоящий публичный
эндпоинт: расчёт живёт в одном месте, и админский тест не должен
повторять его логику.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.modules.audit.models import AuditLog
from app.modules.pricing.models import PriceList
from app.modules.users.enums import UserRole
from tests.conftest import Headers
from tests.helpers import count_queries

PRODUCTS = "/api/v1/admin/products"
PRICE_LIST = "/api/v1/admin/pricing/price-list"
PUBLIC_PRODUCTS = "/api/v1/public/products"


def pricing_url(product_id: int) -> str:
    return f"{PRODUCTS}/{product_id}/pricing"


TIERED_TIERS = [
    {"min_qty": "1", "max_qty": "9", "price": "3500.00"},
    {"min_qty": "10", "max_qty": "49", "price": "3000.00"},
    {"min_qty": "50", "max_qty": None, "price": "2600.00"},
]


@pytest.fixture
async def price_list(committed_session: AsyncSession) -> PriceList:
    """Публичный прайс-лист. Создаётся один раз при настройке системы."""
    item = PriceList(code="default", name="Основной прайс", currency="KZT", is_default=True)
    committed_session.add(item)
    await committed_session.commit()
    await committed_session.refresh(item)
    return item


@pytest.fixture
async def product(api: AsyncClient, admin: Headers, price_list: PriceList) -> dict:
    """Опубликованный товар — чтобы сразу проверять витрину."""
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


# ============================================================== прайс-лист
async def test_price_list_endpoint(api: AsyncClient, admin: Headers, price_list: PriceList) -> None:
    response = await api.get(PRICE_LIST, headers=admin)
    assert response.status_code == 200

    body = response.json()
    assert body["code"] == "default"
    assert body["currency"] == "KZT"


async def test_missing_default_price_list_is_a_server_error(
    api: AsyncClient, admin: Headers
) -> None:
    """Прайс-лист не создаётся на лету — это ошибка конфигурации."""
    response = await api.get(PRICE_LIST, headers=admin)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "default_price_list_missing"


# =================================================================== GET
async def test_get_pricing_without_tiers(api: AsyncClient, admin: Headers, product: dict) -> None:
    response = await api.get(pricing_url(product["id"]), headers=admin)
    assert response.status_code == 200

    body = response.json()
    assert body["tiers"] == []
    assert body["min_price"] is None
    assert body["currency"] == "KZT"
    assert body["price_list_code"] == "default"


async def test_get_pricing_for_unknown_product(api: AsyncClient, admin: Headers) -> None:
    assert (await api.get(pricing_url(999_999), headers=admin)).status_code == 404


# =================================================================== PUT
async def test_set_fixed_pricing(api: AsyncClient, admin: Headers, product: dict) -> None:
    response = await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={
            "pricing_type": "FIXED",
            "tiers": [{"min_qty": "1", "max_qty": None, "price": "1200.50"}],
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert body["pricing_type"] == "FIXED"
    assert len(body["tiers"]) == 1
    assert Decimal(body["min_price"]) == Decimal("1200.50")

    public = (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()["price"]
    assert public["type"] == "FIXED"
    assert Decimal(public["price"]) == Decimal("1200.50")
    assert Decimal(public["from_price"]) == Decimal("1200.50")


async def test_set_tiered_pricing(api: AsyncClient, admin: Headers, product: dict) -> None:
    response = await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={"pricing_type": "TIERED", "tiers": TIERED_TIERS},
    )
    assert response.status_code == 200

    body = response.json()
    assert len(body["tiers"]) == 3
    assert Decimal(body["min_price"]) == Decimal("2600.00")
    assert Decimal(body["max_price"]) == Decimal("3500.00")
    # Ступени возвращаются по возрастанию количества
    assert [Decimal(tier["min_qty"]) for tier in body["tiers"]] == [1, 10, 50]

    public = (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()["price"]
    assert public["type"] == "TIERED"
    assert public["price"] is None
    assert Decimal(public["from_price"]) == Decimal("2600.00")
    assert public["tiers"][-1]["max_quantity"] is None


async def test_set_from_pricing(api: AsyncClient, admin: Headers, product: dict) -> None:
    response = await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={
            "pricing_type": "FROM",
            "tiers": [
                {"min_qty": "1", "max_qty": "99", "price": "5000.00"},
                {"min_qty": "100", "max_qty": None, "price": "4200.00"},
            ],
        },
    )
    assert response.status_code == 200

    public = (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()["price"]
    assert public["type"] == "FROM"
    assert public["price"] is None
    assert Decimal(public["from_price"]) == Decimal("4200.00")


async def test_set_on_request_pricing(api: AsyncClient, admin: Headers, product: dict) -> None:
    """ON_REQUEST — отсутствие строк, а не цена 0."""
    await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={"pricing_type": "TIERED", "tiers": TIERED_TIERS},
    )

    response = await api.put(
        pricing_url(product["id"]), headers=admin, json={"pricing_type": "ON_REQUEST", "tiers": []}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["tiers"] == []
    assert body["min_price"] is None

    public = (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()["price"]
    assert public["type"] == "ON_REQUEST"
    assert public["price"] is None
    assert public["from_price"] is None
    assert public["tiers"] == []


async def test_replacement_removes_previous_tiers(
    api: AsyncClient, admin: Headers, product: dict, committed_session: AsyncSession
) -> None:
    await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={"pricing_type": "TIERED", "tiers": TIERED_TIERS},
    )
    response = await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={
            "pricing_type": "FIXED",
            "tiers": [{"min_qty": "1", "max_qty": None, "price": "999.00"}],
        },
    )
    assert response.status_code == 200
    assert len(response.json()["tiers"]) == 1

    stored = (
        await committed_session.execute(
            text("SELECT count(*) FROM price_tiers WHERE product_id = :pid"),
            {"pid": product["id"]},
        )
    ).scalar_one()
    assert stored == 1


async def test_fractional_quantities_are_supported(
    api: AsyncClient, admin: Headers, product: dict
) -> None:
    """Канат меряется метрами: 2.5 м должно сохраниться как 2.5."""
    response = await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={
            "pricing_type": "TIERED",
            "tiers": [
                {"min_qty": "0.5", "max_qty": "2.5", "price": "400.00"},
                {"min_qty": "2.6", "max_qty": None, "price": "350.00"},
            ],
        },
    )
    assert response.status_code == 200
    assert Decimal(response.json()["tiers"][0]["max_qty"]) == Decimal("2.5")


async def test_pricing_of_deleted_product_is_rejected(
    api: AsyncClient, admin: Headers, product: dict
) -> None:
    """Цены подчиняются тому же правилу, что и остальные мутации товара."""
    await api.delete(f"{PRODUCTS}/{product['id']}", headers=admin)

    response = await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={
            "pricing_type": "FIXED",
            "tiers": [{"min_qty": "1", "max_qty": None, "price": "100.00"}],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "product_deleted"
    assert response.json()["error"]["details"]["product_id"] == product["id"]
    # Читать цены удалённого товара можно — это нужно для разбора истории
    assert (await api.get(pricing_url(product["id"]), headers=admin)).status_code == 200

    # После восстановления цены снова редактируются
    await api.post(f"{PRODUCTS}/{product['id']}/restore", headers=admin)
    restored = await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={
            "pricing_type": "FIXED",
            "tiers": [{"min_qty": "1", "max_qty": None, "price": "100.00"}],
        },
    )
    assert restored.status_code == 200


# ============================================================== валидация
@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"pricing_type": "TIERED", "tiers": []}, "нет ступеней"),
        ({"pricing_type": "FIXED", "tiers": []}, "нет ступеней"),
        ({"pricing_type": "FROM", "tiers": []}, "нет ступеней"),
        (
            {
                "pricing_type": "ON_REQUEST",
                "tiers": [{"min_qty": "1", "max_qty": None, "price": "10.00"}],
            },
            "ступени при ON_REQUEST",
        ),
        (
            {
                "pricing_type": "FIXED",
                "tiers": [
                    {"min_qty": "1", "max_qty": "9", "price": "10.00"},
                    {"min_qty": "10", "max_qty": None, "price": "9.00"},
                ],
            },
            "FIXED с несколькими ступенями",
        ),
        (
            {
                "pricing_type": "FIXED",
                "tiers": [{"min_qty": "5", "max_qty": None, "price": "10.00"}],
            },
            "FIXED с min_qty != 1",
        ),
        (
            {
                "pricing_type": "FIXED",
                "tiers": [{"min_qty": "1", "max_qty": "9", "price": "10.00"}],
            },
            "FIXED с закрытым диапазоном",
        ),
        (
            {
                "pricing_type": "TIERED",
                "tiers": [{"min_qty": "0", "max_qty": "9", "price": "10.00"}],
            },
            "min_qty = 0",
        ),
        (
            {
                "pricing_type": "TIERED",
                "tiers": [{"min_qty": "-1", "max_qty": "9", "price": "10.00"}],
            },
            "отрицательное min_qty",
        ),
        (
            {
                "pricing_type": "TIERED",
                "tiers": [{"min_qty": "10", "max_qty": "5", "price": "10.00"}],
            },
            "max_qty < min_qty",
        ),
        (
            {
                "pricing_type": "TIERED",
                "tiers": [{"min_qty": "1", "max_qty": None, "price": "-1.00"}],
            },
            "отрицательная цена",
        ),
        (
            {
                "pricing_type": "TIERED",
                "tiers": [
                    {"min_qty": "1", "max_qty": "10", "price": "10.00"},
                    {"min_qty": "10", "max_qty": "20", "price": "9.00"},
                ],
            },
            "пересечение по границе",
        ),
        (
            {
                "pricing_type": "TIERED",
                "tiers": [
                    {"min_qty": "1", "max_qty": None, "price": "10.00"},
                    {"min_qty": "50", "max_qty": None, "price": "9.00"},
                ],
            },
            "две открытые ступени",
        ),
        (
            {
                "pricing_type": "TIERED",
                "tiers": [{"min_qty": "1", "max_qty": None, "price": "10.005"}],
            },
            "лишний знак в цене",
        ),
    ],
)
async def test_invalid_pricing_payloads(
    api: AsyncClient, admin: Headers, product: dict, payload: dict, reason: str
) -> None:
    response = await api.put(pricing_url(product["id"]), headers=admin, json=payload)
    assert response.status_code == 422, reason
    assert response.json()["error"]["code"] == "validation_error"


async def test_unknown_pricing_type_is_rejected(
    api: AsyncClient, admin: Headers, product: dict
) -> None:
    response = await api.put(
        pricing_url(product["id"]), headers=admin, json={"pricing_type": "MAGIC", "tiers": []}
    )
    assert response.status_code == 422


async def test_gaps_between_tiers_are_allowed(
    api: AsyncClient, admin: Headers, product: dict
) -> None:
    """Непрерывность не требуется: модель её не навязывает.

    Заказ на количество из «дыры» просто попадёт в цену по запросу.
    """
    response = await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={
            "pricing_type": "TIERED",
            "tiers": [
                {"min_qty": "1", "max_qty": "9", "price": "100.00"},
                {"min_qty": "20", "max_qty": "49", "price": "90.00"},
            ],
        },
    )
    assert response.status_code == 200


async def test_internal_constraint_name_is_not_exposed(
    api: AsyncClient, admin: Headers, product: dict
) -> None:
    response = await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={
            "pricing_type": "TIERED",
            "tiers": [
                {"min_qty": "1", "max_qty": "50", "price": "10.00"},
                {"min_qty": "40", "max_qty": "90", "price": "9.00"},
            ],
        },
    )
    assert response.status_code == 422
    assert "no_overlapping_tiers" not in str(response.json())


# =========================================== публичная витрина и сортировка
async def test_public_response_hides_price_list_internals(
    api: AsyncClient, admin: Headers, product: dict
) -> None:
    await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={"pricing_type": "TIERED", "tiers": TIERED_TIERS},
    )
    public = (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()

    assert "price_list_code" not in str(public)
    assert "price_list_id" not in str(public)
    assert public["price"]["currency"] == "KZT"


async def test_pricing_changes_affect_public_sorting_and_filters(
    api: AsyncClient, admin: Headers, product: dict
) -> None:
    second = (
        await api.post(
            PRODUCTS,
            headers=admin,
            json={
                "sku": "KRP-10",
                "slug": "kreplenie-10",
                "status": "PUBLISHED",
                "translations": {"ru": {"name": "Крепление"}},
            },
        )
    ).json()

    await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={
            "pricing_type": "FIXED",
            "tiers": [{"min_qty": "1", "max_qty": None, "price": "5000.00"}],
        },
    )
    await api.put(
        pricing_url(second["id"]),
        headers=admin,
        json={
            "pricing_type": "FIXED",
            "tiers": [{"min_qty": "1", "max_qty": None, "price": "1000.00"}],
        },
    )

    ascending = (await api.get(PUBLIC_PRODUCTS, params={"sort": "price_asc"})).json()
    assert [item["slug"] for item in ascending["items"]] == ["kreplenie-10", "kanat-16"]

    descending = (await api.get(PUBLIC_PRODUCTS, params={"sort": "price_desc"})).json()
    assert [item["slug"] for item in descending["items"]] == ["kanat-16", "kreplenie-10"]

    cheap = (await api.get(PUBLIC_PRODUCTS, params={"max_price": "2000"})).json()
    assert [item["slug"] for item in cheap["items"]] == ["kreplenie-10"]

    expensive = (await api.get(PUBLIC_PRODUCTS, params={"min_price": "2000"})).json()
    assert [item["slug"] for item in expensive["items"]] == ["kanat-16"]


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
async def test_pricing_permissions(
    api: AsyncClient,
    admin: Headers,
    product: dict,
    login_as,
    role: UserRole,
    read_status: int,
    write_status: int,
) -> None:
    """MANAGER читает каталог, но цены менять не может."""
    headers = await login_as(role)

    assert (await api.get(pricing_url(product["id"]), headers=headers)).status_code == read_status
    written = await api.put(
        pricing_url(product["id"]),
        headers=headers,
        json={
            "pricing_type": "FIXED",
            "tiers": [{"min_qty": "1", "max_qty": None, "price": "100.00"}],
        },
    )
    assert written.status_code == write_status


async def test_anonymous_access_is_rejected(api: AsyncClient, product: dict) -> None:
    assert (await api.get(pricing_url(product["id"]))).status_code == 401
    assert (await api.get(PRICE_LIST)).status_code == 401
    assert (
        await api.put(pricing_url(product["id"]), json={"pricing_type": "ON_REQUEST", "tiers": []})
    ).status_code == 401


# =================================================================== аудит
async def test_pricing_change_is_audited(
    api: AsyncClient, admin: Headers, product: dict, committed_session: AsyncSession
) -> None:
    await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={
            "pricing_type": "FIXED",
            "tiers": [{"min_qty": "1", "max_qty": None, "price": "1000.00"}],
        },
    )
    await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={"pricing_type": "ON_REQUEST", "tiers": []},
    )

    entries = (
        (
            await committed_session.execute(
                select(AuditLog)
                .where(AuditLog.entity_type == "product_pricing")
                .order_by(AuditLog.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 2
    assert all(entry.action == "pricing.updated" for entry in entries)

    last = entries[-1]
    assert last.changes["old"]["pricing_type"] == "FIXED"
    assert last.changes["old"]["tiers"][0]["price"] == "1000.00"
    assert last.changes["new"]["pricing_type"] == "ON_REQUEST"
    assert last.changes["new"]["tiers"] == []
    assert last.user_id is not None


async def test_reads_are_not_audited(
    api: AsyncClient, admin: Headers, product: dict, committed_session: AsyncSession
) -> None:
    await api.get(pricing_url(product["id"]), headers=admin)
    await api.get(PRICE_LIST, headers=admin)

    entries = (
        (
            await committed_session.execute(
                select(AuditLog).where(AuditLog.entity_type == "product_pricing")
            )
        )
        .scalars()
        .all()
    )
    assert entries == []


# ============================================================ конкурентность
async def test_concurrent_pricing_updates_do_not_merge(
    test_engine: AsyncEngine, api: AsyncClient, admin: Headers, product: dict, make_user
) -> None:
    """Два одновременных PUT не должны оставить смесь из двух прайсов.

    Строка товара блокируется на время транзакции, поэтому изменения
    выполняются по очереди, и итоговый набор принадлежит одному из
    запросов целиком.
    """
    from app.modules.pricing.schemas_admin import PricingUpdate
    from app.modules.pricing.service_admin import AdminPricingService

    actor = await make_user()
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    first = PricingUpdate.model_validate(
        {
            "pricing_type": "TIERED",
            "tiers": [
                {"min_qty": "1", "max_qty": "9", "price": "100.00"},
                {"min_qty": "10", "max_qty": None, "price": "90.00"},
            ],
        }
    )
    second = PricingUpdate.model_validate(
        {
            "pricing_type": "FIXED",
            "tiers": [{"min_qty": "1", "max_qty": None, "price": "777.00"}],
        }
    )

    async def apply(payload: PricingUpdate) -> None:
        async with session_factory() as session:
            await AdminPricingService(session).set_pricing(product["id"], payload, actor)

    await asyncio.gather(apply(first), apply(second))

    result = (await api.get(pricing_url(product["id"]), headers=admin)).json()
    prices = sorted(Decimal(tier["price"]) for tier in result["tiers"])

    # Итог — ровно один из двух наборов, без склейки
    assert prices in ([Decimal("777.00")], [Decimal("90.00"), Decimal("100.00")])
    assert len(result["tiers"]) == len(prices)


# ========================================================== производительность
async def test_pricing_get_query_count_is_fixed(
    api: AsyncClient, admin: Headers, product: dict, test_engine: AsyncEngine
) -> None:
    with count_queries(test_engine) as empty:
        await api.get(pricing_url(product["id"]), headers=admin)
    baseline = len(empty)

    await api.put(
        pricing_url(product["id"]),
        headers=admin,
        json={"pricing_type": "TIERED", "tiers": TIERED_TIERS},
    )

    with count_queries(test_engine) as filled:
        body = (await api.get(pricing_url(product["id"]), headers=admin)).json()

    assert len(body["tiers"]) == 3
    assert len(filled) == baseline
