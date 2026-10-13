"""Публичный каталог — /api/v1/public.

Без авторизации. Все параметры запроса валидируются, размер страницы
и длина поискового запроса ограничены, сортировка — только из белого
списка.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Path, Query
from fastapi.exceptions import RequestValidationError

from app.api.deps import SessionDep
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams
from app.modules.catalog.enums import ProductSort
from app.modules.catalog.repository import MAX_SEARCH_LENGTH, ProductFilters
from app.modules.catalog.schemas import (
    CategoryDetail,
    CategoryNode,
    FacetRead,
    ProductDetail,
    ProductListItem,
)
from app.modules.catalog.service import CatalogService, resolve_locale
from app.modules.inventory.enums import PublicAvailability

router = APIRouter(tags=["catalog"])

# Локаль приходит параметром, а не только из Accept-Language: язык
# должен переключаться ссылкой и попадать в URL, иначе поисковые
# системы не увидят вторую языковую версию.
LocaleQuery = Annotated[str | None, Query(max_length=8, description="Код языка, например ru")]

# Slug приходит параметром пути. Ограничение набора символов отсекает
# мусор до обращения к БД и делает невозможными сюрпризы вроде обхода
# пути или управляющих символов в URL. Одна аннотация на все эндпоинты:
# разъехавшиеся правила валидации — источник неожиданных 404 вместо 422.
SlugPath = Annotated[str, Path(min_length=1, max_length=200, pattern=r"^[a-z0-9-]+$")]


@router.get("/categories", response_model=list[CategoryNode], summary="Дерево категорий")
async def list_categories(session: SessionDep, locale: LocaleQuery = None) -> list[CategoryNode]:
    primary, fallback = resolve_locale(locale)
    return await CatalogService(session).get_category_tree(primary, fallback)


@router.get("/categories/{slug}", response_model=CategoryDetail, summary="Категория")
async def get_category(
    slug: SlugPath,
    session: SessionDep,
    locale: LocaleQuery = None,
) -> CategoryDetail:
    primary, fallback = resolve_locale(locale)
    return await CatalogService(session).get_category(slug, primary, fallback)


# Фильтр по характеристике: `attr=color:black`. Значение проверяется
# шаблоном до обращения к БД; число фильтров ограничено.
AttrQuery = Annotated[
    list[str],
    Query(
        max_length=20,
        description="Фильтр по характеристике: код:slug варианта, например color:black",
    ),
]
_ATTR_PATTERN = re.compile(r"^[a-z0-9_]{1,64}:[a-z0-9-]{1,200}$")


def parse_attribute_filters(values: list[str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    grouped: dict[str, list[str]] = {}
    for value in values:
        if not _ATTR_PATTERN.fullmatch(value):
            raise RequestValidationError(
                [
                    {
                        "type": "value_error",
                        "loc": ("query", "attr"),
                        "msg": "Ожидается код:slug, например color:black",
                        "input": value,
                    }
                ]
            )
        code, slug = value.split(":", 1)
        if slug not in grouped.setdefault(code, []):
            grouped[code].append(slug)
    return tuple((code, tuple(slugs)) for code, slugs in sorted(grouped.items()))


@router.get(
    "/categories/{slug}/facets",
    response_model=list[FacetRead],
    summary="Фильтры раздела по характеристикам",
)
async def get_category_facets(
    slug: SlugPath,
    session: SessionDep,
    locale: LocaleQuery = None,
) -> list[FacetRead]:
    primary, fallback = resolve_locale(locale)
    return await CatalogService(session).get_category_facets(slug, primary, fallback)


@router.get("/products", response_model=Page[ProductListItem], summary="Список товаров")
async def list_products(
    session: SessionDep,
    locale: LocaleQuery = None,
    category: Annotated[str | None, Query(max_length=200)] = None,
    search: Annotated[str | None, Query(max_length=MAX_SEARCH_LENGTH)] = None,
    availability: PublicAvailability | None = None,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    featured: bool | None = None,
    attr: AttrQuery = [],  # noqa: B006 — FastAPI копирует значение по умолчанию
    sort: ProductSort = ProductSort.RELEVANCE,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[ProductListItem]:
    """Отдаёт только опубликованные, активные и не удалённые товары."""
    primary, fallback = resolve_locale(locale)
    filters = ProductFilters(
        category_slug=category,
        search=search,
        availability=availability.value if availability else None,
        min_price=min_price,
        max_price=max_price,
        featured=featured,
        attributes=parse_attribute_filters(attr),
    )
    return await CatalogService(session).list_products(
        filters=filters,
        sort=sort,
        params=PageParams(page=page, page_size=page_size),
        locale=primary,
        fallback=fallback,
    )


@router.get("/products/{slug}", response_model=ProductDetail, summary="Карточка товара")
async def get_product(
    slug: SlugPath,
    session: SessionDep,
    locale: LocaleQuery = None,
) -> ProductDetail:
    primary, fallback = resolve_locale(locale)
    return await CatalogService(session).get_product(slug, primary, fallback)


@router.get(
    "/products/{slug}/related",
    response_model=list[ProductListItem],
    summary="Похожие товары",
)
async def get_related_products(
    slug: SlugPath,
    session: SessionDep,
    locale: LocaleQuery = None,
) -> list[ProductListItem]:
    """Соседи по категории. Никаких рекомендательных моделей."""
    primary, fallback = resolve_locale(locale)
    return await CatalogService(session).get_related_products(slug, primary, fallback)
