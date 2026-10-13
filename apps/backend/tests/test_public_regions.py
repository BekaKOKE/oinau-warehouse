"""Публичный справочник регионов.

Форма заявки обязана знать допустимые `region_id`: без этого списка
фронтенду пришлось бы хардкодить идентификаторы из базы.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.geo.models import Region
from tests.catalog_fixtures import CatalogFixture

REGIONS_URL = "/api/v1/public/regions"


async def test_returns_active_regions(api: AsyncClient, catalog: CatalogFixture) -> None:
    response = await api.get(REGIONS_URL)
    assert response.status_code == 200

    body = response.json()
    assert [item["code"] for item in body] == ["almaty"]
    assert body[0]["name"] == "Алматы"
    # `id` наружу выходит намеренно: именно его принимает заявка.
    assert body[0]["id"] == catalog.region.id


async def test_inactive_region_is_hidden(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    committed_session.add(Region(code="hidden", name="Отключённый", is_active=False))
    await committed_session.commit()

    codes = {item["code"] for item in (await api.get(REGIONS_URL)).json()}
    assert codes == {"almaty"}


async def test_regions_are_ordered_by_sort_order(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    """Первым идёт основной регион, а не первый по алфавиту."""
    committed_session.add(Region(code="astana", name="Астана", sort_order=1))
    catalog.region.sort_order = 0
    await committed_session.commit()

    codes = [item["code"] for item in (await api.get(REGIONS_URL)).json()]
    assert codes == ["almaty", "astana"]


async def test_response_has_no_internal_fields(api: AsyncClient, catalog: CatalogFixture) -> None:
    body = (await api.get(REGIONS_URL)).json()
    assert set(body[0]) == {"id", "code", "name"}
