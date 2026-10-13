"""Интеграционные тесты Admin API заявок — /api/v1/admin/requests."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.modules.audit.models import AuditLog
from app.modules.geo.models import Region
from app.modules.requests.models import Request, RequestStatusHistory
from app.modules.users.enums import UserRole
from tests.catalog_fixtures import CatalogFixture
from tests.conftest import Headers
from tests.helpers import count_queries
from tests.request_helpers import (
    ADMIN_REQUESTS,
    CUSTOMER_EMAIL,
    CUSTOMER_NAME,
    CUSTOMER_PHONE_NORMALIZED,
    request_id,
    submit_request,
)


def detail_url(rid: int) -> str:
    return f"{ADMIN_REQUESTS}/{rid}"


def status_url(rid: int) -> str:
    return f"{ADMIN_REQUESTS}/{rid}/status"


def comments_url(rid: int) -> str:
    return f"{ADMIN_REQUESTS}/{rid}/comments"


def history_url(rid: int) -> str:
    return f"{ADMIN_REQUESTS}/{rid}/history"


@pytest.fixture
async def submitted(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> dict[str, Any]:
    """Заявка из двух позиций, созданная через публичный API."""
    body = await submit_request(
        api,
        catalog,
        items=[{"sku": "KAN-16-PP", "quantity": "10"}, {"sku": "SID-01", "quantity": "2"}],
    )
    body["id"] = await request_id(committed_session, body["number"])
    return body


async def _audit(session: AsyncSession, action: str) -> list[AuditLog]:
    query = select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)
    return list((await session.execute(query)).scalars().all())


# ================================================================ список
async def test_list_newest_first_with_pagination(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    numbers = [(await submit_request(api, catalog))["number"] for _ in range(3)]

    first = (await api.get(ADMIN_REQUESTS, headers=admin, params={"page_size": 2})).json()
    second = (
        await api.get(ADMIN_REQUESTS, headers=admin, params={"page_size": 2, "page": 2})
    ).json()

    assert first["total"] == 3
    assert first["pages"] == 2
    assert [item["number"] for item in first["items"] + second["items"]] == numbers[::-1]

    item = first["items"][0]
    assert item["status"] == "NEW"
    assert item["kind"] == "CART"
    assert item["customer_name"] == CUSTOMER_NAME
    assert item["phone"] == CUSTOMER_PHONE_NORMALIZED
    assert item["region"] == {"id": catalog.region.id, "code": "almaty", "name": "Алматы"}
    assert item["items_count"] == 1
    assert Decimal(item["total_estimate"]) == Decimal("32000.00")


async def test_list_sort_whitelist(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    numbers = [(await submit_request(api, catalog))["number"] for _ in range(2)]

    oldest = (await api.get(ADMIN_REQUESTS, headers=admin, params={"sort": "oldest"})).json()
    assert [item["number"] for item in oldest["items"]] == numbers

    injected = await api.get(ADMIN_REQUESTS, headers=admin, params={"sort": "created_at; DROP"})
    assert injected.status_code == 422


async def test_list_filters_by_status_and_region(
    api: AsyncClient,
    admin: Headers,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
) -> None:
    astana = Region(code="astana", name="Астана")
    committed_session.add(astana)
    await committed_session.commit()

    almaty_request = await submit_request(api, catalog)
    astana_request = await submit_request(api, catalog, region_id=astana.id)
    await api.patch(
        status_url(await request_id(committed_session, astana_request["number"])),
        headers=admin,
        json={"status": "IN_PROGRESS"},
    )

    async def numbers(**params: Any) -> list[str]:
        body = (await api.get(ADMIN_REQUESTS, headers=admin, params=params)).json()
        return [item["number"] for item in body["items"]]

    assert await numbers(status="IN_PROGRESS") == [astana_request["number"]]
    assert await numbers(status="NEW") == [almaty_request["number"]]
    assert await numbers(region_id=astana.id) == [astana_request["number"]]
    assert await numbers(region_id=catalog.region.id, status="IN_PROGRESS") == []
    assert (
        await api.get(ADMIN_REQUESTS, headers=admin, params={"status": "UNKNOWN"})
    ).status_code == 422


async def test_list_filters_by_date(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    body = await submit_request(api, catalog)
    created = datetime.fromisoformat(body["created_at"])
    hour = timedelta(hours=1)

    async def total(**params: Any) -> int:
        response = await api.get(ADMIN_REQUESTS, headers=admin, params=params)
        assert response.status_code == 200, response.text
        return int(response.json()["total"])

    assert await total(created_from=(created - hour).isoformat()) == 1
    assert await total(created_from=(created + hour).isoformat()) == 0
    assert await total(created_to=(created + hour).isoformat()) == 1
    assert await total(created_to=(created - hour).isoformat()) == 0
    assert (
        await total(
            created_from=(created - hour).isoformat(), created_to=(created + hour).isoformat()
        )
        == 1
    )
    # Время без пояса — UTC
    naive = (created - hour).astimezone(UTC).replace(tzinfo=None).isoformat()
    assert await total(created_from=naive) == 1

    inverted = await api.get(
        ADMIN_REQUESTS,
        headers=admin,
        params={"created_from": created.isoformat(), "created_to": created.isoformat()},
    )
    assert inverted.status_code == 422
    assert inverted.json()["error"]["code"] == "invalid_date_range"


@pytest.mark.parametrize(
    "term",
    ["Петров", "petrov@example", "+7701123", "701 123-45", "ТОО Детские"],
)
async def test_search_by_contacts(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, term: str
) -> None:
    body = await submit_request(api, catalog)
    await submit_request(
        api,
        catalog,
        name="Анна Смирнова",
        phone="+77470000000",
        email="anna@example.kz",
        company="ИП Смирнова",
    )

    found = (await api.get(ADMIN_REQUESTS, headers=admin, params={"search": term})).json()
    assert [item["number"] for item in found["items"]] == [body["number"]]


async def test_search_by_number(api: AsyncClient, admin: Headers, catalog: CatalogFixture) -> None:
    first = await submit_request(api, catalog)
    await submit_request(api, catalog)

    found = (
        await api.get(ADMIN_REQUESTS, headers=admin, params={"search": first["number"]})
    ).json()
    assert [item["number"] for item in found["items"]] == [first["number"]]


async def test_soft_deleted_request_is_hidden(
    api: AsyncClient, admin: Headers, submitted: dict[str, Any], committed_session: AsyncSession
) -> None:
    await committed_session.execute(
        update(Request).where(Request.id == submitted["id"]).values(deleted_at=datetime.now(UTC))
    )
    await committed_session.commit()

    assert (await api.get(ADMIN_REQUESTS, headers=admin)).json()["total"] == 0
    assert (await api.get(detail_url(submitted["id"]), headers=admin)).status_code == 404
    assert (
        await api.patch(status_url(submitted["id"]), headers=admin, json={"status": "SPAM"})
    ).status_code == 404


# ============================================================== карточка
async def test_detail(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, submitted: dict[str, Any]
) -> None:
    response = await api.get(detail_url(submitted["id"]), headers=admin)
    assert response.status_code == 200
    body = response.json()

    assert body["number"] == submitted["number"]
    assert body["status"] == "NEW"
    assert body["kind"] == "CART"
    assert body["source"] == "CATALOG_CART"
    assert body["customer_name"] == CUSTOMER_NAME
    assert body["phone"] == CUSTOMER_PHONE_NORMALIZED
    assert body["email"] == CUSTOMER_EMAIL
    assert body["company"] == "ТОО Детские площадки"
    assert body["comment"] == "Нужна доставка до объекта"
    assert body["region"]["code"] == "almaty"
    assert body["currency"] == "KZT"
    # Одна позиция «по запросу» — общей суммы нет
    assert body["total_estimate"] is None
    assert body["created_at"] and body["updated_at"]

    assert [
        (item["sku"], item["name"], item["unit"], item["pricing_type"], item["quantity"])
        for item in body["items"]
    ] == [
        ("KAN-16-PP", "Канат полипропиленовый 16 мм", "m", "TIERED", "10.000"),
        ("SID-01", "Сиденье качелей HDPE", "pcs", "ON_REQUEST", "2.000"),
    ]
    assert body["items"][0]["product_id"] == catalog.products["rope"].id
    assert Decimal(body["items"][0]["unit_price"]) == Decimal("3200.00")
    assert Decimal(body["items"][0]["line_total"]) == Decimal("32000.00")
    assert body["items"][1]["unit_price"] is None

    assert body["comments"] == []
    assert [(entry["from_status"], entry["to_status"]) for entry in body["status_history"]] == [
        (None, "NEW")
    ]
    assert body["status_history"][0]["changed_by"] is None


async def test_detail_shows_snapshot_not_current_product(
    api: AsyncClient,
    admin: Headers,
    catalog: CatalogFixture,
    submitted: dict[str, Any],
    committed_session: AsyncSession,
) -> None:
    catalog.products["rope"].sku = "KAN-16-NEW"
    await committed_session.commit()

    body = (await api.get(detail_url(submitted["id"]), headers=admin)).json()
    assert body["items"][0]["sku"] == "KAN-16-PP"


@pytest.mark.parametrize("method", ["detail", "status", "comments", "add_comment", "history"])
async def test_unknown_request_returns_404(api: AsyncClient, admin: Headers, method: str) -> None:
    calls = {
        "detail": lambda: api.get(detail_url(999_999), headers=admin),
        "status": lambda: api.patch(
            status_url(999_999), headers=admin, json={"status": "IN_PROGRESS"}
        ),
        "comments": lambda: api.get(comments_url(999_999), headers=admin),
        "add_comment": lambda: api.post(comments_url(999_999), headers=admin, json={"body": "x"}),
        "history": lambda: api.get(history_url(999_999), headers=admin),
    }
    response = await calls[method]()
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "request_not_found"


# ================================================================ статусы
async def _me(api: AsyncClient, headers: Headers, session: AsyncSession) -> tuple[int, dict]:
    """Внутренний id сотрудника (для журнала) и его ссылка в ответах API."""
    from app.modules.users.models import User

    me = (await api.get("/api/v1/admin/auth/me", headers=headers)).json()
    user_id = (
        await session.execute(select(User.id).where(User.uuid == uuid.UUID(me["uuid"])))
    ).scalar_one()
    return user_id, {"uuid": me["uuid"], "full_name": me["full_name"]}


async def test_status_change_is_recorded(
    api: AsyncClient,
    login_as,
    submitted: dict[str, Any],
    committed_session: AsyncSession,
) -> None:
    manager = await login_as(UserRole.MANAGER)
    manager_id, manager_ref = await _me(api, manager, committed_session)

    response = await api.patch(
        status_url(submitted["id"]),
        headers=manager,
        json={"status": "IN_PROGRESS", "comment": "Позвонил клиенту"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"

    await api.patch(status_url(submitted["id"]), headers=manager, json={"status": "QUOTE_SENT"})

    history = (await api.get(history_url(submitted["id"]), headers=manager)).json()
    assert [(entry["from_status"], entry["to_status"]) for entry in history] == [
        (None, "NEW"),
        ("NEW", "IN_PROGRESS"),
        ("IN_PROGRESS", "QUOTE_SENT"),
    ]
    assert history[1]["comment"] == "Позвонил клиенту"
    assert history[1]["changed_by"] == manager_ref

    entries = await _audit(committed_session, "request.status_updated")
    assert [entry.changes["status"] for entry in entries] == [
        {"old": "NEW", "new": "IN_PROGRESS"},
        {"old": "IN_PROGRESS", "new": "QUOTE_SENT"},
    ]
    assert all(entry.user_id == manager_id for entry in entries)
    assert all(entry.entity_id == submitted["id"] for entry in entries)
    assert all(entry.entity_type == "request" for entry in entries)


async def test_any_transition_is_allowed(
    api: AsyncClient, admin: Headers, submitted: dict[str, Any]
) -> None:
    """Движка workflow нет: из SPAM можно вернуть в работу."""
    for status in ("SPAM", "IN_PROGRESS", "COMPLETED", "NEW"):
        response = await api.patch(
            status_url(submitted["id"]), headers=admin, json={"status": status}
        )
        assert response.status_code == 200
        assert response.json()["status"] == status


async def test_same_status_is_a_no_op(
    api: AsyncClient,
    admin: Headers,
    submitted: dict[str, Any],
    committed_session: AsyncSession,
) -> None:
    response = await api.patch(status_url(submitted["id"]), headers=admin, json={"status": "NEW"})
    assert response.status_code == 200
    assert len(response.json()["status_history"]) == 1
    assert await _audit(committed_session, "request.status_updated") == []


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "DONE"},
        {},
        {"status": "NEW", "user_id": 1},
        {"status": "NEW", "comment": "x" * 2001},
    ],
)
async def test_invalid_status_payload(
    api: AsyncClient, admin: Headers, submitted: dict[str, Any], payload: dict[str, Any]
) -> None:
    response = await api.patch(status_url(submitted["id"]), headers=admin, json=payload)
    assert response.status_code == 422


async def test_concurrent_status_changes_keep_history_consistent(
    submitted: dict[str, Any], test_engine: AsyncEngine, make_user
) -> None:
    """Строка заявки блокируется: цепочка переходов в истории непрерывна."""
    from app.modules.requests.enums import RequestStatus
    from app.modules.requests.schemas_admin import RequestStatusUpdate
    from app.modules.requests.service_admin import AdminRequestService

    actor = await make_user(role=UserRole.MANAGER)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def change(status: RequestStatus) -> None:
        async with session_factory() as session:
            await AdminRequestService(session).update_status(
                submitted["id"], RequestStatusUpdate(status=status), actor
            )

    await asyncio.gather(change(RequestStatus.IN_PROGRESS), change(RequestStatus.SPAM))

    async with session_factory() as session:
        history = (
            (
                await session.execute(
                    select(RequestStatusHistory)
                    .where(RequestStatusHistory.request_id == submitted["id"])
                    .order_by(RequestStatusHistory.id)
                )
            )
            .scalars()
            .all()
        )
        current = (
            await session.execute(select(Request.status).where(Request.id == submitted["id"]))
        ).scalar_one()

    assert len(history) == 3
    for previous, entry in pairwise(history):
        assert entry.from_status == previous.to_status
    assert history[-1].to_status == current


# ============================================================ комментарии
async def test_add_and_list_comments(
    api: AsyncClient,
    login_as,
    submitted: dict[str, Any],
    committed_session: AsyncSession,
) -> None:
    manager = await login_as(UserRole.MANAGER)
    manager_id, manager_ref = await _me(api, manager, committed_session)

    created = await api.post(
        comments_url(submitted["id"]),
        headers=manager,
        json={"body": "  Клиент просит перезвонить после 18:00 на +77019998877  "},
    )
    assert created.status_code == 201
    comment = created.json()
    assert comment["body"] == "Клиент просит перезвонить после 18:00 на +77019998877"
    assert comment["is_internal"] is True
    assert comment["author"] == manager_ref

    await api.post(comments_url(submitted["id"]), headers=manager, json={"body": "Второй"})

    listed = (await api.get(comments_url(submitted["id"]), headers=manager)).json()
    assert [item["body"] for item in listed] == [comment["body"], "Второй"]

    detail = (await api.get(detail_url(submitted["id"]), headers=manager)).json()
    assert [item["id"] for item in detail["comments"]] == [item["id"] for item in listed]

    # Аудит без текста комментария: там могут быть контакты клиента
    entries = await _audit(committed_session, "request.comment_created")
    assert len(entries) == 2
    assert entries[0].changes == {"comment_id": comment["id"]}
    assert entries[0].user_id == manager_id
    assert "+77019998877" not in json.dumps([entry.changes for entry in entries])


@pytest.mark.parametrize(
    "payload",
    [{"body": ""}, {"body": "   "}, {"body": "x" * 5001}, {}, {"body": "x", "is_internal": False}],
)
async def test_invalid_comment(
    api: AsyncClient, admin: Headers, submitted: dict[str, Any], payload: dict[str, Any]
) -> None:
    response = await api.post(comments_url(submitted["id"]), headers=admin, json=payload)
    assert response.status_code == 422


async def test_comments_are_not_public(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, submitted: dict[str, Any]
) -> None:
    await api.post(comments_url(submitted["id"]), headers=admin, json={"body": "Секретная пометка"})

    # Публичного чтения заявки нет, а ответ на создание не содержит комментариев
    assert (await api.get("/api/v1/public/requests")).status_code == 405
    fresh = await submit_request(api, catalog)
    assert "comments" not in fresh
    assert "Секретная пометка" not in json.dumps(fresh, ensure_ascii=False)


# ================================================================== RBAC
@pytest.mark.parametrize(
    ("role", "read_status", "write_status"),
    [
        (UserRole.SUPERADMIN, 200, 200),
        (UserRole.ADMIN, 200, 200),
        (UserRole.MANAGER, 200, 200),
        (UserRole.VIEWER, 200, 403),
        (UserRole.CONTENT_MANAGER, 403, 403),
    ],
)
async def test_request_permissions(
    api: AsyncClient,
    login_as,
    submitted: dict[str, Any],
    role: UserRole,
    read_status: int,
    write_status: int,
) -> None:
    headers = await login_as(role)
    rid = submitted["id"]

    for url in (ADMIN_REQUESTS, detail_url(rid), comments_url(rid), history_url(rid)):
        assert (await api.get(url, headers=headers)).status_code == read_status, url

    status_change = await api.patch(
        status_url(rid), headers=headers, json={"status": "IN_PROGRESS"}
    )
    assert status_change.status_code == write_status
    comment = await api.post(comments_url(rid), headers=headers, json={"body": "Комментарий"})
    assert comment.status_code == (201 if write_status == 200 else 403)
    if write_status == 403:
        assert comment.json()["error"]["details"]["required"] == ["request.write"]


async def test_manager_has_no_catalog_stock_pricing_or_user_write(
    api: AsyncClient, login_as, catalog: CatalogFixture
) -> None:
    manager = await login_as(UserRole.MANAGER)
    product_id = catalog.products["rope"].id

    denied = [
        await api.patch(
            f"/api/v1/admin/products/{product_id}", headers=manager, json={"is_featured": False}
        ),
        await api.put(
            f"/api/v1/admin/products/{product_id}/stock",
            headers=manager,
            json={"items": [{"warehouse_id": catalog.warehouse.id, "quantity": "1"}]},
        ),
        await api.put(
            f"/api/v1/admin/products/{product_id}/pricing",
            headers=manager,
            json={"pricing_type": "ON_REQUEST", "tiers": []},
        ),
        await api.get("/api/v1/admin/users", headers=manager),
    ]
    assert [response.status_code for response in denied] == [403, 403, 403, 403]


async def test_anonymous_access_is_rejected(api: AsyncClient, submitted: dict[str, Any]) -> None:
    rid = submitted["id"]
    assert (await api.get(ADMIN_REQUESTS)).status_code == 401
    assert (await api.get(detail_url(rid))).status_code == 401
    assert (await api.get(history_url(rid))).status_code == 401
    assert (await api.get(comments_url(rid))).status_code == 401
    assert (await api.patch(status_url(rid), json={"status": "SPAM"})).status_code == 401
    assert (await api.post(comments_url(rid), json={"body": "x"})).status_code == 401


# ================================================================= аудит
async def test_reads_are_not_audited(
    api: AsyncClient, admin: Headers, submitted: dict[str, Any], committed_session: AsyncSession
) -> None:
    rid = submitted["id"]
    for url in (ADMIN_REQUESTS, detail_url(rid), comments_url(rid), history_url(rid)):
        assert (await api.get(url, headers=admin)).status_code == 200

    entries = (
        (await committed_session.execute(select(AuditLog).where(AuditLog.entity_type == "request")))
        .scalars()
        .all()
    )
    # Только создание заявки
    assert [entry.action for entry in entries] == ["request.created"]


# ========================================================== производительность
async def test_list_query_count_is_fixed(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, test_engine: AsyncEngine
) -> None:
    await submit_request(api, catalog)
    with count_queries(test_engine) as single:
        await api.get(ADMIN_REQUESTS, headers=admin)

    for _ in range(5):
        await submit_request(
            api,
            catalog,
            items=[{"sku": "KAN-16-PP", "quantity": "1"}, {"sku": "KRP-M10", "quantity": "1"}],
        )
    with count_queries(test_engine) as many:
        body = (await api.get(ADMIN_REQUESTS, headers=admin)).json()

    assert body["total"] == 6
    assert len(many) == len(single)


async def test_detail_query_count_is_fixed(
    api: AsyncClient,
    admin: Headers,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
    test_engine: AsyncEngine,
    login_as,
) -> None:
    small = await submit_request(api, catalog)
    small_id = await request_id(committed_session, small["number"])
    # Комментарий и переход от одного автора — чтобы оба варианта
    # загружали имена авторов
    await api.post(comments_url(small_id), headers=admin, json={"body": "Первый"})
    await api.patch(status_url(small_id), headers=admin, json={"status": "IN_PROGRESS"})
    with count_queries(test_engine) as single:
        await api.get(detail_url(small_id), headers=admin)

    big = await submit_request(
        api,
        catalog,
        items=[
            {"sku": "KAN-16-PP", "quantity": "1"},
            {"sku": "KRP-M10", "quantity": "1"},
            {"sku": "SID-01", "quantity": "1"},
        ],
    )
    big_id = await request_id(committed_session, big["number"])
    other = await login_as(UserRole.MANAGER)
    for index in range(3):
        await api.post(comments_url(big_id), headers=admin, json={"body": f"A{index}"})
        await api.post(comments_url(big_id), headers=other, json={"body": f"M{index}"})
    for status in ("IN_PROGRESS", "QUOTE_SENT", "APPROVED"):
        await api.patch(status_url(big_id), headers=other, json={"status": status})

    with count_queries(test_engine) as many:
        body = (await api.get(detail_url(big_id), headers=admin)).json()

    assert len(body["items"]) == 3
    assert len(body["comments"]) == 6
    assert len(body["status_history"]) == 4
    assert len(many) == len(single)
