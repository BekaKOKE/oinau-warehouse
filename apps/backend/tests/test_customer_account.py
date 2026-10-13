"""Кабинет клиента: профиль, избранное, заявки, проекты, уведомления.

Главное свойство, которое проверяется почти в каждом тесте: клиент
видит и меняет только свои данные. Чужой объект неотличим от
несуществующего (404), а внутренние данные менеджеров не выходят наружу.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.enums import ProductStatus
from app.modules.catalog.models import Product
from app.modules.customers.models import CustomerNotification
from app.modules.requests.models import Request
from tests.catalog_fixtures import CatalogFixture
from tests.customer_helpers import (
    FAVORITES_URL,
    NOTIFICATIONS_URL,
    PROFILE_URL,
    PROJECTS_URL,
    REQUESTS_URL,
)
from tests.request_helpers import ADMIN_REQUESTS, request_payload, submit_request

Headers = dict[str, str]


async def customer_request(
    api: AsyncClient, catalog: CatalogFixture, headers: Headers, **overrides: Any
) -> dict[str, Any]:
    response = await api.post(
        REQUESTS_URL, headers=headers, json=request_payload(catalog, **overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def request_db_id(session: AsyncSession, number: str) -> int:
    return (await session.execute(select(Request.id).where(Request.number == number))).scalar_one()


async def set_product(session: AsyncSession, current_sku: str, **values: Any) -> None:
    query = select(Product).where(Product.sku == current_sku)
    product = (await session.execute(query)).scalar_one()
    for key, value in values.items():
        setattr(product, key, value)
    await session.commit()


# ------------------------------------------------------------------ профиль
async def test_profile_read_and_update(
    api: AsyncClient, catalog: CatalogFixture, customer_headers
) -> None:
    customer, headers = await customer_headers(region_id=catalog.region.id)

    profile = (await api.get(PROFILE_URL, headers=headers)).json()
    assert profile["email"] == customer.email
    assert profile["region"]["code"] == "almaty"
    assert "password_hash" not in profile
    assert "id" not in profile

    updated = await api.patch(
        PROFILE_URL,
        headers=headers,
        json={
            "contact_name": "Новое Имя",
            "company_name": "",
            "phone": "8 (777) 000-11-22",
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["contact_name"] == "Новое Имя"
    assert body["company_name"] is None
    assert body["phone"] == "87770001122"
    assert body["email"] == customer.email


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "hijack@example.kz"},
        {"is_active": False},
        {"email_verified_at": None},
        {"contact_name": ""},
        {"phone": "not a phone"},
    ],
)
async def test_profile_rejects_forbidden_fields(
    api: AsyncClient, customer_headers, payload: dict[str, Any]
) -> None:
    _, headers = await customer_headers()
    response = await api.patch(PROFILE_URL, headers=headers, json=payload)
    assert response.status_code == 422


async def test_profile_rejects_unknown_region(api: AsyncClient, customer_headers) -> None:
    _, headers = await customer_headers()
    response = await api.patch(PROFILE_URL, headers=headers, json={"region_id": 999_999})
    assert response.status_code == 422


async def test_profile_update_touches_only_own_account(api: AsyncClient, customer_headers) -> None:
    _, alice = await customer_headers()
    bob, bob_headers = await customer_headers()

    await api.patch(PROFILE_URL, headers=alice, json={"contact_name": "Алиса"})

    assert (await api.get(PROFILE_URL, headers=bob_headers)).json()["contact_name"] == (
        bob.contact_name
    )


# ---------------------------------------------------------------- избранное
async def test_favorites_add_list_remove(
    api: AsyncClient, catalog: CatalogFixture, customer_headers
) -> None:
    _, headers = await customer_headers()

    first = await api.post(FAVORITES_URL, headers=headers, json={"sku": "KAN-16-PP"})
    again = await api.post(FAVORITES_URL, headers=headers, json={"sku": "KAN-16-PP"})
    await api.post(FAVORITES_URL, headers=headers, json={"sku": "KRP-M10"})

    assert first.status_code == 201
    assert first.json()["slug"] == "kanat-16-pp"
    # Повтор не создаёт дубль и не считается ошибкой
    assert again.status_code == 200

    listed = (await api.get(FAVORITES_URL, headers=headers)).json()
    assert listed["total"] == 2
    assert [item["sku"] for item in listed["items"]] == ["KRP-M10", "KAN-16-PP"]

    assert (await api.delete(f"{FAVORITES_URL}/KAN-16-PP", headers=headers)).status_code == 204
    assert (await api.delete(f"{FAVORITES_URL}/KAN-16-PP", headers=headers)).status_code == 404
    assert (await api.get(FAVORITES_URL, headers=headers)).json()["total"] == 1


@pytest.mark.parametrize("sku", ["DRAFT-1", "DEL-1", "OFF-1", "NO-SUCH-SKU"])
async def test_non_public_products_cannot_be_favorited(
    api: AsyncClient, catalog: CatalogFixture, customer_headers, sku: str
) -> None:
    _, headers = await customer_headers()
    response = await api.post(FAVORITES_URL, headers=headers, json={"sku": sku})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "product_unavailable"


async def test_unpublished_product_disappears_from_favorites(
    api: AsyncClient,
    catalog: CatalogFixture,
    customer_headers,
    committed_session: AsyncSession,
) -> None:
    _, headers = await customer_headers()
    await api.post(FAVORITES_URL, headers=headers, json={"sku": "KAN-16-PP"})
    await api.post(FAVORITES_URL, headers=headers, json={"sku": "SID-01"})

    await set_product(committed_session, "KAN-16-PP", status=ProductStatus.DRAFT.value)
    await set_product(committed_session, "SID-01", deleted_at=datetime.now(UTC))
    hidden = (await api.get(FAVORITES_URL, headers=headers)).json()
    assert hidden["total"] == 0
    assert hidden["items"] == []

    # Снова опубликованный товар возвращается в избранное
    await set_product(committed_session, "KAN-16-PP", status=ProductStatus.PUBLISHED.value)
    restored = (await api.get(FAVORITES_URL, headers=headers)).json()
    assert [item["sku"] for item in restored["items"]] == ["KAN-16-PP"]
    # Убрать скрытый товар из избранного всё равно можно
    assert (await api.delete(f"{FAVORITES_URL}/SID-01", headers=headers)).status_code == 204


async def test_favorites_are_private(
    api: AsyncClient, catalog: CatalogFixture, customer_headers
) -> None:
    _, alice = await customer_headers()
    _, bob = await customer_headers()
    await api.post(FAVORITES_URL, headers=alice, json={"sku": "KAN-16-PP"})

    assert (await api.get(FAVORITES_URL, headers=bob)).json()["total"] == 0
    # Боб не может удалить избранное Алисы
    assert (await api.delete(f"{FAVORITES_URL}/KAN-16-PP", headers=bob)).status_code == 404
    assert (await api.get(FAVORITES_URL, headers=alice)).json()["total"] == 1


# ------------------------------------------------------------------- заявки
async def test_customer_request_is_linked_and_listed(
    api: AsyncClient, catalog: CatalogFixture, customer_headers
) -> None:
    _, headers = await customer_headers()
    created = await customer_request(api, catalog, headers)

    listed = (await api.get(REQUESTS_URL, headers=headers)).json()
    assert listed["total"] == 1
    item = listed["items"][0]
    assert item["number"] == created["number"]
    assert item["status"] == "NEW"
    assert item["items_count"] == 1
    assert item["total_estimate"] == created["total_estimate"]
    assert item["currency"] == "KZT"

    detail = (await api.get(f"{REQUESTS_URL}/{created['number']}", headers=headers)).json()
    assert detail["items"] == [
        {
            "sku": line["sku"],
            "name": line["name"],
            "unit": line["unit"],
            "quantity": line["quantity"],
            "pricing_type": line["pricing_type"],
            "unit_price": line["unit_price"],
            "line_total": line["line_total"],
        }
        for line in created["items"]
    ]
    assert detail["status_history"][0]["status"] == "NEW"


async def test_request_history_uses_snapshots(
    api: AsyncClient,
    catalog: CatalogFixture,
    customer_headers,
    committed_session: AsyncSession,
) -> None:
    """Переименование и снятие товара с публикации не меняют историю."""
    _, headers = await customer_headers()
    created = await customer_request(api, catalog, headers)
    await set_product(committed_session, "KAN-16-PP", sku="KAN-16-PP-NEW", is_active=False)

    detail = (await api.get(f"{REQUESTS_URL}/{created['number']}", headers=headers)).json()
    assert detail["items"][0]["sku"] == "KAN-16-PP"
    assert detail["items"][0]["name"] == created["items"][0]["name"]


async def test_customer_sees_only_own_requests(
    api: AsyncClient, catalog: CatalogFixture, customer_headers
) -> None:
    _, alice = await customer_headers()
    _, bob = await customer_headers()
    alice_request = await customer_request(api, catalog, alice)
    anonymous = await submit_request(api, catalog)

    bob_list = (await api.get(REQUESTS_URL, headers=bob)).json()
    assert bob_list["total"] == 0

    for number in (alice_request["number"], anonymous["number"]):
        response = await api.get(f"{REQUESTS_URL}/{number}", headers=bob)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "request_not_found"
    # Анонимная заявка с сайта не попадает в кабинет даже по совпадению email
    alice_list = (await api.get(REQUESTS_URL, headers=alice)).json()
    assert [item["number"] for item in alice_list["items"]] == [alice_request["number"]]


async def test_requests_pagination(
    api: AsyncClient, catalog: CatalogFixture, customer_headers
) -> None:
    _, headers = await customer_headers()
    numbers = [(await customer_request(api, catalog, headers))["number"] for _ in range(3)]

    page = (await api.get(REQUESTS_URL, headers=headers, params={"page_size": 2})).json()
    second = (
        await api.get(REQUESTS_URL, headers=headers, params={"page_size": 2, "page": 2})
    ).json()

    assert page["total"] == 3
    assert page["pages"] == 2
    assert [item["number"] for item in page["items"]] == numbers[::-1][:2]
    assert [item["number"] for item in second["items"]] == numbers[::-1][2:]
    assert (
        await api.get(REQUESTS_URL, headers=headers, params={"page_size": 500})
    ).status_code == 422


async def test_request_detail_hides_internal_data(
    api: AsyncClient,
    catalog: CatalogFixture,
    customer_headers,
    admin: Headers,
    committed_session: AsyncSession,
) -> None:
    _, headers = await customer_headers()
    created = await customer_request(api, catalog, headers)
    rid = await request_db_id(committed_session, created["number"])

    await api.post(
        f"{ADMIN_REQUESTS}/{rid}/comments",
        headers=admin,
        json={"body": "ВНУТРЕННЕЕ: клиент капризный, скидку не давать"},
    )
    await api.post(
        f"{ADMIN_REQUESTS}/{rid}/comments",
        headers=admin,
        json={"body": "Добрый день! Готовим предложение.", "visible_to_customer": True},
    )
    await api.patch(
        f"{ADMIN_REQUESTS}/{rid}/status",
        headers=admin,
        json={"status": "IN_PROGRESS", "comment": "ВНУТРЕННЕЕ: позвонить директору"},
    )

    response = await api.get(f"{REQUESTS_URL}/{created['number']}", headers=headers)
    assert response.status_code == 200
    detail = response.json()
    assert detail["status"] == "IN_PROGRESS"
    assert [comment["body"] for comment in detail["comments"]] == [
        "Добрый день! Готовим предложение."
    ]
    assert [step["status"] for step in detail["status_history"]] == ["NEW", "IN_PROGRESS"]
    serialized = response.text
    assert "ВНУТРЕННЕЕ" not in serialized
    for internal_field in ("is_internal", "author", "assigned_to", "ip_hash", "user_agent", "utm"):
        assert internal_field not in serialized


async def test_spam_status_is_shown_as_cancelled(
    api: AsyncClient,
    catalog: CatalogFixture,
    customer_headers,
    admin: Headers,
    committed_session: AsyncSession,
) -> None:
    _, headers = await customer_headers()
    created = await customer_request(api, catalog, headers)
    rid = await request_db_id(committed_session, created["number"])
    await api.patch(f"{ADMIN_REQUESTS}/{rid}/status", headers=admin, json={"status": "SPAM"})

    detail = (await api.get(f"{REQUESTS_URL}/{created['number']}", headers=headers)).json()
    listed = (await api.get(REQUESTS_URL, headers=headers)).json()
    assert detail["status"] == "CANCELLED"
    assert listed["items"][0]["status"] == "CANCELLED"
    assert "SPAM" not in str(detail)


async def test_deleted_request_is_hidden(
    api: AsyncClient,
    catalog: CatalogFixture,
    customer_headers,
    committed_session: AsyncSession,
) -> None:
    _, headers = await customer_headers()
    created = await customer_request(api, catalog, headers)
    request = (
        await committed_session.execute(select(Request).where(Request.number == created["number"]))
    ).scalar_one()
    request.deleted_at = datetime.now(UTC)
    await committed_session.commit()

    assert (await api.get(REQUESTS_URL, headers=headers)).json()["total"] == 0
    assert (
        await api.get(f"{REQUESTS_URL}/{created['number']}", headers=headers)
    ).status_code == 404


async def test_idempotency_key_is_bound_to_sender(
    api: AsyncClient, catalog: CatalogFixture, customer_headers
) -> None:
    _, alice = await customer_headers()
    _, bob = await customer_headers()
    key = {"Idempotency-Key": f"key-{uuid.uuid4().hex}"}

    first = await api.post(REQUESTS_URL, headers={**alice, **key}, json=request_payload(catalog))
    replay = await api.post(REQUESTS_URL, headers={**alice, **key}, json=request_payload(catalog))
    stolen = await api.post(REQUESTS_URL, headers={**bob, **key}, json=request_payload(catalog))
    anonymous = await api.post(
        "/api/v1/public/requests", headers=key, json=request_payload(catalog)
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["number"] == first.json()["number"]
    # Чужой ключ не раскрывает состав заявки ни клиенту, ни анонимной форме
    assert stolen.status_code == 409
    assert anonymous.status_code == 409
    assert first.json()["number"] not in stolen.text + anonymous.text


# ------------------------------------------------------------------ проекты
async def test_project_crud_and_items(
    api: AsyncClient, catalog: CatalogFixture, customer_headers
) -> None:
    _, headers = await customer_headers()

    created = await api.post(
        PROJECTS_URL,
        headers=headers,
        json={
            "name": "Двор ЖК «Нурлы»",
            "description": "Площадка 400 м²",
            "region_id": catalog.region.id,
        },
    )
    assert created.status_code == 201
    project = created.json()
    assert project["status"] == "PLANNING"
    assert project["region"]["code"] == "almaty"
    url = f"{PROJECTS_URL}/{project['uuid']}"

    added = await api.post(
        f"{url}/items",
        headers=headers,
        json={"sku": "KAN-16-PP", "quantity": "120", "note": "Сетка"},
    )
    assert added.status_code == 201
    assert added.json()["items"] == [
        {
            "sku": "KAN-16-PP",
            "name": "Канат полипропиленовый 16 мм",
            "slug": "kanat-16-pp",
            "is_available": True,
            "quantity": "120.000",
            "note": "Сетка",
            "added_at": added.json()["items"][0]["added_at"],
        }
    ]
    duplicate = await api.post(f"{url}/items", headers=headers, json={"sku": "KAN-16-PP"})
    assert duplicate.status_code == 409
    unavailable = await api.post(f"{url}/items", headers=headers, json={"sku": "DRAFT-1"})
    assert unavailable.status_code == 422

    patched = await api.patch(
        url, headers=headers, json={"status": "ACTIVE", "description": None, "name": "ЖК «Нурлы»"}
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "ACTIVE"
    assert patched.json()["description"] is None
    assert patched.json()["name"] == "ЖК «Нурлы»"

    listed = (await api.get(PROJECTS_URL, headers=headers)).json()
    assert listed["total"] == 1
    assert listed["items"][0]["items_count"] == 1

    assert (await api.delete(f"{url}/items/KAN-16-PP", headers=headers)).status_code == 204
    assert (await api.delete(f"{url}/items/KAN-16-PP", headers=headers)).status_code == 404

    assert (await api.delete(url, headers=headers)).status_code == 204
    assert (await api.get(url, headers=headers)).status_code == 404
    assert (await api.get(PROJECTS_URL, headers=headers)).json()["total"] == 0


async def test_project_item_survives_unpublishing(
    api: AsyncClient,
    catalog: CatalogFixture,
    customer_headers,
    committed_session: AsyncSession,
) -> None:
    _, headers = await customer_headers()
    project = (await api.post(PROJECTS_URL, headers=headers, json={"name": "Проект"})).json()
    url = f"{PROJECTS_URL}/{project['uuid']}"
    await api.post(f"{url}/items", headers=headers, json={"sku": "SID-01"})

    await set_product(committed_session, "SID-01", status=ProductStatus.ARCHIVED.value)
    item = (await api.get(url, headers=headers)).json()["items"][0]
    assert item["sku"] == "SID-01"
    assert item["is_available"] is False
    assert item["slug"] is None


async def test_request_linked_to_project(
    api: AsyncClient, catalog: CatalogFixture, customer_headers
) -> None:
    _, headers = await customer_headers()
    project = (await api.post(PROJECTS_URL, headers=headers, json={"name": "Школа №5"})).json()

    created = await customer_request(api, catalog, headers, project_uuid=project["uuid"])

    detail = (await api.get(f"{PROJECTS_URL}/{project['uuid']}", headers=headers)).json()
    assert [item["number"] for item in detail["requests"]] == [created["number"]]
    assert detail["requests_count"] == 1
    request = (await api.get(f"{REQUESTS_URL}/{created['number']}", headers=headers)).json()
    assert request["project"] == {"uuid": project["uuid"], "name": "Школа №5"}


async def test_projects_are_private(
    api: AsyncClient, catalog: CatalogFixture, customer_headers
) -> None:
    _, alice = await customer_headers()
    _, bob = await customer_headers()
    project = (await api.post(PROJECTS_URL, headers=alice, json={"name": "Проект Алисы"})).json()
    url = f"{PROJECTS_URL}/{project['uuid']}"

    assert (await api.get(PROJECTS_URL, headers=bob)).json()["total"] == 0
    for response in (
        await api.get(url, headers=bob),
        await api.patch(url, headers=bob, json={"name": "Взлом"}),
        await api.delete(url, headers=bob),
        await api.post(f"{url}/items", headers=bob, json={"sku": "KAN-16-PP"}),
        await api.post(
            REQUESTS_URL, headers=bob, json=request_payload(catalog, project_uuid=project["uuid"])
        ),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "project_not_found"

    # Проект Алисы не изменился
    detail = (await api.get(url, headers=alice)).json()
    assert detail["name"] == "Проект Алисы"
    assert detail["items"] == []
    assert detail["requests"] == []


@pytest.mark.parametrize(
    "payload",
    [{"name": ""}, {"name": "x", "status": "DONE"}, {"name": "x", "customer_id": 1}],
)
async def test_project_validation(
    api: AsyncClient, customer_headers, payload: dict[str, Any]
) -> None:
    _, headers = await customer_headers()
    assert (await api.post(PROJECTS_URL, headers=headers, json=payload)).status_code == 422


# -------------------------------------------------------------- уведомления
async def test_admin_actions_notify_customer(
    api: AsyncClient,
    catalog: CatalogFixture,
    customer_headers,
    admin: Headers,
    committed_session: AsyncSession,
) -> None:
    _, headers = await customer_headers()
    created = await customer_request(api, catalog, headers)
    anonymous = await submit_request(api, catalog)
    rid = await request_db_id(committed_session, created["number"])
    anonymous_id = await request_db_id(committed_session, anonymous["number"])

    await api.patch(f"{ADMIN_REQUESTS}/{rid}/status", headers=admin, json={"status": "QUOTE_SENT"})
    await api.post(f"{ADMIN_REQUESTS}/{rid}/comments", headers=admin, json={"body": "внутренний"})
    await api.post(
        f"{ADMIN_REQUESTS}/{rid}/comments",
        headers=admin,
        json={"body": "КП во вложении", "visible_to_customer": True},
    )
    # Действия с анонимной заявкой уведомлений не создают
    await api.patch(
        f"{ADMIN_REQUESTS}/{anonymous_id}/status", headers=admin, json={"status": "IN_PROGRESS"}
    )

    assert (await api.get(f"{NOTIFICATIONS_URL}/unread-count", headers=headers)).json() == {
        "unread": 2
    }
    listed = (await api.get(NOTIFICATIONS_URL, headers=headers)).json()
    assert [item["type"] for item in listed["items"]] == [
        "REQUEST_COMMENT_ADDED",
        "REQUEST_STATUS_CHANGED",
    ]
    status_note = listed["items"][1]
    assert status_note["payload"] == {"request_number": created["number"], "status": "QUOTE_SENT"}
    # Текст комментария в уведомление не копируется
    assert "КП во вложении" not in listed["items"][0]["message"]
    total = (await committed_session.execute(select(CustomerNotification))).scalars().all()
    assert len(total) == 2


async def test_notifications_read_flow_and_ownership(
    api: AsyncClient,
    catalog: CatalogFixture,
    customer_headers,
    committed_session: AsyncSession,
) -> None:
    alice, alice_headers = await customer_headers()
    _, bob_headers = await customer_headers()
    for index in range(3):
        committed_session.add(
            CustomerNotification(
                customer_id=alice.id, type="SYSTEM", title=f"Сообщение {index}", message="Текст"
            )
        )
    await committed_session.commit()

    listed = (await api.get(NOTIFICATIONS_URL, headers=alice_headers)).json()
    assert listed["total"] == 3
    target = listed["items"][0]["uuid"]

    # Боб не видит и не может отметить чужое уведомление
    assert (await api.get(NOTIFICATIONS_URL, headers=bob_headers)).json()["total"] == 0
    stranger = await api.post(f"{NOTIFICATIONS_URL}/{target}/read", headers=bob_headers)
    assert stranger.status_code == 404
    assert (await api.post(f"{NOTIFICATIONS_URL}/read-all", headers=bob_headers)).json() == {
        "unread": 0
    }
    assert (await api.get(f"{NOTIFICATIONS_URL}/unread-count", headers=alice_headers)).json() == {
        "unread": 3
    }

    read = await api.post(f"{NOTIFICATIONS_URL}/{target}/read", headers=alice_headers)
    assert read.status_code == 200
    assert read.json()["is_read"] is True
    unread_only = (
        await api.get(NOTIFICATIONS_URL, headers=alice_headers, params={"unread": "true"})
    ).json()
    assert unread_only["total"] == 2

    await api.post(f"{NOTIFICATIONS_URL}/read-all", headers=alice_headers)
    assert (await api.get(f"{NOTIFICATIONS_URL}/unread-count", headers=alice_headers)).json() == {
        "unread": 0
    }
    assert (
        await api.post(f"{NOTIFICATIONS_URL}/{uuid.uuid4()}/read", headers=alice_headers)
    ).status_code == 404
