"""Интеграционные тесты галереи товара и её видимости на витрине."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import Product
from app.modules.media.enums import MediaStatus
from app.modules.media.models import MediaFile
from app.modules.users.enums import UserRole
from tests.conftest import Headers
from tests.factories import make_product
from tests.helpers import count_queries
from tests.media_helpers import (
    MEDIA_URL,
    InMemoryObjectStorage,
    make_media,
    png_bytes,
    upload_ready,
)

PRODUCTS = "/api/v1/admin/products"
PUBLIC_PRODUCTS = "/api/v1/public/products"


def images_url(product_id: int) -> str:
    return f"{PRODUCTS}/{product_id}/images"


@pytest.fixture
async def product(committed_session: AsyncSession) -> Product:
    item = await make_product(committed_session, slug="kanat-16", sku="KAN-16")
    await committed_session.commit()
    return item


@pytest.fixture
async def ready_media(committed_session: AsyncSession) -> list[MediaFile]:
    items = [await make_media(committed_session) for _ in range(3)]
    await committed_session.commit()
    return items


async def attach(
    api: AsyncClient, headers: Headers, product_id: int, media: MediaFile, **extra: object
) -> dict:
    response = await api.post(
        images_url(product_id), headers=headers, json={"media_uuid": str(media.uuid), **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def product_audit(engine: AsyncEngine, product_id: int) -> list[AuditLog]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        rows = await session.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == "product", AuditLog.entity_id == product_id)
            .order_by(AuditLog.id)
        )
        return list(rows.scalars().all())


# ================================================================ привязка
async def test_first_image_becomes_main(
    api: AsyncClient, admin: Headers, product: Product, ready_media: list[MediaFile]
) -> None:
    body = await attach(api, admin, product.id, ready_media[0], alt={"ru": "Канат, общий вид"})

    assert body["product_id"] == product.id
    [image] = body["items"]
    assert image["is_main"] is True
    assert image["sort_order"] == 0
    assert image["kind"] == "PHOTO"
    assert image["alt"] == {"ru": "Канат, общий вид"}
    assert image["media_uuid"] == str(ready_media[0].uuid)
    assert image["status"] == "READY"
    assert image["is_publicly_visible"] is True
    assert image["url"].endswith("/variants/large.webp")
    assert (image["width"], image["height"]) == (64, 48)


async def test_next_images_are_appended_in_order(
    api: AsyncClient, admin: Headers, product: Product, ready_media: list[MediaFile]
) -> None:
    for media in ready_media:
        body = await attach(api, admin, product.id, media)

    assert [item["media_uuid"] for item in body["items"]] == [str(m.uuid) for m in ready_media]
    assert [item["sort_order"] for item in body["items"]] == [0, 1, 2]
    assert [item["is_main"] for item in body["items"]] == [True, False, False]


async def test_attach_as_main_moves_the_flag(
    api: AsyncClient, admin: Headers, product: Product, ready_media: list[MediaFile]
) -> None:
    await attach(api, admin, product.id, ready_media[0])
    body = await attach(api, admin, product.id, ready_media[1], is_main=True, kind="SCHEME")

    mains = [item for item in body["items"] if item["is_main"]]
    assert len(mains) == 1
    assert mains[0]["media_uuid"] == str(ready_media[1].uuid)
    assert mains[0]["kind"] == "SCHEME"


async def test_attach_unknown_media(api: AsyncClient, admin: Headers, product: Product) -> None:
    response = await api.post(
        images_url(product.id),
        headers=admin,
        json={"media_uuid": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "media_not_found"


async def test_attach_to_unknown_product(
    api: AsyncClient, admin: Headers, ready_media: list[MediaFile]
) -> None:
    response = await api.post(
        images_url(999_999), headers=admin, json={"media_uuid": str(ready_media[0].uuid)}
    )
    assert response.status_code == 404


async def test_deleted_product_gallery_is_read_only(
    api: AsyncClient, admin: Headers, product: Product, ready_media: list[MediaFile]
) -> None:
    body = await attach(api, admin, product.id, ready_media[0])
    image_id = body["items"][0]["id"]
    await api.delete(f"{PRODUCTS}/{product.id}", headers=admin)

    # Чтение доступно: иначе нельзя разобраться, что восстанавливать.
    assert (await api.get(images_url(product.id), headers=admin)).status_code == 200

    attempts = [
        api.post(
            images_url(product.id), headers=admin, json={"media_uuid": str(ready_media[1].uuid)}
        ),
        api.patch(f"{images_url(product.id)}/{image_id}", headers=admin, json={"kind": "SCHEME"}),
        api.put(f"{images_url(product.id)}/order", headers=admin, json={"image_ids": [image_id]}),
        api.put(f"{images_url(product.id)}/main", headers=admin, json={"image_id": image_id}),
        api.delete(f"{images_url(product.id)}/{image_id}", headers=admin),
    ]
    for attempt in attempts:
        response = await attempt
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "product_deleted"


async def test_failed_media_cannot_be_attached(
    api: AsyncClient, admin: Headers, product: Product, committed_session: AsyncSession
) -> None:
    failed = await make_media(committed_session, status=MediaStatus.FAILED)
    await committed_session.commit()
    response = await api.post(
        images_url(product.id), headers=admin, json={"media_uuid": str(failed.uuid)}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "media_failed"


async def test_processing_media_can_be_attached_but_is_not_public(
    api: AsyncClient, admin: Headers, product: Product, committed_session: AsyncSession
) -> None:
    pending = await make_media(committed_session, status=MediaStatus.PROCESSING)
    await committed_session.commit()
    body = await attach(api, admin, product.id, pending)

    [image] = body["items"]
    assert image["status"] == "PROCESSING"
    assert image["is_publicly_visible"] is False
    assert image["url"] is None
    assert image["variants"] == {}


async def test_duplicate_attach_conflicts(
    api: AsyncClient, admin: Headers, product: Product, ready_media: list[MediaFile]
) -> None:
    await attach(api, admin, product.id, ready_media[0])
    response = await api.post(
        images_url(product.id), headers=admin, json={"media_uuid": str(ready_media[0].uuid)}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "image_already_attached"


async def test_image_limit(
    api: AsyncClient,
    admin: Headers,
    product: Product,
    ready_media: list[MediaFile],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.modules.media.service_admin.MAX_PRODUCT_IMAGES", 2)
    await attach(api, admin, product.id, ready_media[0])
    await attach(api, admin, product.id, ready_media[1])
    response = await api.post(
        images_url(product.id), headers=admin, json={"media_uuid": str(ready_media[2].uuid)}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "product_image_limit"


async def test_same_media_in_several_products(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession, ready_media: list[MediaFile]
) -> None:
    """Один файл (схема узла) может использоваться в нескольких товарах."""
    first = await make_product(committed_session)
    second = await make_product(committed_session)
    await committed_session.commit()
    await attach(api, admin, first.id, ready_media[0])
    await attach(api, admin, second.id, ready_media[0])

    detail = (await api.get(f"{MEDIA_URL}/{ready_media[0].uuid}", headers=admin)).json()
    assert detail["usage_count"] == 2


# ============================================================= подписи
async def test_update_alt_and_kind(
    api: AsyncClient, admin: Headers, product: Product, ready_media: list[MediaFile]
) -> None:
    image_id = (await attach(api, admin, product.id, ready_media[0]))["items"][0]["id"]
    response = await api.patch(
        f"{images_url(product.id)}/{image_id}",
        headers=admin,
        json={"kind": "DRAWING", "alt": {"ru": "Чертёж крепления", "kk": "Сызба"}},
    )
    assert response.status_code == 200
    image = response.json()["items"][0]
    assert image["kind"] == "DRAWING"
    assert image["alt"] == {"ru": "Чертёж крепления", "kk": "Сызба"}


@pytest.mark.parametrize(
    "alt",
    [
        {"kk": "Тек қазақша"},  # нет русского
        {"ru": "<img src=x onerror=alert(1)>"},
        {"ru": "две\nстроки"},
        {"ru": "x" * 256},
        {"russian": "Канат"},
    ],
)
async def test_alt_validation(
    api: AsyncClient,
    admin: Headers,
    product: Product,
    ready_media: list[MediaFile],
    alt: dict[str, str],
) -> None:
    response = await api.post(
        images_url(product.id),
        headers=admin,
        json={"media_uuid": str(ready_media[0].uuid), "alt": alt},
    )
    assert response.status_code == 422


async def test_unknown_image_returns_404(
    api: AsyncClient, admin: Headers, product: Product
) -> None:
    response = await api.patch(f"{images_url(product.id)}/999999", headers=admin, json={})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "product_image_not_found"


async def test_image_of_another_product_is_not_reachable(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession, ready_media: list[MediaFile]
) -> None:
    first = await make_product(committed_session)
    second = await make_product(committed_session)
    await committed_session.commit()
    foreign_id = (await attach(api, admin, first.id, ready_media[0]))["items"][0]["id"]

    response = await api.delete(f"{images_url(second.id)}/{foreign_id}", headers=admin)
    assert response.status_code == 404
    listing = (await api.get(images_url(first.id), headers=admin)).json()
    assert len(listing["items"]) == 1


# ================================================================ порядок
async def test_reorder(
    api: AsyncClient, admin: Headers, product: Product, ready_media: list[MediaFile]
) -> None:
    for media in ready_media:
        body = await attach(api, admin, product.id, media)
    ids = [item["id"] for item in body["items"]]

    response = await api.put(
        f"{images_url(product.id)}/order", headers=admin, json={"image_ids": ids[::-1]}
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == ids[::-1]
    assert [item["sort_order"] for item in items] == [0, 1, 2]
    # Порядок и главное изображение — независимые свойства.
    assert next(item for item in items if item["is_main"])["id"] == ids[0]


@pytest.mark.parametrize("variant", ["missing", "foreign"])
async def test_reorder_requires_exact_set(
    api: AsyncClient,
    admin: Headers,
    product: Product,
    ready_media: list[MediaFile],
    variant: str,
) -> None:
    for media in ready_media[:2]:
        body = await attach(api, admin, product.id, media)
    ids = [item["id"] for item in body["items"]]
    payload = ids[:1] if variant == "missing" else [*ids, 999_999]

    response = await api.put(
        f"{images_url(product.id)}/order", headers=admin, json={"image_ids": payload}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "image_order_mismatch"


async def test_reorder_rejects_duplicates(
    api: AsyncClient, admin: Headers, product: Product, ready_media: list[MediaFile]
) -> None:
    image_id = (await attach(api, admin, product.id, ready_media[0]))["items"][0]["id"]
    response = await api.put(
        f"{images_url(product.id)}/order", headers=admin, json={"image_ids": [image_id, image_id]}
    )
    assert response.status_code == 422


# ====================================================== главное изображение
async def test_set_main_keeps_single_main(
    api: AsyncClient, admin: Headers, product: Product, ready_media: list[MediaFile]
) -> None:
    for media in ready_media:
        body = await attach(api, admin, product.id, media)
    target = body["items"][2]["id"]

    response = await api.put(
        f"{images_url(product.id)}/main", headers=admin, json={"image_id": target}
    )
    assert response.status_code == 200
    mains = [item["id"] for item in response.json()["items"] if item["is_main"]]
    assert mains == [target]

    # Повтор — не ошибка и не новая запись в журнале.
    again = await api.put(
        f"{images_url(product.id)}/main", headers=admin, json={"image_id": target}
    )
    assert again.status_code == 200


async def test_set_main_for_foreign_image(
    api: AsyncClient, admin: Headers, product: Product
) -> None:
    response = await api.put(
        f"{images_url(product.id)}/main", headers=admin, json={"image_id": 999_999}
    )
    assert response.status_code == 404


# ================================================================ отвязка
async def test_detach_main_promotes_next(
    api: AsyncClient, admin: Headers, product: Product, ready_media: list[MediaFile]
) -> None:
    for media in ready_media:
        body = await attach(api, admin, product.id, media)
    ids = [item["id"] for item in body["items"]]

    response = await api.delete(f"{images_url(product.id)}/{ids[0]}", headers=admin)
    assert response.status_code == 204

    items = (await api.get(images_url(product.id), headers=admin)).json()["items"]
    assert [item["id"] for item in items] == ids[1:]
    assert [item["is_main"] for item in items] == [True, False]

    # Файл остаётся в медиатеке.
    media = await api.get(f"{MEDIA_URL}/{ready_media[0].uuid}", headers=admin)
    assert media.status_code == 200
    assert media.json()["usage_count"] == 0


async def test_detached_media_can_be_deleted(
    api: AsyncClient, admin: Headers, product: Product, ready_media: list[MediaFile]
) -> None:
    image_id = (await attach(api, admin, product.id, ready_media[0]))["items"][0]["id"]
    assert (
        await api.delete(f"{MEDIA_URL}/{ready_media[0].uuid}", headers=admin)
    ).status_code == 409

    await api.delete(f"{images_url(product.id)}/{image_id}", headers=admin)
    assert (
        await api.delete(f"{MEDIA_URL}/{ready_media[0].uuid}", headers=admin)
    ).status_code == 204


# ================================================================= аудит
async def test_gallery_changes_are_audited(
    api: AsyncClient,
    admin: Headers,
    product: Product,
    ready_media: list[MediaFile],
    test_engine: AsyncEngine,
) -> None:
    first = (await attach(api, admin, product.id, ready_media[0]))["items"][0]["id"]
    body = await attach(api, admin, product.id, ready_media[1])
    second = body["items"][1]["id"]
    await api.patch(f"{images_url(product.id)}/{second}", headers=admin, json={"kind": "SCHEME"})
    await api.put(
        f"{images_url(product.id)}/order", headers=admin, json={"image_ids": [second, first]}
    )
    await api.put(f"{images_url(product.id)}/main", headers=admin, json={"image_id": second})
    await api.put(f"{images_url(product.id)}/main", headers=admin, json={"image_id": second})
    await api.delete(f"{images_url(product.id)}/{first}", headers=admin)

    entries = await product_audit(test_engine, product.id)
    assert [entry.action for entry in entries] == [
        "media.product_image_attached",
        "media.product_image_attached",
        "media.product_image_updated",
        "media.product_images_reordered",
        "media.product_main_image_changed",  # повторное назначение не пишется
        "media.product_image_detached",
    ]
    assert all(entry.user_id is not None for entry in entries)
    assert entries[3].changes["order"] == {"old": [first, second], "new": [second, first]}
    assert entries[4].changes["main_image_id"] == {"old": first, "new": second}


# ================================================================== права
@pytest.mark.parametrize(
    ("role", "read", "write"),
    [
        (UserRole.ADMIN, 200, 201),
        (UserRole.CONTENT_MANAGER, 200, 201),
        (UserRole.MANAGER, 200, 403),
        (UserRole.VIEWER, 200, 403),
    ],
)
async def test_gallery_permissions(
    api: AsyncClient,
    login_as,
    product: Product,
    ready_media: list[MediaFile],
    role: UserRole,
    read: int,
    write: int,
) -> None:
    headers = await login_as(role)
    assert (await api.get(images_url(product.id), headers=headers)).status_code == read
    response = await api.post(
        images_url(product.id), headers=headers, json={"media_uuid": str(ready_media[0].uuid)}
    )
    assert response.status_code == write


# ================================================================ витрина
async def test_public_catalog_shows_only_ready_images(
    api: AsyncClient,
    admin: Headers,
    committed_session: AsyncSession,
    object_storage: InMemoryObjectStorage,
    test_engine: AsyncEngine,
) -> None:
    """Главным назначено ещё обрабатываемое фото: витрина его не видит
    и берёт обложкой первое готовое. Ключи хранилища наружу не выходят."""
    product = await make_product(committed_session, slug="kanat-public", sku="KAN-PUB")
    processing = await make_media(committed_session, status=MediaStatus.PROCESSING)
    pending = await make_media(committed_session, status=MediaStatus.PENDING)
    await committed_session.commit()
    ready = await upload_ready(api, admin, object_storage, test_engine, data=png_bytes((900, 600)))

    await attach(api, admin, product.id, processing)
    await attach(api, admin, product.id, pending)
    listing = (await api.get(images_url(product.id), headers=admin)).json()
    ready_media = await api.post(
        images_url(product.id),
        headers=admin,
        json={"media_uuid": ready["uuid"], "alt": {"ru": "Фото"}},
    )
    assert ready_media.status_code == 201
    assert listing["items"][0]["is_main"] is True  # главное — неготовое

    detail = await api.get(f"{PUBLIC_PRODUCTS}/kanat-public")
    assert detail.status_code == 200
    images = detail.json()["images"]
    assert len(images) == 1
    assert images[0]["alt"] == "Фото"
    assert images[0]["url"] == (
        f"{settings.CDN_BASE_URL.rstrip('/')}/products/{ready['uuid']}/variants/large.webp"
    )
    assert (images[0]["width"], images[0]["height"]) == (900, 600)
    assert set(images[0]["variants"]) == {"large", "medium", "small", "thumb"}

    item = next(
        entry
        for entry in (await api.get(PUBLIC_PRODUCTS)).json()["items"]
        if entry["slug"] == "kanat-public"
    )
    assert item["image"]["url"] == images[0]["url"]

    for text in (detail.text, (await api.get(PUBLIC_PRODUCTS)).text):
        assert "original" not in text
        assert "storage_key" not in text
        assert str(processing.uuid) not in text
        assert ready["uuid"] in text  # только в составе CDN-ссылки на вариант


def test_primary_url_never_uses_original_key() -> None:
    """Регрессия: READY без вариантов не получает ссылку на приватный оригинал."""
    from app.modules.media.urls import primary_size, primary_url, variant_urls

    key = "products/11111111-1111-1111-1111-111111111111/original.png"
    without_variants = MediaFile(
        storage_key=key, status=MediaStatus.READY.value, variants={}, width=64, height=48
    )
    assert primary_url(without_variants) is None
    assert primary_size(without_variants) == (None, None)
    assert variant_urls(without_variants) == {}

    broken_variants = MediaFile(
        storage_key=key, status=MediaStatus.READY.value, variants={"large": {"w": 1}}
    )
    assert primary_url(broken_variants) is None

    with_variants = MediaFile(
        storage_key=key,
        status=MediaStatus.READY.value,
        variants={"large": {"key": "products/x/variants/large.webp", "w": 800, "h": 600}},
    )
    cdn = settings.CDN_BASE_URL.rstrip("/")
    assert primary_url(with_variants) == f"{cdn}/products/x/variants/large.webp"
    assert primary_size(with_variants) == (800, 600)


async def test_ready_media_without_variants_is_not_public(
    api: AsyncClient, admin: Headers, product: Product, committed_session: AsyncSession
) -> None:
    """Регрессия: такой файл не попадает ни в витрину, ни в ссылки админки."""
    media = await make_media(committed_session, variants={})
    await committed_session.commit()
    [image] = (await attach(api, admin, product.id, media))["items"]
    assert image["url"] is None
    assert image["variants"] == {}

    detail = await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")
    assert detail.json()["images"] == []
    listing = await api.get(PUBLIC_PRODUCTS)
    item = next(entry for entry in listing.json()["items"] if entry["slug"] == "kanat-16")
    assert item["image"] is None

    library = (await api.get(f"{MEDIA_URL}/{media.uuid}", headers=admin)).json()
    assert library["url"] is None
    assert media.storage_key not in str(library)
    for text in (detail.text, listing.text):
        assert media.storage_key not in text
        assert "original" not in text


async def test_public_product_without_ready_images(
    api: AsyncClient, admin: Headers, product: Product, committed_session: AsyncSession
) -> None:
    pending = await make_media(committed_session, status=MediaStatus.PENDING)
    await committed_session.commit()
    await attach(api, admin, product.id, pending)

    detail = (await api.get(f"{PUBLIC_PRODUCTS}/kanat-16")).json()
    assert detail["images"] == []
    listing = (await api.get(PUBLIC_PRODUCTS)).json()
    assert next(entry for entry in listing["items"] if entry["slug"] == "kanat-16")["image"] is None


# =========================================================== производительность
async def test_gallery_list_has_no_n_plus_one(
    api: AsyncClient,
    admin: Headers,
    product: Product,
    committed_session: AsyncSession,
    test_engine: AsyncEngine,
) -> None:
    from app.modules.media.models import ProductImage

    async def add_images(count: int, start: int) -> None:
        for index in range(count):
            media = await make_media(committed_session)
            committed_session.add(
                ProductImage(
                    product_id=product.id,
                    media_file_id=media.id,
                    sort_order=start + index,
                    is_main=start + index == 0,
                )
            )
        await committed_session.commit()

    await add_images(1, 0)
    with count_queries(test_engine) as single:
        assert (await api.get(images_url(product.id), headers=admin)).status_code == 200

    await add_images(9, 1)
    with count_queries(test_engine) as many:
        body = (await api.get(images_url(product.id), headers=admin)).json()

    assert len(body["items"]) == 10
    assert len(many) == len(single)


async def test_public_catalog_images_have_no_n_plus_one(
    api: AsyncClient, committed_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    from app.modules.media.models import ProductImage

    async def add_product_with_images(index: int) -> None:
        product = await make_product(committed_session, slug=f"p-{index}", sku=f"P-{index}")
        for position in range(2):
            media = await make_media(committed_session)
            committed_session.add(
                ProductImage(
                    product_id=product.id,
                    media_file_id=media.id,
                    sort_order=position,
                    is_main=position == 0,
                )
            )
        await committed_session.commit()

    await add_product_with_images(0)
    with count_queries(test_engine) as single:
        assert (await api.get(PUBLIC_PRODUCTS)).status_code == 200

    for index in range(1, 8):
        await add_product_with_images(index)
    with count_queries(test_engine) as many:
        body = (await api.get(PUBLIC_PRODUCTS, params={"page_size": 60})).json()

    assert body["total"] == 8
    assert all(item["image"] is not None for item in body["items"])
    assert len(many) == len(single)
