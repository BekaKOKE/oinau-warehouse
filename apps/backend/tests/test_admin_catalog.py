"""Интеграционные тесты Admin API каталога.

Закрываются бизнес-правила (цикл в дереве, безопасность удаления,
уникальность) и права доступа.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.catalog.enums import AttributeValueType
from app.modules.catalog.models import Category
from app.modules.users.enums import UserRole
from tests.catalog_fixtures import CatalogFixture
from tests.conftest import Headers
from tests.helpers import count_queries
from tests.media_helpers import make_media

CATEGORIES = "/api/v1/admin/categories"
ATTRIBUTES = "/api/v1/admin/attributes"
LOGIN = "/api/v1/admin/auth/login"


def category_payload(slug: str, name: str, **extra: object) -> dict:
    return {"slug": slug, "translations": {"ru": {"name": name}}, **extra}


def attribute_payload(code: str, name: str, **extra: object) -> dict:
    return {
        "code": code,
        "value_type": AttributeValueType.STRING.value,
        "names": {"ru": name},
        **extra,
    }


# =========================================================== категории
async def test_create_root_and_child(api: AsyncClient, admin: Headers) -> None:
    root = await api.post(CATEGORIES, headers=admin, json=category_payload("osnova", "Основа"))
    assert root.status_code == 201
    root_body = root.json()
    assert root_body["depth"] == 0
    assert root_body["path"] == str(root_body["id"])

    child = await api.post(
        CATEGORIES,
        headers=admin,
        json=category_payload("kanaty", "Канаты", parent_id=root_body["id"]),
    )
    assert child.status_code == 201
    child_body = child.json()
    assert child_body["depth"] == 1
    assert child_body["path"] == f"{root_body['id']}.{child_body['id']}"
    assert child_body["name"] == "Канаты"


async def test_category_image_is_set_replaced_and_cleared(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    """Обложка задаётся файлом медиатеки, меняется и снимается через null."""
    first = await make_media(committed_session)
    second = await make_media(committed_session)
    await committed_session.commit()

    created = await api.post(
        CATEGORIES,
        headers=admin,
        json=category_payload("kanaty", "Канаты", image=str(first.uuid)),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["image"]["uuid"] == str(first.uuid)
    assert body["image"]["url"].endswith(".webp")
    category_id = body["id"]

    replaced = await api.patch(
        f"{CATEGORIES}/{category_id}", headers=admin, json={"image": str(second.uuid)}
    )
    assert replaced.status_code == 200
    assert replaced.json()["image"]["uuid"] == str(second.uuid)

    # Поле не передано — обложка не трогается.
    untouched = await api.patch(
        f"{CATEGORIES}/{category_id}", headers=admin, json={"sort_order": 5}
    )
    assert untouched.json()["image"]["uuid"] == str(second.uuid)

    cleared = await api.patch(f"{CATEGORIES}/{category_id}", headers=admin, json={"image": None})
    assert cleared.status_code == 200
    assert cleared.json()["image"] is None


async def test_unknown_category_image_is_rejected(api: AsyncClient, admin: Headers) -> None:
    response = await api.post(
        CATEGORIES,
        headers=admin,
        json=category_payload("kanaty", "Канаты", image=str(uuid.uuid4())),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "media_not_found"


async def test_media_used_as_category_image_cannot_be_deleted(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    """Файл, который показывается на витрине, из медиатеки не удаляется."""
    media = await make_media(committed_session)
    await committed_session.commit()

    created = await api.post(
        CATEGORIES,
        headers=admin,
        json=category_payload("kanaty", "Канаты", image=str(media.uuid)),
    )
    assert created.status_code == 201

    response = await api.delete(f"/api/v1/admin/media/{media.uuid}", headers=admin)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "media_in_use"
    assert error["details"]["categories"] == ["kanaty"]


async def test_slug_must_be_unique(api: AsyncClient, admin: Headers) -> None:
    await api.post(CATEGORIES, headers=admin, json=category_payload("dubl", "Первая"))
    duplicate = await api.post(CATEGORIES, headers=admin, json=category_payload("dubl", "Вторая"))
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "slug_exists"


async def test_unknown_parent_returns_404(api: AsyncClient, admin: Headers) -> None:
    response = await api.post(
        CATEGORIES, headers=admin, json=category_payload("sirota", "Сирота", parent_id=999_999)
    )
    assert response.status_code == 404


async def test_default_locale_translation_is_required(api: AsyncClient, admin: Headers) -> None:
    response = await api.post(
        CATEGORIES,
        headers=admin,
        json={"slug": "bez-ru", "translations": {"kk": {"name": "Арқан"}}},
    )
    assert response.status_code == 422


async def test_invalid_locale_code_is_rejected(api: AsyncClient, admin: Headers) -> None:
    response = await api.post(
        CATEGORIES,
        headers=admin,
        json={"slug": "krivaya", "translations": {"russian": {"name": "Название"}}},
    )
    assert response.status_code == 422


async def test_update_category_and_translations(api: AsyncClient, admin: Headers) -> None:
    created = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("staryj", "Старое"))
    ).json()

    response = await api.patch(
        f"{CATEGORIES}/{created['id']}",
        headers=admin,
        json={
            "slug": "novyj",
            "sort_order": 5,
            "translations": {"ru": {"name": "Новое", "description": "Описание"}},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "novyj"
    assert body["sort_order"] == 5
    assert body["name"] == "Новое"
    assert body["translations"]["ru"]["description"] == "Описание"


async def test_second_locale_can_be_added(api: AsyncClient, admin: Headers) -> None:
    """Структура готова к kk: добавление второй локали не меняет схему."""
    created = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("dvuyazychnaya", "Раздел"))
    ).json()

    response = await api.patch(
        f"{CATEGORIES}/{created['id']}",
        headers=admin,
        json={"translations": {"kk": {"name": "Бөлім"}}},
    )
    assert response.status_code == 200
    assert set(response.json()["translations"]) == {"ru", "kk"}
    # Отображаемое имя по-прежнему берётся из локали по умолчанию
    assert response.json()["name"] == "Раздел"


async def test_category_cannot_be_its_own_parent(api: AsyncClient, admin: Headers) -> None:
    created = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("sama-sebe", "Сама"))
    ).json()

    response = await api.patch(
        f"{CATEGORIES}/{created['id']}", headers=admin, json={"parent_id": created["id"]}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_cycle"


async def test_cycle_through_descendant_is_rejected(api: AsyncClient, admin: Headers) -> None:
    """Родителя нельзя перенести под собственного потомка."""
    root = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("koren", "Корень"))
    ).json()
    child = (
        await api.post(
            CATEGORIES, headers=admin, json=category_payload("vetka", "Ветка", parent_id=root["id"])
        )
    ).json()

    response = await api.patch(
        f"{CATEGORIES}/{root['id']}", headers=admin, json={"parent_id": child["id"]}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_cycle"


async def test_moving_branch_recalculates_paths(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    """Смена родителя переписывает путь и глубину у всех потомков."""
    first = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("pervyj", "Первый"))
    ).json()
    second = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("vtoroj", "Второй"))
    ).json()
    middle = (
        await api.post(
            CATEGORIES,
            headers=admin,
            json=category_payload("sredniy", "Средний", parent_id=first["id"]),
        )
    ).json()
    leaf = (
        await api.post(
            CATEGORIES,
            headers=admin,
            json=category_payload("list", "Лист", parent_id=middle["id"]),
        )
    ).json()

    response = await api.patch(
        f"{CATEGORIES}/{middle['id']}", headers=admin, json={"parent_id": second["id"]}
    )
    assert response.status_code == 200
    assert response.json()["path"] == f"{second['id']}.{middle['id']}"
    assert response.json()["depth"] == 1

    moved_leaf = (await api.get(f"{CATEGORIES}/{leaf['id']}", headers=admin)).json()
    assert moved_leaf["path"] == f"{second['id']}.{middle['id']}.{leaf['id']}"
    assert moved_leaf["depth"] == 2

    stored = (
        await committed_session.execute(select(Category).where(Category.id == leaf["id"]))
    ).scalar_one()
    await committed_session.refresh(stored)
    assert stored.depth == 2


async def test_delete_requires_no_children(api: AsyncClient, admin: Headers) -> None:
    root = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("roditel", "Родитель"))
    ).json()
    await api.post(
        CATEGORIES, headers=admin, json=category_payload("potomok", "Потомок", parent_id=root["id"])
    )

    response = await api.delete(f"{CATEGORIES}/{root['id']}", headers=admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_has_children"


async def test_delete_requires_no_products(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    """Каскад product_categories → categories физически оборвал бы связи,
    поэтому категория с товарами не удаляется вовсе."""
    category_id = catalog.categories["ropes"].id
    response = await api.delete(f"{CATEGORIES}/{category_id}", headers=admin)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_has_products"
    assert response.json()["error"]["details"]["products_count"] >= 1


async def test_soft_delete_and_restore(api: AsyncClient, admin: Headers) -> None:
    created = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("vremennaya", "Временная"))
    ).json()

    assert (await api.delete(f"{CATEGORIES}/{created['id']}", headers=admin)).status_code == 204

    # Из обычного списка пропала
    listing = (await api.get(CATEGORIES, headers=admin)).json()
    assert created["id"] not in {item["id"] for item in listing["items"]}

    # Но доступна явно
    with_deleted = (
        await api.get(CATEGORIES, headers=admin, params={"include_deleted": True})
    ).json()
    assert created["id"] in {item["id"] for item in with_deleted["items"]}

    detail = (await api.get(f"{CATEGORIES}/{created['id']}", headers=admin)).json()
    assert detail["deleted_at"] is not None
    assert detail["is_active"] is False

    restored = await api.post(f"{CATEGORIES}/{created['id']}/restore", headers=admin)
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None


async def test_restore_of_living_category_is_rejected(api: AsyncClient, admin: Headers) -> None:
    created = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("zhivaya", "Живая"))
    ).json()
    response = await api.post(f"{CATEGORIES}/{created['id']}/restore", headers=admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "category_not_deleted"


async def test_deleted_category_disappears_from_public_api(
    api: AsyncClient, admin: Headers
) -> None:
    created = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("publichnaya", "Публичная"))
    ).json()
    assert (await api.get("/api/v1/public/categories/publichnaya")).status_code == 200

    await api.delete(f"{CATEGORIES}/{created['id']}", headers=admin)
    assert (await api.get("/api/v1/public/categories/publichnaya")).status_code == 404


async def test_category_tree_is_nested(api: AsyncClient, admin: Headers) -> None:
    root = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("derevo", "Дерево"))
    ).json()
    await api.post(
        CATEGORIES, headers=admin, json=category_payload("vetv", "Ветвь", parent_id=root["id"])
    )

    tree = (await api.get(f"{CATEGORIES}/tree", headers=admin)).json()
    node = next(item for item in tree if item["id"] == root["id"])
    assert [child["slug"] for child in node["children"]] == ["vetv"]


# ======================================================== характеристики
async def test_create_attribute_with_options(api: AsyncClient, admin: Headers) -> None:
    response = await api.post(
        ATTRIBUTES,
        headers=admin,
        json={
            "code": "material",
            "value_type": "OPTION",
            "names": {"ru": "Материал"},
            "options": [
                {"slug": "pp", "values": {"ru": "Полипропилен"}, "sort_order": 1},
                {"slug": "hdpe", "values": {"ru": "HDPE"}, "sort_order": 2},
            ],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Материал"
    assert [option["slug"] for option in body["options"]] == ["pp", "hdpe"]
    assert body["usage_count"] == 0


async def test_attribute_code_must_be_unique(api: AsyncClient, admin: Headers) -> None:
    await api.post(ATTRIBUTES, headers=admin, json=attribute_payload("dlina", "Длина"))
    duplicate = await api.post(
        ATTRIBUTES, headers=admin, json=attribute_payload("dlina", "Длина 2")
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "attribute_code_exists"


async def test_options_only_for_option_type(api: AsyncClient, admin: Headers) -> None:
    response = await api.post(
        ATTRIBUTES,
        headers=admin,
        json={
            "code": "ves",
            "value_type": "NUMBER",
            "names": {"ru": "Вес"},
            "options": [{"slug": "x", "values": {"ru": "X"}}],
        },
    )
    assert response.status_code == 422


async def test_option_cannot_be_added_to_non_option_attribute(
    api: AsyncClient, admin: Headers
) -> None:
    created = (
        await api.post(
            ATTRIBUTES,
            headers=admin,
            json={"code": "diametr", "value_type": "NUMBER", "names": {"ru": "Диаметр"}},
        )
    ).json()

    response = await api.post(
        f"{ATTRIBUTES}/{created['id']}/options",
        headers=admin,
        json={"slug": "x", "values": {"ru": "X"}},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "attribute_type_mismatch"


async def test_update_attribute_merges_names(api: AsyncClient, admin: Headers) -> None:
    created = (
        await api.post(ATTRIBUTES, headers=admin, json=attribute_payload("cvet", "Цвет"))
    ).json()

    response = await api.patch(
        f"{ATTRIBUTES}/{created['id']}",
        headers=admin,
        json={"names": {"kk": "Түс"}, "is_filterable": False, "unit": "шт"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["names"] == {"ru": "Цвет", "kk": "Түс"}
    assert body["is_filterable"] is False


async def test_value_type_cannot_be_changed(api: AsyncClient, admin: Headers) -> None:
    """Смена типа осиротила бы уже заполненные значения товаров."""
    created = (
        await api.post(ATTRIBUTES, headers=admin, json=attribute_payload("tip", "Тип"))
    ).json()

    response = await api.patch(
        f"{ATTRIBUTES}/{created['id']}", headers=admin, json={"value_type": "NUMBER"}
    )
    assert response.status_code == 200
    assert response.json()["value_type"] == "STRING"


async def test_option_crud(api: AsyncClient, admin: Headers) -> None:
    attribute = (
        await api.post(
            ATTRIBUTES,
            headers=admin,
            json={"code": "pokrytie", "value_type": "OPTION", "names": {"ru": "Покрытие"}},
        )
    ).json()

    created = await api.post(
        f"{ATTRIBUTES}/{attribute['id']}/options",
        headers=admin,
        json={"slug": "cink", "values": {"ru": "Оцинковка"}},
    )
    assert created.status_code == 201
    option_id = created.json()["id"]

    updated = await api.patch(
        f"{ATTRIBUTES}/{attribute['id']}/options/{option_id}",
        headers=admin,
        json={"sort_order": 3, "values": {"ru": "Горячее цинкование"}},
    )
    assert updated.status_code == 200
    assert updated.json()["values"]["ru"] == "Горячее цинкование"

    duplicate = await api.post(
        f"{ATTRIBUTES}/{attribute['id']}/options",
        headers=admin,
        json={"slug": "cink", "values": {"ru": "Дубль"}},
    )
    assert duplicate.status_code == 409

    deleted = await api.delete(f"{ATTRIBUTES}/{attribute['id']}/options/{option_id}", headers=admin)
    assert deleted.status_code == 204


async def test_attribute_in_use_cannot_be_deleted(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    """Внешний ключ объявлен с RESTRICT — вместо 500 отдаём понятную ошибку."""
    listing = (await api.get(ATTRIBUTES, headers=admin, params={"search": "diameter"})).json()
    attribute = listing["items"][0]
    assert attribute["usage_count"] >= 1

    response = await api.delete(f"{ATTRIBUTES}/{attribute['id']}", headers=admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "attribute_in_use"


async def test_used_option_cannot_be_deleted(
    api: AsyncClient, admin: Headers, catalog: CatalogFixture
) -> None:
    listing = (await api.get(ATTRIBUTES, headers=admin, params={"search": "material"})).json()
    attribute = listing["items"][0]
    option_id = attribute["options"][0]["id"]

    response = await api.delete(
        f"{ATTRIBUTES}/{attribute['id']}/options/{option_id}", headers=admin
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "attribute_option_in_use"


async def test_unused_attribute_can_be_deleted(api: AsyncClient, admin: Headers) -> None:
    created = (
        await api.post(ATTRIBUTES, headers=admin, json=attribute_payload("lishnyaya", "Лишняя"))
    ).json()
    assert (await api.delete(f"{ATTRIBUTES}/{created['id']}", headers=admin)).status_code == 204
    assert (await api.get(f"{ATTRIBUTES}/{created['id']}", headers=admin)).status_code == 404


# ================================================ категория ↔ атрибуты
async def test_assign_and_replace_category_attributes(api: AsyncClient, admin: Headers) -> None:
    category = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("filtry", "Фильтры"))
    ).json()
    first = (
        await api.post(ATTRIBUTES, headers=admin, json=attribute_payload("a1", "Первая"))
    ).json()
    second = (
        await api.post(ATTRIBUTES, headers=admin, json=attribute_payload("a2", "Вторая"))
    ).json()

    assigned = await api.put(
        f"{CATEGORIES}/{category['id']}/attributes",
        headers=admin,
        json={
            "items": [
                {"attribute_id": first["id"], "sort_order": 1, "is_required": True},
                {"attribute_id": second["id"], "sort_order": 2},
            ]
        },
    )
    assert assigned.status_code == 200
    body = assigned.json()
    assert [item["code"] for item in body] == ["a1", "a2"]
    assert body[0]["is_required"] is True

    # Полная замена набора: остаётся только второй
    replaced = await api.put(
        f"{CATEGORIES}/{category['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": second["id"], "sort_order": 1}]},
    )
    assert [item["code"] for item in replaced.json()] == ["a2"]

    current = await api.get(f"{CATEGORIES}/{category['id']}/attributes", headers=admin)
    assert [item["code"] for item in current.json()] == ["a2"]


async def test_duplicate_attribute_in_payload_is_rejected(api: AsyncClient, admin: Headers) -> None:
    category = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("dubli", "Дубли"))
    ).json()
    attribute = (
        await api.post(ATTRIBUTES, headers=admin, json=attribute_payload("a3", "Третья"))
    ).json()

    response = await api.put(
        f"{CATEGORIES}/{category['id']}/attributes",
        headers=admin,
        json={
            "items": [
                {"attribute_id": attribute["id"]},
                {"attribute_id": attribute["id"], "sort_order": 2},
            ]
        },
    )
    assert response.status_code == 422


async def test_assign_unknown_attribute_returns_404(api: AsyncClient, admin: Headers) -> None:
    category = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("pustaya", "Пустая"))
    ).json()
    response = await api.put(
        f"{CATEGORIES}/{category['id']}/attributes",
        headers=admin,
        json={"items": [{"attribute_id": 999_999}]},
    )
    assert response.status_code == 404


async def test_attributes_of_unknown_category_returns_404(api: AsyncClient, admin: Headers) -> None:
    assert (await api.get(f"{CATEGORIES}/999999/attributes", headers=admin)).status_code == 404


# =============================================================== доступ
@pytest.mark.parametrize(
    ("role", "read_status", "write_status"),
    [
        (UserRole.SUPERADMIN, 200, 201),
        (UserRole.ADMIN, 200, 201),
        (UserRole.CONTENT_MANAGER, 200, 201),
        (UserRole.MANAGER, 200, 403),
        (UserRole.VIEWER, 200, 403),
    ],
)
async def test_catalog_permissions(
    api: AsyncClient,
    login_as,
    role: UserRole,
    read_status: int,
    write_status: int,
) -> None:
    headers = await login_as(role)

    assert (await api.get(CATEGORIES, headers=headers)).status_code == read_status
    created = await api.post(
        CATEGORIES,
        headers=headers,
        json=category_payload(f"rbac-{role.value.lower().replace('_', '-')}", "RBAC"),
    )
    assert created.status_code == write_status


async def test_anonymous_access_is_rejected(api: AsyncClient) -> None:
    assert (await api.get(CATEGORIES)).status_code == 401
    assert (await api.get(ATTRIBUTES)).status_code == 401
    assert (await api.post(CATEGORIES, json=category_payload("anon", "Аноним"))).status_code == 401


# ================================================================ аудит
async def test_mutations_are_audited(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    created = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("auditnaya", "Аудит"))
    ).json()
    await api.patch(f"{CATEGORIES}/{created['id']}", headers=admin, json={"sort_order": 9})
    await api.delete(f"{CATEGORIES}/{created['id']}", headers=admin)

    entries = (
        (
            await committed_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "category", AuditLog.entity_id == created["id"]
                )
            )
        )
        .scalars()
        .all()
    )
    actions = {entry.action for entry in entries}

    assert "catalog.category_created" in actions
    assert "catalog.category_updated" in actions
    assert "catalog.category_deleted" in actions
    assert all(entry.user_id is not None for entry in entries)


async def test_read_requests_are_not_audited(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    """Журналируются изменения, а не просмотры — иначе таблица удвоится
    без пользы."""
    await api.get(CATEGORIES, headers=admin)
    entries = (
        (
            await committed_session.execute(
                select(AuditLog).where(AuditLog.entity_type == "category")
            )
        )
        .scalars()
        .all()
    )
    assert entries == []


# ====================================================== производительность
async def test_category_tree_has_no_n_plus_one(
    api: AsyncClient, admin: Headers, test_engine: AsyncEngine
) -> None:
    """Число запросов не растёт вместе с деревом."""
    root = (
        await api.post(CATEGORIES, headers=admin, json=category_payload("perf-root", "Корень"))
    ).json()

    with count_queries(test_engine) as small:
        assert (await api.get(f"{CATEGORIES}/tree", headers=admin)).status_code == 200
    baseline = len(small)

    for index in range(10):
        await api.post(
            CATEGORIES,
            headers=admin,
            json=category_payload(f"perf-{index}", f"Раздел {index}", parent_id=root["id"]),
        )

    with count_queries(test_engine) as large:
        tree = (await api.get(f"{CATEGORIES}/tree", headers=admin)).json()

    node = next(item for item in tree if item["id"] == root["id"])
    assert len(node["children"]) == 10
    assert len(large) == baseline


async def test_attribute_list_has_no_n_plus_one(
    api: AsyncClient, admin: Headers, test_engine: AsyncEngine
) -> None:
    await api.post(ATTRIBUTES, headers=admin, json=attribute_payload("perf_a", "А"))

    with count_queries(test_engine) as small:
        assert (await api.get(ATTRIBUTES, headers=admin)).status_code == 200
    baseline = len(small)

    for index in range(8):
        await api.post(
            ATTRIBUTES,
            headers=admin,
            json={
                "code": f"perf_{index}",
                "value_type": "OPTION",
                "names": {"ru": f"Характеристика {index}"},
                "options": [{"slug": "a", "values": {"ru": "А"}}],
            },
        )

    with count_queries(test_engine) as large:
        body = (await api.get(ATTRIBUTES, headers=admin)).json()

    assert body["total"] == 9
    assert len(large) == baseline
