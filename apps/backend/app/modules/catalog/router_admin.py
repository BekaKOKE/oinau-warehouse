"""Admin API каталога — категории и характеристики.

Каждый эндпоинт защищён правом из существующей системы RBAC:
`catalog.read` на чтение, `catalog.write` на изменение. Новых прав
не вводится — конвенция проекта уже задана на этапе 4.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import SessionDep, require_permissions
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams
from app.modules.catalog.schemas_admin import (
    AttributeCreate,
    AttributeOptionCreate,
    AttributeOptionRead,
    AttributeOptionUpdate,
    AttributeRead,
    AttributeUpdate,
    CategoryAttributeRead,
    CategoryAttributesUpdate,
    CategoryCreate,
    CategoryRead,
    CategoryTreeNode,
    CategoryUpdate,
)
from app.modules.catalog.service_admin import AdminAttributeService, AdminCategoryService
from app.modules.users.models import User
from app.modules.users.permissions import CATALOG_READ, CATALOG_WRITE

CatalogReader = Annotated[User, Depends(require_permissions(CATALOG_READ))]
CatalogWriter = Annotated[User, Depends(require_permissions(CATALOG_WRITE))]

IdPath = Annotated[int, Path(ge=1)]
PageQuery = Annotated[int, Query(ge=1, le=10_000)]
PageSizeQuery = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
SearchQuery = Annotated[str | None, Query(max_length=100)]

categories_router = APIRouter(prefix="/categories", tags=["admin:categories"])
attributes_router = APIRouter(prefix="/attributes", tags=["admin:attributes"])


# --------------------------------------------------------------- категории
@categories_router.get("", response_model=Page[CategoryRead], summary="Список категорий")
async def list_categories(
    session: SessionDep,
    _: CatalogReader,
    include_deleted: bool = False,
    is_active: bool | None = None,
    parent_id: Annotated[int | None, Query(ge=1)] = None,
    search: SearchQuery = None,
    page: PageQuery = 1,
    page_size: PageSizeQuery = DEFAULT_PAGE_SIZE,
) -> Page[CategoryRead]:
    """Удалённые категории по умолчанию скрыты — их видно только по
    явному `include_deleted=true`."""
    return await AdminCategoryService(session).list_categories(
        params=PageParams(page=page, page_size=page_size),
        include_deleted=include_deleted,
        is_active=is_active,
        parent_id=parent_id,
        search=search,
    )


@categories_router.get("/tree", response_model=list[CategoryTreeNode], summary="Дерево категорий")
async def get_category_tree(
    session: SessionDep,
    _: CatalogReader,
    include_deleted: bool = False,
) -> list[CategoryTreeNode]:
    return await AdminCategoryService(session).get_tree(include_deleted=include_deleted)


@categories_router.post(
    "",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать категорию",
)
async def create_category(
    payload: CategoryCreate,
    session: SessionDep,
    actor: CatalogWriter,
) -> CategoryRead:
    return await AdminCategoryService(session).create_category(payload, actor)


@categories_router.get("/{category_id}", response_model=CategoryRead, summary="Категория")
async def get_category(
    category_id: IdPath,
    session: SessionDep,
    _: CatalogReader,
) -> CategoryRead:
    return await AdminCategoryService(session).get_category(category_id)


@categories_router.patch(
    "/{category_id}", response_model=CategoryRead, summary="Изменить категорию"
)
async def update_category(
    category_id: IdPath,
    payload: CategoryUpdate,
    session: SessionDep,
    actor: CatalogWriter,
) -> CategoryRead:
    return await AdminCategoryService(session).update_category(category_id, payload, actor)


@categories_router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить категорию (мягко)",
)
async def delete_category(
    category_id: IdPath,
    session: SessionDep,
    actor: CatalogWriter,
) -> None:
    await AdminCategoryService(session).delete_category(category_id, actor)


@categories_router.post(
    "/{category_id}/restore", response_model=CategoryRead, summary="Восстановить категорию"
)
async def restore_category(
    category_id: IdPath,
    session: SessionDep,
    actor: CatalogWriter,
) -> CategoryRead:
    return await AdminCategoryService(session).restore_category(category_id, actor)


# ------------------------------------------- характеристики категории
@categories_router.get(
    "/{category_id}/attributes",
    response_model=list[CategoryAttributeRead],
    summary="Характеристики категории",
)
async def get_category_attributes(
    category_id: IdPath,
    session: SessionDep,
    _: CatalogReader,
) -> list[CategoryAttributeRead]:
    return await AdminCategoryService(session).get_category_attributes(category_id)


@categories_router.put(
    "/{category_id}/attributes",
    response_model=list[CategoryAttributeRead],
    summary="Назначить характеристики категории",
)
async def set_category_attributes(
    category_id: IdPath,
    payload: CategoryAttributesUpdate,
    session: SessionDep,
    actor: CatalogWriter,
) -> list[CategoryAttributeRead]:
    """Полная замена набора: передаётся итоговый список, а не дельта."""
    return await AdminCategoryService(session).set_category_attributes(category_id, payload, actor)


# ---------------------------------------------------------- характеристики
@attributes_router.get("", response_model=Page[AttributeRead], summary="Список характеристик")
async def list_attributes(
    session: SessionDep,
    _: CatalogReader,
    is_active: bool | None = None,
    is_filterable: bool | None = None,
    search: SearchQuery = None,
    page: PageQuery = 1,
    page_size: PageSizeQuery = DEFAULT_PAGE_SIZE,
) -> Page[AttributeRead]:
    return await AdminAttributeService(session).list_attributes(
        params=PageParams(page=page, page_size=page_size),
        is_active=is_active,
        is_filterable=is_filterable,
        search=search,
    )


@attributes_router.post(
    "",
    response_model=AttributeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать характеристику",
)
async def create_attribute(
    payload: AttributeCreate,
    session: SessionDep,
    actor: CatalogWriter,
) -> AttributeRead:
    return await AdminAttributeService(session).create_attribute(payload, actor)


@attributes_router.get("/{attribute_id}", response_model=AttributeRead, summary="Характеристика")
async def get_attribute(
    attribute_id: IdPath,
    session: SessionDep,
    _: CatalogReader,
) -> AttributeRead:
    return await AdminAttributeService(session).get_attribute(attribute_id)


@attributes_router.patch(
    "/{attribute_id}", response_model=AttributeRead, summary="Изменить характеристику"
)
async def update_attribute(
    attribute_id: IdPath,
    payload: AttributeUpdate,
    session: SessionDep,
    actor: CatalogWriter,
) -> AttributeRead:
    """`value_type` не изменяется: смена типа осиротила бы заполненные
    значения товаров."""
    return await AdminAttributeService(session).update_attribute(attribute_id, payload, actor)


@attributes_router.delete(
    "/{attribute_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить характеристику",
)
async def delete_attribute(
    attribute_id: IdPath,
    session: SessionDep,
    actor: CatalogWriter,
) -> None:
    """Только если характеристика не используется товарами."""
    await AdminAttributeService(session).delete_attribute(attribute_id, actor)


# ------------------------------------------------------ варианты значений
@attributes_router.post(
    "/{attribute_id}/options",
    response_model=AttributeOptionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить вариант значения",
)
async def create_option(
    attribute_id: IdPath,
    payload: AttributeOptionCreate,
    session: SessionDep,
    actor: CatalogWriter,
) -> AttributeOptionRead:
    return await AdminAttributeService(session).create_option(attribute_id, payload, actor)


@attributes_router.patch(
    "/{attribute_id}/options/{option_id}",
    response_model=AttributeOptionRead,
    summary="Изменить вариант значения",
)
async def update_option(
    attribute_id: IdPath,
    option_id: IdPath,
    payload: AttributeOptionUpdate,
    session: SessionDep,
    actor: CatalogWriter,
) -> AttributeOptionRead:
    return await AdminAttributeService(session).update_option(
        attribute_id, option_id, payload, actor
    )


@attributes_router.delete(
    "/{attribute_id}/options/{option_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить вариант значения",
)
async def delete_option(
    attribute_id: IdPath,
    option_id: IdPath,
    session: SessionDep,
    actor: CatalogWriter,
) -> None:
    await AdminAttributeService(session).delete_option(attribute_id, option_id, actor)
