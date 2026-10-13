"""Тесты последней линии защиты уникальности — ограничений PostgreSQL.

Предварительный SELECT не переживает гонку: два запроса убеждаются, что
артикул свободен, и оба идут на вставку. Здесь проверяется, что второй
получает корректный 409, а не 500.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.integrity import (
    extract_constraint_name,
    guard_unique,
    translate_integrity_error,
)
from app.modules.catalog.exceptions import (
    ExternalIdExistsError,
    ProductSkuExistsError,
    ProductSlugExistsError,
)
from app.modules.catalog.integrity import CATALOG_UNIQUE_ERRORS
from app.modules.catalog.models import Product
from app.modules.catalog.schemas_admin_products import ProductCreate
from app.modules.catalog.service_admin_products import AdminProductService
from tests.conftest import Headers

PRODUCTS = "/api/v1/admin/products"


def product_payload(sku: str, slug: str, name: str, **extra: object) -> dict:
    return {"sku": sku, "slug": slug, "translations": {"ru": {"name": name}}, **extra}


async def _provoke_duplicate_sku(session: AsyncSession) -> IntegrityError:
    session.add(Product(sku="RACE-DUP", slug="race-dup-1"))
    await session.flush()
    session.add(Product(sku="RACE-DUP", slug="race-dup-2"))
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        return exc
    pytest.fail("Ожидалось нарушение уникального индекса")


# ------------------------------------------------- распознавание конфликта
async def test_constraint_name_is_extracted(committed_session: AsyncSession) -> None:
    """Конфликт определяется по имени индекса, а не по тексту ошибки.

    Текст сообщения PostgreSQL зависит от версии и локали сервера,
    а имена зафиксированы в миграции.
    """
    error = await _provoke_duplicate_sku(committed_session)
    assert extract_constraint_name(error) == "uq_products_sku"


async def test_known_constraint_maps_to_domain_error(
    committed_session: AsyncSession,
) -> None:
    error = await _provoke_duplicate_sku(committed_session)
    translated = translate_integrity_error(error, CATALOG_UNIQUE_ERRORS)

    assert isinstance(translated, ProductSkuExistsError)
    assert translated.code == "sku_exists"


async def test_unknown_constraint_is_not_translated(
    committed_session: AsyncSession,
) -> None:
    """Незнакомое нарушение не выдаётся за бизнес-конфликт.

    Иначе ошибка в коде или в схеме молча превратилась бы в 409
    и осталась незамеченной.
    """
    error = await _provoke_duplicate_sku(committed_session)
    assert translate_integrity_error(error, {}) is None


async def test_guard_reraises_unknown_integrity_error(
    committed_session: AsyncSession,
) -> None:
    class Service:
        def __init__(self, session: AsyncSession) -> None:
            self.session = session

        @guard_unique({})  # пустая таблица соответствий
        async def mutate(self) -> None:
            self.session.add(Product(sku="GUARD-1", slug="guard-1"))
            await self.session.flush()
            self.session.add(Product(sku="GUARD-1", slug="guard-2"))
            await self.session.flush()

    with pytest.raises(IntegrityError):
        await Service(committed_session).mutate()

    # Сессия откачена и пригодна к работе: после IntegrityError
    # транзакция PostgreSQL находится в состоянии aborted, и без отката
    # любой следующий запрос упал бы.
    assert (await committed_session.execute(Product.__table__.select())).first() is None


# ----------------------------------------------------- реальная гонка
async def test_concurrent_create_gives_conflict_not_500(
    test_engine: AsyncEngine, make_user
) -> None:
    """Два одновременных создания товара с одним артикулом.

    Оба запроса проходят предварительную проверку (артикул свободен),
    оба доходят до вставки. Побеждает один, второй обязан получить
    доменный конфликт.
    """
    actor = await make_user()
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    payload = ProductCreate.model_validate(product_payload("RACE-1", "race-1", "Гонка"))

    async def attempt() -> str:
        async with session_factory() as session:
            try:
                await AdminProductService(session).create_product(payload, actor)
            except ProductSkuExistsError:
                return "conflict"
            return "created"

    results = sorted(await asyncio.gather(attempt(), attempt()))
    assert results == ["conflict", "created"]


# ------------------------------------------ HTTP: обход предпроверки
@pytest.fixture
def without_prechecks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отключает предварительные SELECT-проверки.

    Так воспроизводится состояние гонки: проверка «прошла», и запрос
    упирается прямо в ограничение базы. Без этого до ограничения дело
    не доходит и путь остался бы непокрытым.
    """

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    for method in (
        "_check_sku_unique",
        "_check_slug_unique",
        "_check_external_id_unique",
    ):
        monkeypatch.setattr(AdminProductService, method, _noop)


@pytest.mark.parametrize(
    ("first", "second", "expected_code"),
    [
        (
            {"sku": "HTTP-1", "slug": "http-1"},
            {"sku": "HTTP-1", "slug": "http-2"},
            "sku_exists",
        ),
        (
            {"sku": "HTTP-3", "slug": "http-3"},
            {"sku": "HTTP-4", "slug": "http-3"},
            "product_slug_exists",
        ),
        (
            {"sku": "HTTP-5", "slug": "http-5", "external_id": "1c-guid"},
            {"sku": "HTTP-6", "slug": "http-6", "external_id": "1c-guid"},
            "external_id_exists",
        ),
    ],
)
async def test_db_constraint_returns_conflict(
    api: AsyncClient,
    admin: Headers,
    without_prechecks: None,
    first: dict,
    second: dict,
    expected_code: str,
) -> None:
    created = await api.post(PRODUCTS, headers=admin, json=product_payload(name="Первый", **first))
    assert created.status_code == 201

    conflict = await api.post(
        PRODUCTS, headers=admin, json=product_payload(name="Второй", **second)
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == expected_code
    # Имя индекса наружу не отдаётся — это внутренняя деталь схемы
    assert "uq_" not in str(conflict.json())


async def test_db_constraint_on_update(
    api: AsyncClient, admin: Headers, without_prechecks: None
) -> None:
    """PATCH тоже упирается в ограничение, а не в 500."""
    await api.post(PRODUCTS, headers=admin, json=product_payload("UPD-A", "upd-a", "А"))
    second = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("UPD-B", "upd-b", "Б"))
    ).json()

    response = await api.patch(f"{PRODUCTS}/{second['id']}", headers=admin, json={"sku": "UPD-A"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "sku_exists"


async def test_db_constraint_on_restore(
    api: AsyncClient, admin: Headers, without_prechecks: None
) -> None:
    """Пока товар был удалён, его артикул мог занять другой товар."""
    original = (
        await api.post(PRODUCTS, headers=admin, json=product_payload("RST-1", "rst-1", "А"))
    ).json()
    await api.delete(f"{PRODUCTS}/{original['id']}", headers=admin)

    replacement = await api.post(
        PRODUCTS, headers=admin, json=product_payload("RST-1", "rst-2", "Б")
    )
    assert replacement.status_code == 201

    restored = await api.post(f"{PRODUCTS}/{original['id']}/restore", headers=admin)
    assert restored.status_code == 409
    assert restored.json()["error"]["code"] == "sku_exists"


async def test_session_is_usable_after_conflict(
    api: AsyncClient, admin: Headers, without_prechecks: None
) -> None:
    """После конфликта работа продолжается штатно.

    Проверяет, что сессия не осталась в aborted-транзакции: следующий
    запрос должен пройти обычным порядком.
    """
    await api.post(PRODUCTS, headers=admin, json=product_payload("SES-1", "ses-1", "А"))

    conflict = await api.post(PRODUCTS, headers=admin, json=product_payload("SES-1", "ses-2", "Б"))
    assert conflict.status_code == 409

    listing = await api.get(PRODUCTS, headers=admin)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    created = await api.post(PRODUCTS, headers=admin, json=product_payload("SES-3", "ses-3", "В"))
    assert created.status_code == 201


# ------------------------------------------------- категории и атрибуты
async def test_category_slug_conflict_from_db(
    api: AsyncClient, admin: Headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Та же защита стоит на категориях: гонка там ровно такая же."""
    from app.modules.catalog.repository_admin import AdminCategoryRepository

    categories = "/api/v1/admin/categories"
    payload = {"slug": "gonka", "translations": {"ru": {"name": "Гонка"}}}
    assert (await api.post(categories, headers=admin, json=payload)).status_code == 201

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(AdminCategoryRepository, "get_by_slug", _noop)

    conflict = await api.post(categories, headers=admin, json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "slug_exists"


async def test_attribute_code_conflict_from_db(
    api: AsyncClient, admin: Headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.catalog.repository_admin import AdminAttributeRepository

    attributes = "/api/v1/admin/attributes"
    payload = {"code": "gonka", "value_type": "STRING", "names": {"ru": "Гонка"}}
    assert (await api.post(attributes, headers=admin, json=payload)).status_code == 201

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(AdminAttributeRepository, "get_by_code", _noop)

    conflict = await api.post(attributes, headers=admin, json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "attribute_code_exists"


async def test_external_id_precheck_returns_conflict(api: AsyncClient, admin: Headers) -> None:
    """Обычный путь: предпроверка отдаёт 409 без ожидания базы."""
    await api.post(
        PRODUCTS,
        headers=admin,
        json=product_payload("EXT-1", "ext-1", "А", external_id="1c-001"),
    )
    conflict = await api.post(
        PRODUCTS,
        headers=admin,
        json=product_payload("EXT-2", "ext-2", "Б", external_id="1c-001"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "external_id_exists"


async def test_empty_external_id_is_not_unique(api: AsyncClient, admin: Headers) -> None:
    """Индекс частичный: пока интеграции с 1С нет, поле пусто у всех."""
    for index in range(3):
        response = await api.post(
            PRODUCTS,
            headers=admin,
            json=product_payload(f"NUL-{index}", f"nul-{index}", "Товар"),
        )
        assert response.status_code == 201


@pytest.mark.parametrize("value", [ProductSlugExistsError, ExternalIdExistsError])
def test_conflict_errors_use_unified_format(value: type) -> None:
    error = value()
    assert error.status_code == 409
    assert error.code
    assert error.message
