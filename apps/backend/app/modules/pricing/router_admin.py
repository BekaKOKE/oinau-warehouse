"""Admin API ценообразования."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import SessionDep, require_permissions
from app.modules.pricing.schemas_admin import PriceListRead, PricingRead, PricingUpdate
from app.modules.pricing.service_admin import AdminPricingService
from app.modules.users.models import User
from app.modules.users.permissions import CATALOG_READ, CATALOG_WRITE

CatalogReader = Annotated[User, Depends(require_permissions(CATALOG_READ))]
CatalogWriter = Annotated[User, Depends(require_permissions(CATALOG_WRITE))]

IdPath = Annotated[int, Path(ge=1)]

product_pricing_router = APIRouter(prefix="/products", tags=["admin:pricing"])
pricing_router = APIRouter(prefix="/pricing", tags=["admin:pricing"])


@product_pricing_router.get(
    "/{product_id}/pricing", response_model=PricingRead, summary="Цены товара"
)
async def get_pricing(
    product_id: IdPath,
    session: SessionDep,
    _: CatalogReader,
) -> PricingRead:
    return await AdminPricingService(session).get_pricing(product_id)


@product_pricing_router.put(
    "/{product_id}/pricing", response_model=PricingRead, summary="Заменить цены товара"
)
async def set_pricing(
    product_id: IdPath,
    payload: PricingUpdate,
    session: SessionDep,
    actor: CatalogWriter,
) -> PricingRead:
    """Полная замена: тип цены и набор ступеней меняются одной транзакцией."""
    return await AdminPricingService(session).set_pricing(product_id, payload, actor)


@pricing_router.get("/price-list", response_model=PriceListRead, summary="Публичный прайс-лист")
async def get_price_list(
    session: SessionDep,
    _: CatalogReader,
) -> PriceListRead:
    """Нужен админке, чтобы показать валюту рядом с полями ввода цены.

    Управления прайс-листами здесь нет: на старте существует только
    прайс по умолчанию.
    """
    return await AdminPricingService(session).get_price_list()
