"""Дерево категорий с признаком удаления (G7) и категории характеристики (G8).

Поля добавлены к существующим ответам; прежние поля и правила проверяет
test_admin_catalog.py.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import Headers
from tests.helpers import count_queries

CATEGORIES = "/api/v1/admin/categories"
ATTRIBUTES = "/api/v1/admin/attributes"


async def _category(
    api: AsyncClient, headers: Headers, slug: str, name: str, **extra: object
) -> dict:
    response = await api.post(
        CATEGORIES,
        headers=headers,
        json={"slug": slug, "translations": {"ru": {"name": name}}, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _attribute(api: AsyncClient, headers: Headers, code: str, name: str) -> dict:
    response = await api.post(
        ATTRIBUTES,
        headers=headers,
        json={"code": code, "value_type": "STRING", "names": {"ru": name}},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _find(nodes: list[dict], node_id: int) -> dict | None:
    for node in nodes:
        if node["id"] == node_id:
            return node
        found = _find(node["children"], node_id)
        if found:
            return found
    return None


# ==================================================================== G7
async def test_tree_nodes_carry_parent_and_deleted_at(api: AsyncClient, admin: Headers) -> None:
    root = await _category(api, admin, "root", "Корень")
    child = await _category(api, admin, "child", "Дочерняя", parent_id=root["id"])
    gone = await _category(api, admin, "gone", "Удалённая", parent_id=root["id"])
    assert (await api.delete(f"{CATEGORIES}/{gone['id']}", headers=admin)).status_code == 204

    live = (await api.get(f"{CATEGORIES}/tree", headers=admin)).json()
    live_root = _find(live, root["id"])
    assert live_root is not None
    assert live_root["parent_id"] is None
    assert live_root["deleted_at"] is None
    assert [item["id"] for item in live_root["children"]] == [child["id"]]
    assert live_root["children"][0]["parent_id"] == root["id"]

    full = (
        await api.get(f"{CATEGORIES}/tree", headers=admin, params={"include_deleted": True})
    ).json()
    deleted = _find(full, gone["id"])
    assert deleted is not None
    assert deleted["deleted_at"] is not None
    assert deleted["parent_id"] == root["id"]
    assert deleted["is_active"] is False


async def test_restored_category_is_live_in_tree_again(api: AsyncClient, admin: Headers) -> None:
    node = await _category(api, admin, "temp", "Временная")
    await api.delete(f"{CATEGORIES}/{node['id']}", headers=admin)
    assert (await api.post(f"{CATEGORIES}/{node['id']}/restore", headers=admin)).status_code == 200

    tree = (
        await api.get(f"{CATEGORIES}/tree", headers=admin, params={"include_deleted": True})
    ).json()
    restored = _find(tree, node["id"])
    assert restored is not None
    assert restored["deleted_at"] is None


# ==================================================================== G8
async def test_attribute_lists_assigned_live_categories(api: AsyncClient, admin: Headers) -> None:
    ropes = await _category(api, admin, "kanaty", "Канаты")
    seats = await _category(api, admin, "sideniya", "Сиденья")
    old = await _category(api, admin, "staroe", "Старое")
    diameter = await _attribute(api, admin, "diameter", "Диаметр")
    unused = await _attribute(api, admin, "weight", "Вес")

    for category in (ropes, seats, old):
        response = await api.put(
            f"{CATEGORIES}/{category['id']}/attributes",
            headers=admin,
            json={"items": [{"attribute_id": diameter["id"]}]},
        )
        assert response.status_code == 200
    # Удалённая категория в списке «где используется» не показывается.
    assert (await api.delete(f"{CATEGORIES}/{old['id']}", headers=admin)).status_code == 204

    listing = (await api.get(ATTRIBUTES, headers=admin)).json()
    by_code = {item["code"]: item for item in listing["items"]}
    assert {item["name"] for item in by_code["diameter"]["categories"]} == {"Канаты", "Сиденья"}
    assert by_code["diameter"]["categories"][0].keys() == {"id", "slug", "name"}
    assert by_code["weight"]["categories"] == []

    single = (await api.get(f"{ATTRIBUTES}/{diameter['id']}", headers=admin)).json()
    assert {item["id"] for item in single["categories"]} == {ropes["id"], seats["id"]}
    assert (await api.get(f"{ATTRIBUTES}/{unused['id']}", headers=admin)).json()["categories"] == []


async def test_unassigning_removes_category_from_attribute(
    api: AsyncClient, admin: Headers
) -> None:
    category = await _category(api, admin, "razdel", "Раздел")
    attribute = await _attribute(api, admin, "color_note", "Цвет")
    url = f"{CATEGORIES}/{category['id']}/attributes"
    await api.put(url, headers=admin, json={"items": [{"attribute_id": attribute["id"]}]})
    await api.put(url, headers=admin, json={"items": []})

    body = (await api.get(f"{ATTRIBUTES}/{attribute['id']}", headers=admin)).json()
    assert body["categories"] == []


async def test_attribute_categories_do_not_add_queries_per_row(
    api: AsyncClient, admin: Headers, test_engine: AsyncEngine
) -> None:
    category = await _category(api, admin, "perf", "Перф")
    first = await _attribute(api, admin, "perf_first", "Первая")
    await api.put(
        f"{CATEGORIES}/{category['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": first["id"]}]},
    )
    with count_queries(test_engine) as small:
        await api.get(ATTRIBUTES, headers=admin)

    items = [{"attribute_id": first["id"]}]
    for index in range(8):
        attribute = await _attribute(api, admin, f"perf_{index}", f"Характеристика {index}")
        items.append({"attribute_id": attribute["id"]})
        extra = await _category(api, admin, f"perf-{index}", f"Раздел {index}")
        await api.put(
            f"{CATEGORIES}/{extra['id']}/attributes",
            headers=admin,
            json={"items": [{"attribute_id": attribute["id"]}]},
        )
    await api.put(f"{CATEGORIES}/{category['id']}/attributes", headers=admin, json={"items": items})

    with count_queries(test_engine) as large:
        body = (await api.get(ATTRIBUTES, headers=admin)).json()

    assert body["total"] == 9
    assert all(len(item["categories"]) >= 1 for item in body["items"])
    assert len(large) == len(small)
