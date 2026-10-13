"""Общие помощники тестов заявок."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.requests.models import Request
from tests.catalog_fixtures import CatalogFixture

PUBLIC_REQUESTS = "/api/v1/public/requests"
ADMIN_REQUESTS = "/api/v1/admin/requests"

# Контакты, которые не должны просочиться ни в журнал, ни в логи
CUSTOMER_NAME = "Иван Петров"
CUSTOMER_PHONE = "+7 (701) 123-45-67"
CUSTOMER_PHONE_NORMALIZED = "+77011234567"
CUSTOMER_EMAIL = "ivan.petrov@example.kz"


def request_payload(
    catalog: CatalogFixture, items: list[dict[str, Any]] | None = None, **overrides: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": CUSTOMER_NAME,
        "phone": CUSTOMER_PHONE,
        "email": CUSTOMER_EMAIL,
        "company": "ТОО Детские площадки",
        "region_id": catalog.region.id,
        "comment": "Нужна доставка до объекта",
        "items": items if items is not None else [{"sku": "KAN-16-PP", "quantity": "10"}],
    }
    body.update(overrides)
    return body


async def submit_request(
    api: AsyncClient, catalog: CatalogFixture, **overrides: Any
) -> dict[str, Any]:
    response = await api.post(PUBLIC_REQUESTS, json=request_payload(catalog, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


async def request_id(session: AsyncSession, number: str) -> int:
    query = select(Request.id).where(Request.number == number)
    return (await session.execute(query)).scalar_one()


async def load_request(session: AsyncSession, number: str) -> Request:
    query = (
        select(Request).where(Request.number == number).execution_options(populate_existing=True)
    )
    return (await session.execute(query)).scalar_one()
