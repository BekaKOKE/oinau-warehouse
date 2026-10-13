"""Интеграционные тесты публичного приёма заявок — POST /api/v1/public/requests."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from decimal import Decimal
from typing import Any

import pytest
import structlog
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import ProductTranslation
from app.modules.inventory.models import Stock
from app.modules.pricing.models import PriceTier
from app.modules.requests.models import Request, RequestItem, RequestStatusHistory
from tests.catalog_fixtures import CatalogFixture
from tests.helpers import count_queries
from tests.request_helpers import (
    CUSTOMER_EMAIL,
    CUSTOMER_NAME,
    CUSTOMER_PHONE_NORMALIZED,
    PUBLIC_REQUESTS,
    load_request,
    request_id,
    request_payload,
    submit_request,
)

ROPE = "KAN-16-PP"  # TIERED: 1–9 → 3500, 10–49 → 3200, 50–99 → 2900, 100+ → 2600
FASTENER = "KRP-M10"  # FIXED: 1200
SEAT = "SID-01"  # ON_REQUEST


async def _items(session: AsyncSession, number: str) -> list[RequestItem]:
    rid = await request_id(session, number)
    query = (
        select(RequestItem)
        .where(RequestItem.request_id == rid)
        .order_by(RequestItem.sort_order)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(query)).scalars().all())


async def _count(session: AsyncSession, model: Any) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


# ============================================================ создание
async def test_create_request(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    body = await submit_request(api, catalog)

    assert re.fullmatch(r"R-\d{4}-\d{6}", body["number"])
    assert body["currency"] == "KZT"
    assert Decimal(body["total_estimate"]) == Decimal("32000.00")
    assert body["items"] == [
        {
            "sku": ROPE,
            "name": "Канат полипропиленовый 16 мм",
            "unit": "m",
            "quantity": "10.000",
            "pricing_type": "TIERED",
            "unit_price": "3200.00",
            "line_total": "32000.00",
        }
    ]
    # Подтверждение не раскрывает внутренних данных заявки
    assert set(body) == {"number", "created_at", "currency", "total_estimate", "items"}

    request = await load_request(committed_session, body["number"])
    assert request.kind == "CART"
    assert request.source == "CATALOG_CART"
    assert request.customer_name == CUSTOMER_NAME
    assert request.phone == CUSTOMER_PHONE_NORMALIZED
    assert request.email == CUSTOMER_EMAIL
    assert request.company == "ТОО Детские площадки"
    assert request.comment == "Нужна доставка до объекта"
    assert request.region_id == catalog.region.id
    assert request.total_estimate == Decimal("32000.00")
    assert request.assigned_to_id is None
    # IP хранится только хешем
    assert request.ip_hash is not None
    assert len(request.ip_hash) == 64


async def test_initial_status_and_history(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    body = await submit_request(api, catalog)
    request = await load_request(committed_session, body["number"])

    assert request.status == "NEW"
    history = (
        (
            await committed_session.execute(
                select(RequestStatusHistory).where(RequestStatusHistory.request_id == request.id)
            )
        )
        .scalars()
        .all()
    )
    assert [(entry.from_status, entry.to_status, entry.user_id) for entry in history] == [
        (None, "NEW", None)
    ]


async def test_multiple_items_keep_order_and_snapshots(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    body = await submit_request(
        api,
        catalog,
        items=[
            {"sku": SEAT, "quantity": "1"},
            {"sku": ROPE, "quantity": "10"},
            {"sku": FASTENER, "quantity": "2.5"},
        ],
    )

    assert [item["sku"] for item in body["items"]] == [SEAT, ROPE, FASTENER]
    # Позиция «по запросу» делает общую сумму неизвестной
    assert body["total_estimate"] is None

    items = await _items(committed_session, body["number"])
    snapshot = [
        (
            item.product_id,
            item.sku_snapshot,
            item.name_snapshot,
            item.unit_snapshot,
            item.pricing_type_snapshot,
            item.quantity,
            item.unit_price_snapshot,
            item.line_total_snapshot,
        )
        for item in items
    ]
    assert snapshot == [
        (
            catalog.products["seat"].id,
            SEAT,
            "Сиденье качелей HDPE",
            "pcs",
            "ON_REQUEST",
            Decimal("1.000"),
            None,
            None,
        ),
        (
            catalog.products["rope"].id,
            ROPE,
            "Канат полипропиленовый 16 мм",
            "m",
            "TIERED",
            Decimal("10.000"),
            Decimal("3200.00"),
            Decimal("32000.00"),
        ),
        (
            catalog.products["fastener"].id,
            FASTENER,
            "Крепление М10 оцинкованное",
            "pcs",
            "FIXED",
            Decimal("2.500"),
            Decimal("1200.00"),
            Decimal("3000.00"),
        ),
    ]


async def test_total_estimate_when_all_items_are_priced(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    body = await submit_request(
        api,
        catalog,
        items=[{"sku": ROPE, "quantity": "10"}, {"sku": FASTENER, "quantity": "3"}],
    )
    assert Decimal(body["total_estimate"]) == Decimal("35600.00")


# ======================================================= цены на сервере
@pytest.mark.parametrize(
    ("quantity", "unit_price", "pricing_type"),
    [
        ("1", "3500.00", "TIERED"),
        ("9", "3500.00", "TIERED"),
        ("10", "3200.00", "TIERED"),
        ("50", "2900.00", "TIERED"),
        ("150.5", "2600.00", "TIERED"),
        # Разрыв между ступенями 1–9 и 10–49: цена «по запросу»
        ("9.5", None, "ON_REQUEST"),
    ],
)
async def test_tier_is_chosen_by_quantity(
    api: AsyncClient,
    catalog: CatalogFixture,
    quantity: str,
    unit_price: str | None,
    pricing_type: str,
) -> None:
    body = await submit_request(api, catalog, items=[{"sku": ROPE, "quantity": quantity}])
    [item] = body["items"]

    assert item["pricing_type"] == pricing_type
    if unit_price is None:
        assert item["unit_price"] is None
        assert item["line_total"] is None
    else:
        assert Decimal(item["unit_price"]) == Decimal(unit_price)
        assert Decimal(item["line_total"]) == Decimal(unit_price) * Decimal(quantity)


async def test_only_public_price_list_is_used(api: AsyncClient, catalog: CatalogFixture) -> None:
    """У каната есть дилерская цена 1111 — в заявку она попасть не должна."""
    body = await submit_request(api, catalog, items=[{"sku": ROPE, "quantity": "1"}])
    assert Decimal(body["items"][0]["unit_price"]) == Decimal("3500.00")


async def test_decimal_quantity_is_stored_exactly(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    body = await submit_request(api, catalog, items=[{"sku": ROPE, "quantity": "12.345"}])

    [item] = await _items(committed_session, body["number"])
    assert item.quantity == Decimal("12.345")
    assert item.line_total_snapshot == Decimal("39504.00")


@pytest.mark.parametrize(
    "field",
    [
        {"price": "1.00"},
        {"unit_price": "1.00"},
        {"line_total": "1.00"},
        {"name": "Своё название"},
        {"unit": "kg"},
        {"product_id": 1},
    ],
)
async def test_client_cannot_send_item_prices_or_snapshots(
    api: AsyncClient,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
    field: dict[str, Any],
) -> None:
    response = await api.post(
        PUBLIC_REQUESTS,
        json=request_payload(catalog, items=[{"sku": ROPE, "quantity": "10", **field}]),
    )
    assert response.status_code == 422
    assert await _count(committed_session, Request) == 0


@pytest.mark.parametrize(
    "field",
    [
        {"status": "COMPLETED"},
        {"user_id": 1},
        {"assigned_to_id": 1},
        {"total_estimate": "1.00"},
        {"number": "R-2026-000001"},
        {"ip_hash": "x"},
    ],
)
async def test_client_cannot_send_internal_fields(
    api: AsyncClient,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
    field: dict[str, Any],
) -> None:
    response = await api.post(PUBLIC_REQUESTS, json=request_payload(catalog, **field))
    assert response.status_code == 422
    assert await _count(committed_session, Request) == 0


# ============================================================ валидация
@pytest.mark.parametrize(
    "quantity",
    ["0", "-1", "1.0001", "abc", "100000000000", None],
)
async def test_invalid_quantity(
    api: AsyncClient, catalog: CatalogFixture, quantity: str | None
) -> None:
    response = await api.post(
        PUBLIC_REQUESTS, json=request_payload(catalog, items=[{"sku": ROPE, "quantity": quantity}])
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"name": "   "}, "пустое имя"),
        ({"name": None}, "нет имени"),
        ({"phone": "abc-phone"}, "буквы в телефоне"),
        ({"phone": "123"}, "слишком короткий телефон"),
        ({"email": "not-an-email"}, "некорректный email"),
        ({"region_id": 0}, "некорректный регион"),
        ({"items": []}, "пустой состав"),
        ({"comment": "x" * 2001}, "слишком длинный комментарий"),
    ],
)
async def test_invalid_payload(
    api: AsyncClient, catalog: CatalogFixture, overrides: dict[str, Any], reason: str
) -> None:
    response = await api.post(PUBLIC_REQUESTS, json=request_payload(catalog, **overrides))
    assert response.status_code == 422, reason
    assert response.json()["error"]["code"] == "validation_error"


async def test_optional_fields_may_be_empty(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    payload = request_payload(catalog, email="", company="  ")
    del payload["comment"]
    response = await api.post(PUBLIC_REQUESTS, json=payload)
    assert response.status_code == 201

    request = await load_request(committed_session, response.json()["number"])
    assert request.email is None
    assert request.company is None
    assert request.comment is None


async def test_duplicate_product_is_rejected(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    response = await api.post(
        PUBLIC_REQUESTS,
        json=request_payload(
            catalog, items=[{"sku": ROPE, "quantity": "1"}, {"sku": ROPE, "quantity": "5"}]
        ),
    )
    assert response.status_code == 422
    assert ROPE in json.dumps(response.json(), ensure_ascii=False)
    assert await _count(committed_session, Request) == 0


@pytest.mark.parametrize(
    "sku",
    ["DEL-1", "DRAFT-1", "OFF-1", "NO-SUCH-SKU"],
    ids=["deleted", "draft", "inactive", "unknown"],
)
async def test_unavailable_product_rejects_whole_request(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession, sku: str
) -> None:
    """Одна недоступная позиция — и заявка не создаётся целиком.

    Удалённый, черновик, отключённый и несуществующий товар дают одну
    и ту же ошибку: публичный API не подтверждает существование скрытых
    позиций.
    """
    response = await api.post(
        PUBLIC_REQUESTS,
        json=request_payload(
            catalog, items=[{"sku": ROPE, "quantity": "1"}, {"sku": sku, "quantity": "1"}]
        ),
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "product_unavailable"
    assert error["details"] == {"skus": [sku]}

    assert await _count(committed_session, Request) == 0
    assert await _count(committed_session, RequestItem) == 0


# ================================================== минимальная партия
async def _set_min_order_qty(
    session: AsyncSession, catalog: CatalogFixture, key: str, value: str
) -> None:
    catalog.products[key].min_order_qty = Decimal(value)
    await session.commit()


async def test_quantity_below_min_order_qty_is_rejected(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    await _set_min_order_qty(committed_session, catalog, "rope", "5")

    response = await api.post(
        PUBLIC_REQUESTS,
        json=request_payload(
            catalog,
            items=[{"sku": FASTENER, "quantity": "1"}, {"sku": ROPE, "quantity": "4.999"}],
        ),
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "quantity_below_minimum"
    assert error["details"] == {
        "items": [{"sku": ROPE, "quantity": "4.999", "min_order_qty": "5.000"}]
    }
    # Корректная соседняя позиция не спасает заявку: она отклоняется целиком
    assert await _count(committed_session, Request) == 0
    assert await _count(committed_session, RequestItem) == 0


async def test_quantity_equal_to_min_order_qty_is_accepted(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    await _set_min_order_qty(committed_session, catalog, "rope", "5")

    body = await submit_request(api, catalog, items=[{"sku": ROPE, "quantity": "5"}])

    [item] = await _items(committed_session, body["number"])
    assert item.quantity == Decimal("5.000")


@pytest.mark.parametrize(
    ("min_order_qty", "quantity", "expected_status"),
    [
        ("2.5", "2.5", 201),
        ("2.5", "2.50", 201),  # хвостовые нули не влияют на сравнение
        ("2.5", "2.500", 201),
        ("2.5", "2.501", 201),
        ("2.5", "2.499", 422),
        ("2.5", "2", 422),
        ("0.125", "0.125", 201),  # минимум меньше единицы
        ("0.125", "0.124", 422),
        ("1.001", "1", 422),  # целое количество против дробного минимума
    ],
)
async def test_fractional_min_order_qty_is_compared_exactly(
    api: AsyncClient,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
    min_order_qty: str,
    quantity: str,
    expected_status: int,
) -> None:
    """Канат продаётся метрами: сравнение идёт в Decimal, без float."""
    await _set_min_order_qty(committed_session, catalog, "fastener", min_order_qty)

    response = await api.post(
        PUBLIC_REQUESTS,
        json=request_payload(catalog, items=[{"sku": FASTENER, "quantity": quantity}]),
    )

    assert response.status_code == expected_status, response.text
    if expected_status == 422:
        assert response.json()["error"]["code"] == "quantity_below_minimum"
        assert await _count(committed_session, Request) == 0
    else:
        assert Decimal(response.json()["items"][0]["quantity"]) == Decimal(quantity)


async def test_request_without_region_is_accepted(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    """На форме заявки региона нет — без него заявка всё равно создаётся."""
    payload = request_payload(catalog)
    del payload["region_id"]

    response = await api.post(PUBLIC_REQUESTS, json=payload)

    assert response.status_code == 201
    number = response.json()["number"]
    request = await load_request(committed_session, number)
    assert request.region_id is None


async def test_unknown_region_is_rejected(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    response = await api.post(PUBLIC_REQUESTS, json=request_payload(catalog, region_id=999_999))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "region_not_found"
    assert await _count(committed_session, Request) == 0


async def test_inactive_region_is_rejected(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    catalog.region.is_active = False
    await committed_session.commit()

    response = await api.post(PUBLIC_REQUESTS, json=request_payload(catalog))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "region_not_found"


# ============================================================ снапшоты
async def test_snapshot_survives_product_changes(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    body = await submit_request(api, catalog, items=[{"sku": ROPE, "quantity": "10"}])

    rope = catalog.products["rope"]
    rope.sku = "KAN-16-RENAMED"
    rope.unit = "pcs"
    rope.pricing_type = "ON_REQUEST"
    await committed_session.execute(
        update(ProductTranslation)
        .where(ProductTranslation.product_id == rope.id)
        .values(name="Совсем другое название")
    )
    await committed_session.execute(
        update(PriceTier).where(PriceTier.product_id == rope.id).values(price=Decimal("9999.00"))
    )
    await committed_session.commit()

    [item] = await _items(committed_session, body["number"])
    assert item.product_id == rope.id
    assert item.sku_snapshot == ROPE
    assert item.name_snapshot == "Канат полипропиленовый 16 мм"
    assert item.unit_snapshot == "m"
    assert item.pricing_type_snapshot == "TIERED"
    assert item.unit_price_snapshot == Decimal("3200.00")
    assert item.line_total_snapshot == Decimal("32000.00")

    request = await load_request(committed_session, body["number"])
    assert request.total_estimate == Decimal("32000.00")


async def test_request_survives_product_deletion(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    """product_id — ссылка со SET NULL, а не источник данных."""
    body = await submit_request(api, catalog, items=[{"sku": FASTENER, "quantity": "2"}])

    await committed_session.delete(catalog.products["fastener"])
    await committed_session.commit()

    [item] = await _items(committed_session, body["number"])
    assert item.product_id is None
    assert item.sku_snapshot == FASTENER
    assert item.unit_price_snapshot == Decimal("1200.00")


# =============================================================== остатки
async def test_request_does_not_touch_stock(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    async def stock_state() -> list[tuple[int, Decimal, Decimal]]:
        rows = await committed_session.execute(
            select(Stock.product_id, Stock.quantity, Stock.reserved).order_by(Stock.product_id)
        )
        return [(row[0], row[1], row[2]) for row in rows.all()]

    before = await stock_state()
    await submit_request(
        api,
        catalog,
        items=[{"sku": ROPE, "quantity": "100"}, {"sku": FASTENER, "quantity": "5"}],
    )
    assert await stock_state() == before


# ========================================================= транзакция
async def test_failure_after_insert_rolls_back_everything(
    catalog: CatalogFixture, test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сбой на последнем шаге — после вставки заявки, позиций и истории —
    не оставляет в базе ничего."""
    from app.modules.audit.service import AuditService
    from app.modules.requests.schemas_public import PublicRequestCreate
    from app.modules.requests.service import RequestSubmissionService
    from app.modules.users.service import RequestContext

    def broken_audit(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("audit is down")

    monkeypatch.setattr(AuditService, "record", broken_audit)
    payload = PublicRequestCreate.model_validate(
        request_payload(
            catalog, items=[{"sku": ROPE, "quantity": "10"}, {"sku": FASTENER, "quantity": "1"}]
        )
    )

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        with pytest.raises(RuntimeError, match="audit is down"):
            await RequestSubmissionService(session).submit(payload, RequestContext())

    async with session_factory() as check:
        assert await _count(check, Request) == 0
        assert await _count(check, RequestItem) == 0
        assert await _count(check, RequestStatusHistory) == 0


# ================================================================ аудит
async def test_creation_is_audited_without_personal_data(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    body = await submit_request(api, catalog)
    rid = await request_id(committed_session, body["number"])

    entries = (
        (await committed_session.execute(select(AuditLog).where(AuditLog.entity_type == "request")))
        .scalars()
        .all()
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry.action == "request.created"
    assert entry.entity_id == rid
    assert entry.actor == "public"
    assert entry.user_id is None
    assert entry.ip_hash is not None
    assert entry.changes["number"] == body["number"]
    assert entry.changes["status"] == {"old": None, "new": "NEW"}
    assert entry.changes["items_count"] == 1

    serialized = json.dumps(entry.changes, ensure_ascii=False)
    for secret in (CUSTOMER_NAME, CUSTOMER_EMAIL, CUSTOMER_PHONE_NORMALIZED, "7011234567"):
        assert secret not in serialized


async def test_personal_data_is_not_logged(api: AsyncClient, catalog: CatalogFixture) -> None:
    with structlog.testing.capture_logs() as logs:
        await submit_request(api, catalog)

    assert any(entry["event"] == "request_created" for entry in logs)
    dumped = json.dumps(logs, ensure_ascii=False, default=str)
    for secret in (CUSTOMER_NAME, CUSTOMER_EMAIL, "7011234567"):
        assert secret not in dumped


# ======================================================== повтор и лимит
async def test_idempotency_key_prevents_duplicates(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    payload = request_payload(catalog)

    first = await api.post(PUBLIC_REQUESTS, json=payload, headers=headers)
    second = await api.post(PUBLIC_REQUESTS, json=payload, headers=headers)
    other = await api.post(
        PUBLIC_REQUESTS, json=payload, headers={"Idempotency-Key": str(uuid.uuid4())}
    )

    assert first.status_code == second.status_code == other.status_code == 201
    assert first.json() == second.json()
    assert other.json()["number"] != first.json()["number"]
    assert await _count(committed_session, Request) == 2

    audit = (
        await committed_session.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "request.created")
        )
    ).scalar_one()
    assert audit == 2


async def test_concurrent_retries_create_one_request(
    catalog: CatalogFixture, test_engine: AsyncEngine
) -> None:
    """Два одновременных запроса с одним ключом: второй упирается
    в уникальный индекс и получает уже созданную заявку."""
    from app.modules.requests.schemas_public import PublicRequestCreate
    from app.modules.requests.service import RequestSubmissionService
    from app.modules.users.service import RequestContext

    key = str(uuid.uuid4())
    payload = PublicRequestCreate.model_validate(request_payload(catalog))
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def submit() -> str:
        async with session_factory() as session:
            result = await RequestSubmissionService(session).submit(payload, RequestContext(), key)
            return result.number

    numbers = await asyncio.gather(submit(), submit())

    assert numbers[0] == numbers[1]
    async with session_factory() as check:
        assert await _count(check, Request) == 1


@pytest.mark.parametrize("key", ["short", "x" * 65, "has space inside"])
async def test_invalid_idempotency_key(api: AsyncClient, catalog: CatalogFixture, key: str) -> None:
    response = await api.post(
        PUBLIC_REQUESTS, json=request_payload(catalog), headers={"Idempotency-Key": key}
    )
    assert response.status_code == 422


async def test_public_form_is_rate_limited(
    api: AsyncClient,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_FORM", "2/minute")
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
    # Свой адрес на каждый прогон: счётчики в Redis переживают тест
    client_ip = f"203.0.113.{uuid.uuid4().int % 250}"
    headers = {"X-Forwarded-For": client_ip}

    responses = [
        await api.post(PUBLIC_REQUESTS, json=request_payload(catalog), headers=headers)
        for _ in range(3)
    ]

    assert [response.status_code for response in responses] == [201, 201, 429]
    assert responses[2].json()["error"]["code"] == "rate_limited"
    assert await _count(committed_session, Request) == 2

    # Другой клиент не страдает от чужого лимита
    other = await api.post(
        PUBLIC_REQUESTS,
        json=request_payload(catalog),
        headers={"X-Forwarded-For": f"198.51.100.{uuid.uuid4().int % 250}"},
    )
    assert other.status_code == 201


# ====================================================== границы доступа
async def test_public_api_cannot_read_requests(api: AsyncClient, catalog: CatalogFixture) -> None:
    body = await submit_request(api, catalog)

    assert (await api.get(PUBLIC_REQUESTS)).status_code == 405
    assert (await api.get(f"{PUBLIC_REQUESTS}/{body['number']}")).status_code in (404, 405)


async def test_submission_query_count_does_not_grow_with_items(
    api: AsyncClient, catalog: CatalogFixture, test_engine: AsyncEngine
) -> None:
    """Проверка и оценка состава — пакетные: запросов на заявку из трёх
    позиций столько же, сколько на заявку из одной."""
    with count_queries(test_engine) as single:
        await submit_request(api, catalog, items=[{"sku": ROPE, "quantity": "1"}])
    with count_queries(test_engine) as many:
        await submit_request(
            api,
            catalog,
            items=[
                {"sku": ROPE, "quantity": "1"},
                {"sku": FASTENER, "quantity": "1"},
                {"sku": SEAT, "quantity": "1"},
            ],
        )

    selects = [statement for statement in many if statement.lstrip().upper().startswith("SELECT")]
    single_selects = [
        statement for statement in single if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(selects) == len(single_selects)
