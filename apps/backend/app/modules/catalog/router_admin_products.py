"""Admin API товаров — /api/v1/admin/products."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import SessionDep, require_permissions
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams
from app.modules.catalog.enums import ProductStatus
from app.modules.catalog.repository_admin_products import ProductAdminFilters, ProductAdminSort
from app.modules.catalog.schemas_admin_products import (
    ProductAttributesUpdate,
    ProductCategoriesUpdate,
    ProductCreate,
    ProductListRow,
    ProductRead,
    ProductUpdate,
)
from app.modules.catalog.service_admin_products import AdminProductService
from app.modules.users.models import User
from app.modules.users.permissions import CATALOG_READ, CATALOG_WRITE

CatalogReader = Annotated[User, Depends(require_permissions(CATALOG_READ))]
CatalogWriter = Annotated[User, Depends(require_permissions(CATALOG_WRITE))]

IdPath = Annotated[int, Path(ge=1)]

router = APIRouter(prefix="/products", tags=["admin:products"])


@router.get("", response_model=Page[ProductListRow], summary="Список товаров")
async def list_products(
    session: SessionDep,
    _: CatalogReader,
    search: Annotated[str | None, Query(max_length=100)] = None,
    product_status: Annotated[ProductStatus | None, Query(alias="status")] = None,
    is_active: bool | None = None,
    is_featured: bool | None = None,
    category_id: Annotated[int | None, Query(ge=1)] = None,
    external_id: Annotated[str | None, Query(max_length=64)] = None,
    include_deleted: bool = False,
    sort: ProductAdminSort = ProductAdminSort.UPDATED,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[ProductListRow]:
    """Удалённые товары скрыты, пока не запрошены явно. Строка содержит
    обложку, цену публичного прайс-листа и публичный статус наличия."""
    filters = ProductAdminFilters(
        search=search,
        status=product_status.value if product_status else None,
        is_active=is_active,
        is_featured=is_featured,
        category_id=category_id,
        external_id=external_id,
        include_deleted=include_deleted,
    )
    return await AdminProductService(session).list_products(
        filters=filters, sort=sort, params=PageParams(page=page, page_size=page_size)
    )


@router.post(
    "", response_model=ProductRead, status_code=status.HTTP_201_CREATED, summary="Создать товар"
)
async def create_product(
    payload: ProductCreate,
    session: SessionDep,
    actor: CatalogWriter,
) -> ProductRead:
    """Категории и характеристики можно передать сразу: иначе между
    созданием товара и привязкой раздела существует окно, в котором
    товар висит без категории."""
    return await AdminProductService(session).create_product(payload, actor)


@router.get("/{product_id}", response_model=ProductRead, summary="Карточка товара")
async def get_product(
    product_id: IdPath,
    session: SessionDep,
    _: CatalogReader,
) -> ProductRead:
    return await AdminProductService(session).get_product(product_id)


@router.patch("/{product_id}", response_model=ProductRead, summary="Изменить товар")
async def update_product(
    product_id: IdPath,
    payload: ProductUpdate,
    session: SessionDep,
    actor: CatalogWriter,
) -> ProductRead:
    return await AdminProductService(session).update_product(product_id, payload, actor)


@router.delete(
    "/{product_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить товар (мягко)"
)
async def delete_product(
    product_id: IdPath,
    session: SessionDep,
    actor: CatalogWriter,
) -> None:
    await AdminProductService(session).delete_product(product_id, actor)


@router.post("/{product_id}/restore", response_model=ProductRead, summary="Восстановить товар")
async def restore_product(
    product_id: IdPath,
    session: SessionDep,
    actor: CatalogWriter,
) -> ProductRead:
    return await AdminProductService(session).restore_product(product_id, actor)


@router.put("/{product_id}/categories", response_model=ProductRead, summary="Категории товара")
async def set_categories(
    product_id: IdPath,
    payload: ProductCategoriesUpdate,
    session: SessionDep,
    actor: CatalogWriter,
) -> ProductRead:
    """Полная замена набора. Если основная категория не указана явно,
    ею становится первая в списке."""
    return await AdminProductService(session).set_categories(product_id, payload, actor)


@router.put("/{product_id}/attributes", response_model=ProductRead, summary="Характеристики товара")
async def set_attributes(
    product_id: IdPath,
    payload: ProductAttributesUpdate,
    session: SessionDep,
    actor: CatalogWriter,
) -> ProductRead:
    """Полная замена набора значений."""
    return await AdminProductService(session).set_attributes(product_id, payload, actor)
