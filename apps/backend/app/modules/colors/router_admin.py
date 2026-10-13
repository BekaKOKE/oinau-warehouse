"""Admin API справочника цветов и цветов товара.

Справочник: чтение — `catalog.read`, изменение — `catalog.write`.
Цвета товара несут остаток и надбавку к цене, поэтому их правка требует
обоих прав: `stock.write` и `price.write`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import SessionDep, require_permissions
from app.modules.colors.schemas_admin import (
    ColorCreate,
    ColorRead,
    ColorUpdate,
    ProductColorsRead,
    ProductColorsUpdate,
)
from app.modules.colors.service_admin import AdminColorService, AdminProductColorService
from app.modules.users.models import User
from app.modules.users.permissions import CATALOG_READ, CATALOG_WRITE, PRICE_WRITE, STOCK_WRITE

ColorReader = Annotated[User, Depends(require_permissions(CATALOG_READ))]
ColorWriter = Annotated[User, Depends(require_permissions(CATALOG_WRITE))]
ProductColorWriter = Annotated[User, Depends(require_permissions(STOCK_WRITE, PRICE_WRITE))]

IdPath = Annotated[int, Path(ge=1)]

colors_router = APIRouter(prefix="/colors", tags=["admin:colors"])
product_colors_router = APIRouter(prefix="/products", tags=["admin:colors"])


@colors_router.get("", response_model=list[ColorRead], summary="Справочник цветов")
async def list_colors(
    session: SessionDep, _: ColorReader, is_active: bool | None = None
) -> list[ColorRead]:
    """Весь справочник одним списком: цветов десятки, не тысячи."""
    return await AdminColorService(session).list_colors(is_active=is_active)


@colors_router.post(
    "", response_model=ColorRead, status_code=status.HTTP_201_CREATED, summary="Создать цвет"
)
async def create_color(payload: ColorCreate, session: SessionDep, actor: ColorWriter) -> ColorRead:
    return await AdminColorService(session).create_color(payload, actor)


@colors_router.patch("/{color_id}", response_model=ColorRead, summary="Изменить цвет")
async def update_color(
    color_id: IdPath, payload: ColorUpdate, session: SessionDep, actor: ColorWriter
) -> ColorRead:
    """Код цвета не меняется: он записан в отправленных заявках."""
    return await AdminColorService(session).update_color(color_id, payload, actor)


@colors_router.delete("/{color_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить цвет")
async def delete_color(color_id: IdPath, session: SessionDep, actor: ColorWriter) -> None:
    """Только если цвет не используется товарами — иначе его отключают."""
    await AdminColorService(session).delete_color(color_id, actor)


@product_colors_router.get(
    "/{product_id}/colors", response_model=ProductColorsRead, summary="Цвета товара"
)
async def get_product_colors(
    product_id: IdPath, session: SessionDep, _: ColorReader
) -> ProductColorsRead:
    """Точные остатки по цветам — в отличие от витрины, которая видит статус."""
    return await AdminProductColorService(session).get_product_colors(product_id)


@product_colors_router.put(
    "/{product_id}/colors", response_model=ProductColorsRead, summary="Задать цвета товара"
)
async def set_product_colors(
    product_id: IdPath,
    payload: ProductColorsUpdate,
    session: SessionDep,
    actor: ProductColorWriter,
) -> ProductColorsRead:
    """Полная замена набора: передаётся итоговый список, а не дельта."""
    return await AdminProductColorService(session).set_product_colors(product_id, payload, actor)
