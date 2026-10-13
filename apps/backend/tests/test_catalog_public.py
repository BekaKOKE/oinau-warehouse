"""Интеграционные тесты публичного каталога.

Проверяется контракт наружу: что видно, что не видно, в каком виде.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.catalog.models import Category
from app.modules.media.enums import MediaStatus
from tests.catalog_fixtures import CatalogFixture
from tests.helpers import count_queries
from tests.media_helpers import make_media

CATEGORIES_URL = "/api/v1/public/categories"
PRODUCTS_URL = "/api/v1/public/products"

# Поля, которых в публичном ответе быть не должно ни при каких условиях
FORBIDDEN_FIELDS = {
    "id",
    "status",
    "storage_key",
    "deleted_at",
    "external_id",
    "sync_source",
    "synced_at",
    "created_at",
    "updated_at",
    "quantity",
    "reserved",
    "price_list_id",
    "product_id",
    "stock_display_override",
    "password_hash",
}


def collect_keys(payload: object) -> set[str]:
    """Все ключи вложенной структуры — для проверки утечки полей."""
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            keys.add(key)
            keys |= collect_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            keys |= collect_keys(item)
    return keys


# ------------------------------------------------------------------ категории
async def test_category_tree_is_nested(api: AsyncClient, catalog: CatalogFixture) -> None:
    response = await api.get(CATEGORIES_URL)
    assert response.status_code == 200

    tree = response.json()
    assert len(tree) == 1
    root = tree[0]
    assert root["slug"] == "komplektuyushchie"
    assert root["name"] == "Комплектующие"
    assert {child["slug"] for child in root["children"]} == {"kanaty", "krepleniya"}


async def test_category_image_is_served_from_media_library(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    """Обложка раздела — ссылка на вариант файла медиатеки, не на оригинал."""
    media = await make_media(committed_session)
    category = await committed_session.get(Category, catalog.categories["ropes"].id)
    assert category is not None
    category.image_media_id = media.id
    await committed_session.commit()

    node = find_node((await api.get(CATEGORIES_URL)).json(), "kanaty")
    assert node is not None
    image = node["image"]
    assert image["url"].endswith("thumb.webp") or image["url"].endswith("large.webp")
    assert image["width"] == 64 and image["height"] == 48
    assert set(image["variants"]) == {"large", "thumb"}
    # Приватный оригинал наружу не уходит ни в какой форме.
    assert "original.png" not in response_text(node)

    detail = (await api.get(f"{CATEGORIES_URL}/kanaty")).json()
    assert detail["image"]["url"] == image["url"]


async def test_category_without_image_returns_null(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    """Своей обложки может не быть — витрина подставит фото товара."""
    node = find_node((await api.get(CATEGORIES_URL)).json(), "krepleniya")
    assert node is not None
    assert node["image"] is None


async def test_unprocessed_category_image_is_not_linked(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    """Файл в обработке ссылки не получает: она вела бы в 404."""
    media = await make_media(committed_session, status=MediaStatus.PROCESSING)
    category = await committed_session.get(Category, catalog.categories["ropes"].id)
    assert category is not None
    category.image_media_id = media.id
    await committed_session.commit()

    node = find_node((await api.get(CATEGORIES_URL)).json(), "kanaty")
    assert node is not None
    assert node["image"] is None


def response_text(node: dict) -> str:
    return json.dumps(node, ensure_ascii=False)


def find_node(nodes: list[dict], slug: str) -> dict | None:
    for node in nodes:
        if node["slug"] == slug:
            return node
        found = find_node(node["children"], slug)
        if found is not None:
            return found
    return None


async def test_inactive_category_is_hidden(api: AsyncClient, catalog: CatalogFixture) -> None:
    slugs = collect_slugs((await api.get(CATEGORIES_URL)).json())
    assert "skrytaya" not in slugs
    assert (await api.get(f"{CATEGORIES_URL}/skrytaya")).status_code == 404


def collect_slugs(nodes: list[dict]) -> set[str]:
    slugs: set[str] = set()
    for node in nodes:
        slugs.add(node["slug"])
        slugs |= collect_slugs(node["children"])
    return slugs


async def test_category_detail_has_breadcrumbs(api: AsyncClient, catalog: CatalogFixture) -> None:
    response = await api.get(f"{CATEGORIES_URL}/kanaty")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Канаты"
    assert [crumb["slug"] for crumb in body["breadcrumbs"]] == ["komplektuyushchie"]


async def test_category_tree_counts_products_of_whole_branch(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    """Счётчик раздела равен числу позиций на его странице.

    У корня — все видимые товары, включая товары подкатегорий: именно
    столько покажет страница «Комплектующие».
    """
    tree = (await api.get(CATEGORIES_URL)).json()
    root = tree[0]
    counts = {child["slug"]: child["product_count"] for child in root["children"]}

    assert root["product_count"] == 3
    assert counts == {"kanaty": 1, "krepleniya": 2}

    listed = (await api.get(PRODUCTS_URL, params={"category": "komplektuyushchie"})).json()
    assert listed["total"] == root["product_count"]


async def test_category_count_ignores_hidden_products(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    """Черновики, удалённые и отключённые товары в счётчик не попадают.

    В «Канатах» их три штуки против одного видимого каната.
    """
    tree = (await api.get(CATEGORIES_URL)).json()
    ropes = next(child for child in tree[0]["children"] if child["slug"] == "kanaty")
    assert ropes["product_count"] == 1


async def test_category_detail_has_product_count(api: AsyncClient, catalog: CatalogFixture) -> None:
    body = (await api.get(f"{CATEGORIES_URL}/krepleniya")).json()
    assert body["product_count"] == 2


async def test_unknown_category_returns_404(api: AsyncClient, catalog: CatalogFixture) -> None:
    response = await api.get(f"{CATEGORIES_URL}/net-takoy")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# -------------------------------------------------------------- видимость
async def test_only_published_products_are_listed(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    body = (await api.get(PRODUCTS_URL)).json()
    slugs = {item["slug"] for item in body["items"]}

    assert slugs == {"kanat-16-pp", "kreplenie-m10", "sidenie-kachelej"}
    assert "chernovik" not in slugs  # DRAFT
    assert "udalennyj" not in slugs  # deleted_at
    assert "otklyuchennyj" not in slugs  # is_active=false
    assert body["total"] == 3


@pytest.mark.parametrize("slug", ["chernovik", "udalennyj", "otklyuchennyj"])
async def test_hidden_products_are_not_reachable_by_slug(
    api: AsyncClient, catalog: CatalogFixture, slug: str
) -> None:
    """Прямая ссылка на черновик или удалённый товар обязана давать 404."""
    assert (await api.get(f"{PRODUCTS_URL}/{slug}")).status_code == 404


async def test_unknown_slug_returns_404(api: AsyncClient, catalog: CatalogFixture) -> None:
    response = await api.get(f"{PRODUCTS_URL}/net-takogo-tovara")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# ------------------------------------------------------------- пагинация
async def test_pagination(api: AsyncClient, catalog: CatalogFixture) -> None:
    first = (await api.get(PRODUCTS_URL, params={"page_size": 2, "sort": "name"})).json()
    second = (
        await api.get(PRODUCTS_URL, params={"page_size": 2, "page": 2, "sort": "name"})
    ).json()

    assert first["total"] == 3
    assert first["pages"] == 2
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    # Страницы не пересекаются
    assert not {item["slug"] for item in first["items"]} & {
        item["slug"] for item in second["items"]
    }


async def test_page_size_is_capped(api: AsyncClient, catalog: CatalogFixture) -> None:
    """Выгрузить весь каталог одним запросом нельзя."""
    assert (await api.get(PRODUCTS_URL, params={"page_size": 10_000})).status_code == 422


# --------------------------------------------------------------- фильтры
async def test_category_filter_includes_subcategories(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    """Верхняя категория показывает товары всех вложенных разделов."""
    root = (await api.get(PRODUCTS_URL, params={"category": "komplektuyushchie"})).json()
    ropes = (await api.get(PRODUCTS_URL, params={"category": "kanaty"})).json()

    assert root["total"] == 3
    assert {item["slug"] for item in ropes["items"]} == {"kanat-16-pp"}


async def test_unknown_category_filter_returns_empty_page(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    body = (await api.get(PRODUCTS_URL, params={"category": "net-takoy"})).json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_availability_filter(api: AsyncClient, catalog: CatalogFixture) -> None:
    in_stock = (await api.get(PRODUCTS_URL, params={"availability": "IN_STOCK"})).json()
    out_of_stock = (await api.get(PRODUCTS_URL, params={"availability": "OUT_OF_STOCK"})).json()
    on_request = (await api.get(PRODUCTS_URL, params={"availability": "ON_REQUEST"})).json()

    assert {item["slug"] for item in in_stock["items"]} == {"kanat-16-pp"}
    assert {item["slug"] for item in out_of_stock["items"]} == {"kreplenie-m10"}
    assert {item["slug"] for item in on_request["items"]} == {"sidenie-kachelej"}


async def test_price_range_filter(api: AsyncClient, catalog: CatalogFixture) -> None:
    body = (await api.get(PRODUCTS_URL, params={"max_price": "1500"})).json()
    assert {item["slug"] for item in body["items"]} == {"kreplenie-m10"}


# ----------------------------------------------------------------- поиск
async def test_search_uses_morphology(api: AsyncClient, catalog: CatalogFixture) -> None:
    """«канаты» находит «Канат» — работает полнотекстовый индекс, не LIKE."""
    body = (await api.get(PRODUCTS_URL, params={"search": "канаты"})).json()
    assert {item["slug"] for item in body["items"]} == {"kanat-16-pp"}


async def test_search_by_sku_fragment(api: AsyncClient, catalog: CatalogFixture) -> None:
    body = (await api.get(PRODUCTS_URL, params={"search": "KRP-M"})).json()
    assert {item["slug"] for item in body["items"]} == {"kreplenie-m10"}


async def test_search_does_not_leak_hidden_products(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    body = (await api.get(PRODUCTS_URL, params={"search": "товар"})).json()
    assert body["items"] == []


async def test_search_length_is_limited(api: AsyncClient, catalog: CatalogFixture) -> None:
    response = await api.get(PRODUCTS_URL, params={"search": "к" * 500})
    assert response.status_code == 422


async def test_search_with_special_characters_is_safe(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    """Попытка инъекции через поиск — обычная строка, а не SQL."""
    response = await api.get(PRODUCTS_URL, params={"search": "'; DROP TABLE products; --"})
    assert response.status_code == 200
    assert (await api.get(PRODUCTS_URL)).json()["total"] == 3


# ------------------------------------------------------------- сортировка
async def test_sort_whitelist_rejects_arbitrary_value(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    response = await api.get(PRODUCTS_URL, params={"sort": "price; DROP TABLE products"})
    assert response.status_code == 422


async def test_sort_price_asc_puts_products_without_price_last(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    body = (await api.get(PRODUCTS_URL, params={"sort": "price_asc"})).json()
    slugs = [item["slug"] for item in body["items"]]

    assert slugs[0] == "kreplenie-m10"  # 1200
    assert slugs[1] == "kanat-16-pp"  # от 2600
    assert slugs[-1] == "sidenie-kachelej"  # цена по запросу — в конце


async def test_sort_by_name(api: AsyncClient, catalog: CatalogFixture) -> None:
    body = (await api.get(PRODUCTS_URL, params={"sort": "name"})).json()
    names = [item["name"] for item in body["items"]]
    assert names == sorted(names)


# ------------------------------------------------------------------- цены
async def test_fixed_pricing(api: AsyncClient, catalog: CatalogFixture) -> None:
    price = (await api.get(f"{PRODUCTS_URL}/kreplenie-m10")).json()["price"]

    assert price["type"] == "FIXED"
    assert price["currency"] == "KZT"
    assert Decimal(price["price"]) == Decimal("1200.00")
    assert price["tiers"] == [{"min_quantity": "1.000", "max_quantity": None, "price": "1200.00"}]


async def test_tiered_pricing(api: AsyncClient, catalog: CatalogFixture) -> None:
    price = (await api.get(f"{PRODUCTS_URL}/kanat-16-pp")).json()["price"]

    assert price["type"] == "TIERED"
    assert price["price"] is None
    assert Decimal(price["from_price"]) == Decimal("2600.00")
    assert len(price["tiers"]) == 4

    first, last = price["tiers"][0], price["tiers"][-1]
    assert Decimal(first["min_quantity"]) == 1
    assert Decimal(first["max_quantity"]) == 9
    # Верхняя ступень — открытый диапазон «100 и больше»
    assert Decimal(last["min_quantity"]) == 100
    assert last["max_quantity"] is None


async def test_on_request_pricing(api: AsyncClient, catalog: CatalogFixture) -> None:
    body = (await api.get(f"{PRODUCTS_URL}/sidenie-kachelej")).json()

    assert body["price"]["type"] == "ON_REQUEST"
    assert body["price"]["price"] is None
    assert body["price"]["from_price"] is None
    assert body["price"]["tiers"] == []
    assert body["availability"] == "ON_REQUEST"


async def test_dealer_price_list_is_not_exposed(api: AsyncClient, catalog: CatalogFixture) -> None:
    """Скрытый прайс-лист не должен просачиваться ни в список, ни в карточку."""
    detail = (await api.get(f"{PRODUCTS_URL}/kanat-16-pp")).json()
    listing = (await api.get(PRODUCTS_URL)).json()

    assert "1111.00" not in str(detail)
    assert "1111.00" not in str(listing)
    assert all(Decimal(tier["price"]) >= Decimal("2600") for tier in detail["price"]["tiers"])


# -------------------------------------------------------------- наличие
async def test_exact_quantity_is_never_exposed(api: AsyncClient, catalog: CatalogFixture) -> None:
    """152.5 метра на складе — коммерческая информация."""
    detail = (await api.get(f"{PRODUCTS_URL}/kanat-16-pp")).json()
    listing = (await api.get(PRODUCTS_URL)).json()

    assert detail["availability"] == "IN_STOCK"
    assert "152.5" not in str(detail)
    assert "152.5" not in str(listing)
    assert "quantity" not in collect_keys(detail)


async def test_zero_stock_is_out_of_stock(api: AsyncClient, catalog: CatalogFixture) -> None:
    body = (await api.get(f"{PRODUCTS_URL}/kreplenie-m10")).json()
    assert body["availability"] == "OUT_OF_STOCK"


# --------------------------------------------------------- карточка товара
async def test_product_detail_contract(api: AsyncClient, catalog: CatalogFixture) -> None:
    body = (await api.get(f"{PRODUCTS_URL}/kanat-16-pp")).json()

    assert body["sku"] == "KAN-16-PP"
    assert body["slug"] == "kanat-16-pp"
    assert body["name"] == "Канат полипропиленовый 16 мм"
    assert body["short_description"]
    assert body["description"] == "Подробное описание каната."
    assert body["unit"] == "m"
    assert body["specs"] == {"Страна": "Казахстан"}
    assert [crumb["slug"] for crumb in body["breadcrumbs"]] == ["komplektuyushchie", "kanaty"]
    assert body["images"] == []  # медиатека пуста до этапа загрузки в R2
    # Публичным считается только PUBLISHED-товар, поэтому статус наружу
    # не нужен; ключ хранилища — тем более.
    assert "status" not in body


async def test_response_does_not_leak_internal_fields(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    detail_keys = collect_keys((await api.get(f"{PRODUCTS_URL}/kanat-16-pp")).json())
    listing_keys = collect_keys((await api.get(PRODUCTS_URL)).json())

    assert not FORBIDDEN_FIELDS & detail_keys
    assert not FORBIDDEN_FIELDS & listing_keys


# ---------------------------------------------------------- характеристики
async def test_characteristics_are_formatted(api: AsyncClient, catalog: CatalogFixture) -> None:
    body = (await api.get(f"{PRODUCTS_URL}/kanat-16-pp")).json()
    by_code = {item["code"]: item for item in body["characteristics"]}

    # Число склеено с единицей измерения, хвостовые нули убраны
    assert by_code["diameter"] == {"code": "diameter", "name": "Диаметр", "value": "16 мм"}
    assert by_code["material"]["value"] == "Полипропилен"
    assert by_code["certified"]["value"] == "Да"
    # Невидимая характеристика на витрину не попадает
    assert "internal_note" not in by_code


# --------------------------------------------------------------- локали
async def test_unsupported_locale_falls_back(api: AsyncClient, catalog: CatalogFixture) -> None:
    """Запрос на неподдерживаемом языке отдаёт русскую версию, а не 400."""
    body = (await api.get(f"{PRODUCTS_URL}/kanat-16-pp", params={"locale": "en"})).json()
    assert body["name"] == "Канат полипропиленовый 16 мм"

    kk = (await api.get(f"{PRODUCTS_URL}/kanat-16-pp", params={"locale": "kk"})).json()
    assert kk["name"] == "Канат полипропиленовый 16 мм"


# ------------------------------------------------------------- похожие
async def test_related_products(api: AsyncClient, catalog: CatalogFixture) -> None:
    related = (await api.get(f"{PRODUCTS_URL}/kreplenie-m10/related")).json()
    slugs = {item["slug"] for item in related}

    assert "sidenie-kachelej" in slugs  # сосед по категории
    assert "kreplenie-m10" not in slugs  # сам товар исключён
    assert "chernovik" not in slugs


# ---------------------------------------------------------- производительность
async def test_product_list_has_no_n_plus_one(
    api: AsyncClient, catalog: CatalogFixture, committed_session, test_engine: AsyncEngine
) -> None:
    """Число запросов не зависит от числа товаров на странице.

    Цена и остаток приходят агрегатами в основном запросе, изображения —
    одним selectinload. Если кто-то заменит их обращением на каждый
    товар, счётчик разъедется и тест упадёт.
    """
    from tests.catalog_fixtures import _add_product

    with count_queries(test_engine) as small:
        assert (await api.get(PRODUCTS_URL, params={"page_size": 60})).status_code == 200
    baseline = len(small)

    for index in range(12):
        await _add_product(
            session=committed_session,
            sku=f"BULK-{index}",
            slug=f"bulk-{index}",
            name=f"Товар для нагрузки {index}",
            categories=[catalog.categories["ropes"]],
        )
    await committed_session.commit()

    with count_queries(test_engine) as large:
        body = (await api.get(PRODUCTS_URL, params={"page_size": 60})).json()

    assert body["total"] == 15
    assert len(large) == baseline


# ------------------------------------------- валидация параметров пути
@pytest.mark.parametrize(
    "path",
    [
        f"{PRODUCTS_URL}/Kanat-16-PP",  # верхний регистр
        f"{PRODUCTS_URL}/kanat 16",  # пробел
        f"{PRODUCTS_URL}/kanat_16",  # подчёркивание вне разрешённого набора
        f"{PRODUCTS_URL}/{'a' * 201}",  # длиннее лимита
        f"{CATEGORIES_URL}/Канаты",  # кириллица
        f"{CATEGORIES_URL}/kanaty;drop",  # спецсимвол
    ],
)
async def test_invalid_slug_is_rejected(
    api: AsyncClient, catalog: CatalogFixture, path: str
) -> None:
    """Некорректный slug — 422 на валидации, а не обращение к БД."""
    response = await api.get(path)
    assert response.status_code == 422


async def test_invalid_slug_rejected_for_related(api: AsyncClient, catalog: CatalogFixture) -> None:
    response = await api.get(f"{PRODUCTS_URL}/Kanat 16/related")
    assert response.status_code == 422


async def test_blank_search_behaves_as_no_search(api: AsyncClient, catalog: CatalogFixture) -> None:
    """Строка из пробелов — это отсутствие поиска, а не поиск по пустоте."""
    without = (await api.get(PRODUCTS_URL)).json()
    blank = (await api.get(PRODUCTS_URL, params={"search": "   "})).json()
    empty = (await api.get(PRODUCTS_URL, params={"search": ""})).json()

    assert blank["total"] == without["total"] == 3
    assert empty["total"] == 3
    assert [item["slug"] for item in blank["items"]] == [item["slug"] for item in without["items"]]
