"""Интеграционные тесты медиатеки: загрузка, проверка, обработка, удаление."""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.modules.audit.models import AuditLog
from app.modules.media.models import MediaFile
from app.modules.users.enums import UserRole
from tests.conftest import Headers
from tests.helpers import count_queries
from tests.media_helpers import (
    MEDIA_URL,
    FakeMediaQueue,
    InMemoryObjectStorage,
    jpeg_bytes,
    make_media,
    media_id_by_uuid,
    png_bytes,
    run_worker,
    upload,
    upload_ready,
)

INTENT_URL = f"{MEDIA_URL}/upload-intent"
UUID_KEY = re.compile(r"^products/[0-9a-f-]{36}/original\.png$")


def intent_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "filename": "канат.png",
        "content_type": "image/png",
        "size_bytes": 1024,
    }
    body.update(overrides)
    return body


async def media_row(engine: AsyncEngine, media_uuid: str) -> MediaFile:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        return (
            await session.execute(select(MediaFile).where(MediaFile.uuid == uuid.UUID(media_uuid)))
        ).scalar_one()


async def audit_actions(engine: AsyncEngine, entity_type: str, entity_id: int) -> list[AuditLog]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        rows = await session.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.id)
        )
        return list(rows.scalars().all())


# ============================================================ upload-intent
async def test_upload_intent_creates_pending_record(
    api: AsyncClient, admin: Headers, object_storage: InMemoryObjectStorage, test_engine
) -> None:
    response = await api.post(INTENT_URL, headers=admin, json=intent_body())
    assert response.status_code == 201

    body = response.json()
    media = body["media"]
    assert media["status"] == "PENDING"
    assert media["original_filename"] == "канат.png"
    assert media["content_type"] == "image/png"
    assert media["size_bytes"] == 1024
    assert media["url"] is None
    assert media["variants"] == {}
    assert "storage_key" not in media

    upload_info = body["upload"]
    assert upload_info["method"] == "PUT"
    assert upload_info["headers"] == {"Content-Type": "image/png"}
    assert upload_info["expires_in"] == settings.UPLOAD_PRESIGN_TTL_SECONDS

    # Ключ — только UUID и расширение из MIME. Имя клиента в ключ не попадает.
    row = await media_row(test_engine, media["uuid"])
    assert UUID_KEY.fullmatch(row.storage_key)
    assert str(row.uuid) in row.storage_key
    assert "канат" not in upload_info["url"]
    assert row.bucket == settings.S3_BUCKET
    assert object_storage.presigned == [row.storage_key]


async def test_content_purpose_uses_content_prefix(
    api: AsyncClient, admin: Headers, test_engine
) -> None:
    response = await api.post(INTENT_URL, headers=admin, json=intent_body(purpose="CONTENT"))
    row = await media_row(test_engine, response.json()["media"]["uuid"])
    assert row.storage_key.startswith("content/")


async def test_filename_path_is_stripped(api: AsyncClient, admin: Headers) -> None:
    """Браузеры и скрипты иногда присылают путь целиком — хранится только имя."""
    response = await api.post(
        INTENT_URL, headers=admin, json=intent_body(filename="C:\\fakepath\\..\\фото <1>.png")
    )
    assert response.status_code == 201
    assert response.json()["media"]["original_filename"] == "фото 1.png"


@pytest.mark.parametrize(
    "overrides",
    [
        {"content_type": "image/gif"},
        {"content_type": "application/zip"},
        {"content_type": "text/html"},
        {"size_bytes": 0},
        {"size_bytes": 16 * 1024 * 1024},
        {"filename": ""},
        {"filename": "\x00\x01"},
        {"storage_key": "products/evil.png"},  # лишнее поле
        {"purpose": "AVATAR"},
    ],
)
async def test_upload_intent_validation(
    api: AsyncClient, admin: Headers, overrides: dict[str, object]
) -> None:
    response = await api.post(INTENT_URL, headers=admin, json=intent_body(**overrides))
    assert response.status_code == 422


@pytest.mark.parametrize("content_type", ["application/pdf", "image/vnd.dwg", "image/vnd.dxf"])
async def test_documents_are_accepted_with_own_size_limit(
    api: AsyncClient, admin: Headers, content_type: str
) -> None:
    """Схемы и чертежи: свой список типов и свой предел размера (50 МБ)."""
    ok = await api.post(
        INTENT_URL,
        headers=admin,
        json=intent_body(
            filename="scheme.pdf", content_type=content_type, size_bytes=40 * 1024 * 1024
        ),
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["media"]["content_type"] == content_type
    too_big = await api.post(
        INTENT_URL,
        headers=admin,
        json=intent_body(content_type=content_type, size_bytes=51 * 1024 * 1024),
    )
    assert too_big.status_code == 422


async def test_content_type_is_case_insensitive(api: AsyncClient, admin: Headers) -> None:
    response = await api.post(INTENT_URL, headers=admin, json=intent_body(content_type="IMAGE/PNG"))
    assert response.status_code == 201
    assert response.json()["media"]["content_type"] == "image/png"


# ================================================================ complete
async def test_complete_moves_to_processing_and_enqueues(
    api: AsyncClient,
    admin: Headers,
    object_storage: InMemoryObjectStorage,
    media_queue: FakeMediaQueue,
    test_engine,
) -> None:
    data = png_bytes()
    media = await upload(api, admin, object_storage, data=data)

    assert media["status"] == "PROCESSING"
    assert media["size_bytes"] == len(data)  # фактический размер по HEAD
    assert media_queue.enqueued == [await media_id_by_uuid(test_engine, media["uuid"])]


async def test_complete_without_uploaded_object(
    api: AsyncClient, admin: Headers, media_queue: FakeMediaQueue
) -> None:
    created = (await api.post(INTENT_URL, headers=admin, json=intent_body())).json()
    response = await api.post(f"{MEDIA_URL}/{created['media']['uuid']}/complete", headers=admin)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "upload_not_found"
    detail = (await api.get(f"{MEDIA_URL}/{created['media']['uuid']}", headers=admin)).json()
    assert detail["status"] == "PENDING"  # загрузку можно повторить
    assert media_queue.enqueued == []


@pytest.mark.parametrize(
    ("declared", "payload", "reason"),
    [
        ("image/png", jpeg_bytes(), "type_mismatch"),
        ("image/png", b"<script>alert(1)</script>", "type_mismatch"),
        ("image/jpeg", b"GIF89a" + b"\x00" * 64, "type_mismatch"),
        ("image/webp", png_bytes(), "type_mismatch"),
        ("image/png", b"", "empty_file"),
    ],
)
async def test_complete_rejects_disguised_files(
    api: AsyncClient,
    admin: Headers,
    object_storage: InMemoryObjectStorage,
    media_queue: FakeMediaQueue,
    declared: str,
    payload: bytes,
    reason: str,
) -> None:
    """Сигнатура файла обязана совпадать с заявленным типом."""
    created = (
        await api.post(
            INTENT_URL,
            headers=admin,
            json=intent_body(content_type=declared, size_bytes=max(len(payload), 1)),
        )
    ).json()
    key = object_storage.put_by_url(created["upload"]["url"], payload, declared)

    response = await api.post(f"{MEDIA_URL}/{created['media']['uuid']}/complete", headers=admin)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "upload_rejected"
    assert response.json()["error"]["details"]["failure_reason"] == reason

    detail = (await api.get(f"{MEDIA_URL}/{created['media']['uuid']}", headers=admin)).json()
    assert detail["status"] == "FAILED"
    assert detail["failure_reason"] == reason
    assert key not in object_storage.objects  # отвергнутый объект удалён
    assert media_queue.enqueued == []


async def test_complete_rejects_oversized_object(
    api: AsyncClient,
    admin: Headers,
    object_storage: InMemoryObjectStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Presigned PUT не ограничивает тело — реальный размер проверяется по HEAD."""
    monkeypatch.setattr(settings, "UPLOAD_MAX_SIZE_MB", 1)
    created = (await api.post(INTENT_URL, headers=admin, json=intent_body(size_bytes=100))).json()
    oversized = png_bytes() + b"\x00" * (1024 * 1024)
    object_storage.put_by_url(created["upload"]["url"], oversized, "image/png")

    response = await api.post(f"{MEDIA_URL}/{created['media']['uuid']}/complete", headers=admin)
    assert response.status_code == 422
    assert response.json()["error"]["details"]["failure_reason"] == "size_exceeded"


async def test_complete_is_idempotent(
    api: AsyncClient,
    admin: Headers,
    object_storage: InMemoryObjectStorage,
    media_queue: FakeMediaQueue,
    test_engine,
) -> None:
    media = await upload(api, admin, object_storage, data=png_bytes())
    complete_url = f"{MEDIA_URL}/{media['uuid']}/complete"

    # Повтор в PROCESSING — задача ставится снова (вдруг прошлая потерялась)
    again = await api.post(complete_url, headers=admin)
    assert again.status_code == 202
    assert again.json()["status"] == "PROCESSING"
    assert len(media_queue.enqueued) == 2

    await run_worker(test_engine, object_storage, media_queue.enqueued[0])
    ready = await api.post(complete_url, headers=admin)
    assert ready.status_code == 202
    assert ready.json()["status"] == "READY"
    assert len(media_queue.enqueued) == 2


async def test_complete_for_failed_media_conflicts(
    api: AsyncClient, admin: Headers, object_storage: InMemoryObjectStorage
) -> None:
    created = (await api.post(INTENT_URL, headers=admin, json=intent_body())).json()
    object_storage.put_by_url(created["upload"]["url"], b"not an image", "image/png")
    complete_url = f"{MEDIA_URL}/{created['media']['uuid']}/complete"
    assert (await api.post(complete_url, headers=admin)).status_code == 422

    response = await api.post(complete_url, headers=admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "media_failed"


async def test_queue_outage_does_not_break_complete(
    api: AsyncClient,
    admin: Headers,
    object_storage: InMemoryObjectStorage,
    media_queue: FakeMediaQueue,
) -> None:
    """Загрузка подтверждена и сохранена; повторный complete поставит задачу."""
    media_queue.broken = True
    media = await upload(api, admin, object_storage, data=png_bytes())
    assert media["status"] == "PROCESSING"

    media_queue.broken = False
    again = await api.post(f"{MEDIA_URL}/{media['uuid']}/complete", headers=admin)
    assert again.status_code == 202
    assert len(media_queue.enqueued) == 1


async def test_unknown_media_returns_404(api: AsyncClient, admin: Headers) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    for method, url in [
        ("GET", f"{MEDIA_URL}/{missing}"),
        ("POST", f"{MEDIA_URL}/{missing}/complete"),
        ("DELETE", f"{MEDIA_URL}/{missing}"),
    ]:
        response = await api.request(method, url, headers=admin)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "media_not_found"


# =============================================================== обработка
async def test_worker_builds_variants_and_metadata(
    api: AsyncClient, admin: Headers, object_storage: InMemoryObjectStorage, test_engine
) -> None:
    data = png_bytes((2400, 1200))
    media = await upload(api, admin, object_storage, data=data)
    media_id = await media_id_by_uuid(test_engine, media["uuid"])

    assert await run_worker(test_engine, object_storage, media_id) == "READY"

    detail = (await api.get(f"{MEDIA_URL}/{media['uuid']}", headers=admin)).json()
    assert detail["status"] == "READY"
    assert detail["width"] == 2400
    assert detail["height"] == 1200
    assert detail["failure_reason"] is None
    assert set(detail["variants"]) == {"large", "medium", "small", "thumb"}

    # Публичная ссылка — CDN + ключ варианта; оригинал наружу не выходит.
    cdn = settings.CDN_BASE_URL.rstrip("/")
    assert detail["url"] == f"{cdn}/products/{media['uuid']}/variants/large.webp"
    assert all("original" not in url for url in detail["variants"].values())

    row = await media_row(test_engine, media["uuid"])
    assert row.checksum is not None and len(row.checksum) == 64
    assert row.variants["large"] == {
        "key": f"products/{media['uuid']}/variants/large.webp",
        "w": 1600,
        "h": 800,
    }
    assert row.variants["thumb"]["w"] == 200

    stored, content_type, cache_control = object_storage.objects[row.variants["large"]["key"]]
    assert content_type == "image/webp"
    assert cache_control == "public, max-age=31536000, immutable"
    assert stored[:4] == b"RIFF" and stored[8:12] == b"WEBP"


async def test_small_image_is_not_upscaled(
    api: AsyncClient, admin: Headers, object_storage: InMemoryObjectStorage, test_engine
) -> None:
    media = await upload_ready(api, admin, object_storage, test_engine, data=png_bytes((100, 50)))
    row = await media_row(test_engine, media["uuid"])
    assert row.variants["large"]["w"] == 100
    assert row.variants["large"]["h"] == 50


async def test_worker_strips_exif_and_applies_orientation(
    api: AsyncClient, admin: Headers, object_storage: InMemoryObjectStorage, test_engine
) -> None:
    """EXIF (геометки, камера) в публичный файл не попадает; поворот применён."""
    from io import BytesIO

    from PIL import Image

    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: повернуть на 90°
    exif[0x010F] = "SecretCameraVendor"
    data = jpeg_bytes((80, 40), exif=exif.tobytes())

    media = await upload(
        api, admin, object_storage, data=data, content_type="image/jpeg", filename="a.jpg"
    )
    await run_worker(
        test_engine, object_storage, await media_id_by_uuid(test_engine, media["uuid"])
    )

    row = await media_row(test_engine, media["uuid"])
    assert (row.width, row.height) == (40, 80)
    variant = object_storage.objects[row.variants["large"]["key"]][0]
    assert b"SecretCameraVendor" not in variant
    assert not Image.open(BytesIO(variant)).getexif()


async def test_worker_fails_undecodable_file(
    api: AsyncClient, admin: Headers, object_storage: InMemoryObjectStorage, test_engine
) -> None:
    """Сигнатура PNG верна, но внутри мусор — отсекает только декодер."""
    broken = b"\x89PNG\r\n\x1a\n" + b"\x00garbage" * 50
    media = await upload(api, admin, object_storage, data=broken)
    media_id = await media_id_by_uuid(test_engine, media["uuid"])

    assert await run_worker(test_engine, object_storage, media_id) == "FAILED"

    row = await media_row(test_engine, media["uuid"])
    assert row.status == "FAILED"
    assert row.failure_reason == "decode_failed"
    assert row.storage_key not in object_storage.objects
    assert row.storage_key in object_storage.deleted


async def test_worker_rejects_decompression_bomb(
    api: AsyncClient,
    admin: Headers,
    object_storage: InMemoryObjectStorage,
    test_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_MAX_IMAGE_PIXELS", 1000)
    media = await upload(api, admin, object_storage, data=png_bytes((100, 100)))
    media_id = await media_id_by_uuid(test_engine, media["uuid"])

    assert await run_worker(test_engine, object_storage, media_id) == "FAILED"
    assert (await media_row(test_engine, media["uuid"])).failure_reason == "too_many_pixels"


async def test_worker_skips_media_not_in_processing(
    api: AsyncClient, admin: Headers, object_storage: InMemoryObjectStorage, test_engine
) -> None:
    media = await upload_ready(api, admin, object_storage, test_engine)
    media_id = await media_id_by_uuid(test_engine, media["uuid"])
    assert await run_worker(test_engine, object_storage, media_id) == "skipped"
    assert await run_worker(test_engine, object_storage, 999_999) == "skipped"


async def test_storage_failure_marks_media_failed(
    api: AsyncClient, admin: Headers, object_storage: InMemoryObjectStorage, test_engine
) -> None:
    media = await upload(api, admin, object_storage, data=png_bytes())
    media_id = await media_id_by_uuid(test_engine, media["uuid"])

    async def broken_write(*_args: object, **_kwargs: object) -> None:
        raise ConnectionError("storage unavailable")

    object_storage.write = broken_write  # type: ignore[method-assign]
    assert await run_worker(test_engine, object_storage, media_id) == "FAILED"
    assert (await media_row(test_engine, media["uuid"])).failure_reason == "processing_error"


# =================================================================== аудит
async def test_upload_flow_is_audited(
    api: AsyncClient, admin: Headers, object_storage: InMemoryObjectStorage, test_engine
) -> None:
    media = await upload_ready(api, admin, object_storage, test_engine, filename="секрет.png")
    media_id = await media_id_by_uuid(test_engine, media["uuid"])

    entries = await audit_actions(test_engine, "media_file", media_id)
    assert [entry.action for entry in entries] == [
        "media.upload_requested",
        "media.upload_completed",
        "media.processed",
    ]
    assert entries[0].user_id is not None
    assert entries[2].user_id is None
    assert entries[2].actor == "system"
    assert entries[1].changes["status"] == {"old": "PENDING", "new": "PROCESSING"}


async def test_rejection_is_audited(
    api: AsyncClient, admin: Headers, object_storage: InMemoryObjectStorage, test_engine
) -> None:
    created = (await api.post(INTENT_URL, headers=admin, json=intent_body())).json()
    object_storage.put_by_url(created["upload"]["url"], b"MZ\x90\x00", "image/png")
    await api.post(f"{MEDIA_URL}/{created['media']['uuid']}/complete", headers=admin)

    media_id = await media_id_by_uuid(test_engine, created["media"]["uuid"])
    actions = [entry.action for entry in await audit_actions(test_engine, "media_file", media_id)]
    assert actions == ["media.upload_requested", "media.upload_rejected"]


# ================================================================ удаление
async def test_delete_unused_media_removes_objects(
    api: AsyncClient, admin: Headers, object_storage: InMemoryObjectStorage, test_engine
) -> None:
    media = await upload_ready(api, admin, object_storage, test_engine)
    row = await media_row(test_engine, media["uuid"])
    keys = [row.storage_key, *(item["key"] for item in row.variants.values())]

    response = await api.delete(f"{MEDIA_URL}/{media['uuid']}", headers=admin)
    assert response.status_code == 204
    assert (await api.get(f"{MEDIA_URL}/{media['uuid']}", headers=admin)).status_code == 404
    assert set(keys) <= set(object_storage.deleted)
    assert not any(key in object_storage.objects for key in keys)

    actions = [entry.action for entry in await audit_actions(test_engine, "media_file", row.id)]
    assert actions[-1] == "media.deleted"


async def test_pending_media_can_be_deleted(api: AsyncClient, admin: Headers) -> None:
    """Отмена загрузки: запись PENDING удаляется, объекта может и не быть."""
    created = (await api.post(INTENT_URL, headers=admin, json=intent_body())).json()
    response = await api.delete(f"{MEDIA_URL}/{created['media']['uuid']}", headers=admin)
    assert response.status_code == 204


async def test_media_attached_to_product_cannot_be_deleted(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    from tests.factories import make_product

    product = await make_product(committed_session)
    media = await make_media(committed_session)
    await committed_session.commit()
    attach = await api.post(
        f"/api/v1/admin/products/{product.id}/images",
        headers=admin,
        json={"media_uuid": str(media.uuid)},
    )
    assert attach.status_code == 201

    response = await api.delete(f"{MEDIA_URL}/{media.uuid}", headers=admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "media_in_use"
    assert response.json()["error"]["details"]["products_count"] == 1

    detail = (await api.get(f"{MEDIA_URL}/{media.uuid}", headers=admin)).json()
    assert detail["usage_count"] == 1
    assert detail["products"][0]["product_id"] == product.id
    assert detail["products"][0]["sku"] == product.sku


async def test_media_used_by_deleted_product_is_still_protected(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    """Удалённый товар можно восстановить — вместе с его галереей."""
    from tests.factories import make_product

    product = await make_product(committed_session)
    media = await make_media(committed_session)
    await committed_session.commit()
    await api.post(
        f"/api/v1/admin/products/{product.id}/images",
        headers=admin,
        json={"media_uuid": str(media.uuid)},
    )
    await api.delete(f"/api/v1/admin/products/{product.id}", headers=admin)

    response = await api.delete(f"{MEDIA_URL}/{media.uuid}", headers=admin)
    assert response.status_code == 409
    detail = (await api.get(f"{MEDIA_URL}/{media.uuid}", headers=admin)).json()
    assert detail["products"][0]["is_deleted"] is True


async def test_media_used_in_content_cannot_be_deleted(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    media = await make_media(committed_session)
    await committed_session.commit()
    saved = await api.put(
        "/api/v1/admin/content/home",
        headers=admin,
        json={"seo": {"og_image": str(media.uuid)}},
    )
    assert saved.status_code == 200

    response = await api.delete(f"{MEDIA_URL}/{media.uuid}", headers=admin)
    assert response.status_code == 409
    assert response.json()["error"]["details"]["content_sections"] == ["home"]
    detail = (await api.get(f"{MEDIA_URL}/{media.uuid}", headers=admin)).json()
    assert detail["content_sections"] == ["home"]


# ================================================================= список
async def test_list_filters_and_search(
    api: AsyncClient, admin: Headers, committed_session: AsyncSession
) -> None:
    from app.modules.media.enums import MediaStatus

    await make_media(committed_session, original_filename="kanat-front.png")
    await make_media(committed_session, original_filename="seat.png")
    await make_media(committed_session, status=MediaStatus.PENDING, original_filename="new.png")
    await committed_session.commit()

    everything = (await api.get(MEDIA_URL, headers=admin)).json()
    assert everything["total"] == 3

    ready = (await api.get(MEDIA_URL, headers=admin, params={"status": "READY"})).json()
    assert ready["total"] == 2
    assert all(item["url"] for item in ready["items"])

    pending = (await api.get(MEDIA_URL, headers=admin, params={"status": "PENDING"})).json()
    assert pending["items"][0]["url"] is None

    found = (await api.get(MEDIA_URL, headers=admin, params={"search": "kanat"})).json()
    assert [item["original_filename"] for item in found["items"]] == ["kanat-front.png"]


async def test_media_list_has_no_n_plus_one(
    api: AsyncClient,
    admin: Headers,
    committed_session: AsyncSession,
    test_engine: AsyncEngine,
) -> None:
    """Число привязок считается агрегатом, а не запросом на каждый файл."""
    from app.modules.media.models import ProductImage
    from tests.factories import make_product

    async def add_used_media() -> None:
        product = await make_product(committed_session)
        media = await make_media(committed_session)
        committed_session.add(ProductImage(product_id=product.id, media_file_id=media.id))
        await committed_session.flush()

    await add_used_media()
    await committed_session.commit()
    with count_queries(test_engine) as single:
        assert (await api.get(MEDIA_URL, headers=admin)).status_code == 200

    for _ in range(10):
        await add_used_media()
    await committed_session.commit()
    with count_queries(test_engine) as many:
        body = (await api.get(MEDIA_URL, headers=admin)).json()

    assert body["total"] == 11
    assert all(item["usage_count"] == 1 for item in body["items"])
    assert len(many) == len(single)


# ================================================================== права
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (UserRole.SUPERADMIN, 201),
        (UserRole.ADMIN, 201),
        (UserRole.CONTENT_MANAGER, 201),
        (UserRole.MANAGER, 403),
        (UserRole.VIEWER, 403),
    ],
)
async def test_upload_permissions(
    api: AsyncClient, login_as, role: UserRole, expected: int
) -> None:
    headers = await login_as(role)
    response = await api.post(INTENT_URL, headers=headers, json=intent_body())
    assert response.status_code == expected


@pytest.mark.parametrize(
    ("role", "read", "delete"),
    [
        (UserRole.CONTENT_MANAGER, 200, 204),
        (UserRole.MANAGER, 200, 403),
        (UserRole.VIEWER, 200, 403),
    ],
)
async def test_library_permissions(
    api: AsyncClient,
    login_as,
    committed_session: AsyncSession,
    role: UserRole,
    read: int,
    delete: int,
) -> None:
    """Чтение — catalog.read, удаление — catalog.write."""
    media = await make_media(committed_session)
    await committed_session.commit()
    headers = await login_as(role)

    assert (await api.get(MEDIA_URL, headers=headers)).status_code == read
    assert (await api.get(f"{MEDIA_URL}/{media.uuid}", headers=headers)).status_code == read
    assert (await api.delete(f"{MEDIA_URL}/{media.uuid}", headers=headers)).status_code == delete


async def test_media_requires_authentication(api: AsyncClient) -> None:
    assert (await api.get(MEDIA_URL)).status_code == 401
    assert (await api.post(INTENT_URL, json=intent_body())).status_code == 401


# ============================================================ S3-хранилище
async def test_presigned_url_uses_public_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подпись — чистая криптография, сеть не нужна. Проверяем, что ссылка
    для браузера строится на публичный адрес (localhost:9000 у MinIO),
    а не на внутренний адрес контейнера, и что тип входит в подпись."""
    from app.infrastructure.storage.s3 import S3ObjectStorage

    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setattr(settings, "S3_PUBLIC_ENDPOINT_URL", "http://localhost:9000")
    monkeypatch.setattr(settings, "S3_ACCESS_KEY_ID", "minioadmin")
    monkeypatch.setattr(settings, "S3_SECRET_ACCESS_KEY", "minioadmin")

    upload_url = await S3ObjectStorage("oinau-media").create_upload_url(
        "products/abc/original.png", content_type="image/png", expires_in=600
    )

    assert upload_url.url.startswith("http://localhost:9000/oinau-media/products/abc/original.png?")
    assert "X-Amz-Signature=" in upload_url.url
    assert "X-Amz-Expires=600" in upload_url.url
    assert "content-type" in upload_url.url.lower()
    assert upload_url.method == "PUT"
    assert upload_url.headers == {"Content-Type": "image/png"}
