"""Справочник регионов — /api/v1/public/regions.

Публичная заявка принимает `region_id`, поэтому форма на сайте обязана
знать список допустимых значений. Без этого эндпоинта фронтенду
пришлось бы хардкодить идентификаторы из базы.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.modules.geo.repository import RegionRepository
from app.modules.geo.schemas import RegionRead

router = APIRouter(tags=["geo"])


@router.get("/regions", response_model=list[RegionRead], summary="Регионы доставки")
async def list_regions(session: SessionDep) -> list[RegionRead]:
    regions = await RegionRepository(session).list_active()
    return [RegionRead(id=item.id, code=item.code, name=item.name) for item in regions]
