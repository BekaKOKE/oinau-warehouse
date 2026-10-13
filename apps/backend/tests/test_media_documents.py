"""Документы в медиатеке: схемы и чертежи товара (PDF, DWG, DXF)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.catalog.models import Product
from app.modules.media.documents import content_disposition, sniff_document_mime
from tests.bundle_helpers import DWG_BYTES, DXF_BYTES, PDF_BYTES
from tests.conftest import Headers
from tests.factories import make_product
from tests.media_helpers import (
    MEDIA_URL,
    InMemoryObjectStorage,
    media_id_by_uuid,
    run_worker,
    upload,
    upload_ready,
)

PRODUCTS = "/api/v1/admin/products"
PUBLIC_PRODUCTS = "/api/v1/public/products"


@pytest.fixture
async def product(committed_session: AsyncSession) -> Product:
    item = await make_product(committed_session, slug="sidene-504", sku="504-176")
    await committed_session.commit()
    return item


async def upload_document(
    api: AsyncClient,
    headers: Headers,
    storage: InMemoryObjectStorage,
    engine: AsyncEngine,
    *,
    data: bytes = PDF_BYTES,
    content_type: str = "application/pdf",
    filename: str = "504-176.pdf",
) -> dict:
    media = await upload(
        api, headers, storage, data=data, content_type=content_type, filename=filename
    )
    assert media["status"] == "PROCESSING"
    result = await run_worker(engine, storage, await media_id_by_uuid(engine, media["uuid"]))
    assert result == "READY"
    response = await api.get(f"{MEDIA_URL}/{media['uuid']}", headers=headers)
    return response.json()


def test_signatures() -> None:
    assert sniff_document_mime(PDF_BYTES) == "application/pdf"
    assert sniff_document_mime(DWG_BYTES) == "image/vnd.dwg"
    assert sniff_document_mime(DXF_BYTES) == "image/vnd.dxf"
    assert sniff_document_mime(b"AutoCAD Binary DXF\r\n\x1a\x00...") == "image/vnd.dxf"
    assert sniff_document_mime(b"<html><script>") is None
    assert sniff_document_mime(b"MZ\x90\x00") is None


def test_content_disposition_keeps_cyrillic_name() -> None:
    header = content_disposition("application/pdf", "Схема 504-176.pdf")
    assert header.startswith("inline;")
    assert 'filename="______504-176.pdf"' in header
    assert "filename*=UTF-8''%D0%A1%D1%85%D0%B5%D0%BC%D0%B0%20504-176.pdf" in header
    assert content_disposition("image/vnd.dwg", "plan.dwg").startswith("attachment;")


@pytest.mark.parametrize(
    ("data", "content_type", "filename", "extension"),
    [
        (PDF_BYTES, "application/pdf", "504-176.pdf", "pdf"),
        (DWG_BYTES, "image/vnd.dwg", "plan.dwg", "dwg"),
        (DXF_BYTES, "image/vnd.dxf", "plan.dxf", "dxf"),
    ],
)
async def test_document_is_published_as_copy_not_original(
    api: AsyncClient,
    admin: Headers,
    object_storage: InMemoryObjectStorage,
    test_engine: AsyncEngine,
    data: bytes,
    content_type: str,
    filename: str,
    extension: str,
) -> None:
    media = await upload_document(
        api,
        admin,
        object_storage,
        test_engine,
        data=data,
        content_type=content_type,
        filename=filename,
    )
    assert media["status"] == "READY"
    assert media["url"].endswith(f"/variants/file.{extension}")
    assert "original" not in media["url"]
    key = next(key for key in object_storage.objects if key.endswith(f"variants/file.{extension}"))
    assert object_storage.objects[key][0] == data
    assert object_storage.dispositions[key].split(";")[0] == (
        "inline" if extension == "pdf" else "attachment"
    )


async def test_disguised_document_is_rejected(
    api: AsyncClient, admin: Headers, object_storage: InMemoryObjectStorage
) -> None:
    intent = await api.post(
        f"{MEDIA_URL}/upload-intent",
        headers=admin,
        json={"filename": "evil.pdf", "content_type": "application/pdf", "size_bytes": 20},
    )
    created = intent.json()
    object_storage.put_by_url(created["upload"]["url"], b"<script>alert(1)</script>", "x")
    complete = await api.post(f"{MEDIA_URL}/{created['media']['uuid']}/complete", headers=admin)
    assert complete.status_code == 422
    assert complete.json()["error"]["details"]["failure_reason"] == "type_mismatch"


async def test_document_can_be_scheme_but_not_photo_or_cover(
    api: AsyncClient,
    admin: Headers,
    object_storage: InMemoryObjectStorage,
    test_engine: AsyncEngine,
    product: Product,
) -> None:
    url = f"{PRODUCTS}/{product.id}/images"
    document = await upload_document(api, admin, object_storage, test_engine)

    as_photo = await api.post(url, headers=admin, json={"media_uuid": document["uuid"]})
    assert as_photo.status_code == 409
    assert as_photo.json()["error"]["code"] == "document_kind_invalid"

    scheme = await api.post(
        url, headers=admin, json={"media_uuid": document["uuid"], "kind": "SCHEME"}
    )
    assert scheme.status_code == 201, scheme.text
    [item] = scheme.json()["items"]
    # Первый привязанный документ не становится обложкой
    assert item["is_main"] is False
    assert item["content_type"] == "application/pdf"

    main = await api.put(f"{url}/main", headers=admin, json={"image_id": item["id"]})
    assert main.status_code == 409
    to_photo = await api.patch(f"{url}/{item['id']}", headers=admin, json={"kind": "PHOTO"})
    assert to_photo.status_code == 409

    photo = await upload_ready(api, admin, object_storage, test_engine)
    attached = await api.post(url, headers=admin, json={"media_uuid": photo["uuid"]})
    items = attached.json()["items"]
    assert [(entry["kind"], entry["is_main"]) for entry in items] == [
        ("SCHEME", False),
        ("PHOTO", True),
    ]


async def test_storefront_separates_gallery_and_documents(
    api: AsyncClient,
    admin: Headers,
    object_storage: InMemoryObjectStorage,
    test_engine: AsyncEngine,
    product: Product,
) -> None:
    url = f"{PRODUCTS}/{product.id}/images"
    photo = await upload_ready(api, admin, object_storage, test_engine)
    scheme_image = await upload_ready(api, admin, object_storage, test_engine, filename="s.png")
    document = await upload_document(api, admin, object_storage, test_engine)
    await api.post(url, headers=admin, json={"media_uuid": photo["uuid"]})
    await api.post(url, headers=admin, json={"media_uuid": scheme_image["uuid"], "kind": "SCHEME"})
    await api.post(url, headers=admin, json={"media_uuid": document["uuid"], "kind": "DRAWING"})

    body = (await api.get(f"{PUBLIC_PRODUCTS}/{product.slug}")).json()
    assert [image["kind"] for image in body["images"]] == ["PHOTO"]
    assert [(item["kind"], item["content_type"]) for item in body["documents"]] == [
        ("SCHEME", "image/webp"),
        ("DRAWING", "application/pdf"),
    ]
    assert body["documents"][0]["preview_url"]
    assert body["documents"][1]["preview_url"] is None
    assert body["documents"][1]["filename"] == "504-176.pdf"

    listing = (await api.get(PUBLIC_PRODUCTS)).json()
    [row] = [item for item in listing["items"] if item["sku"] == product.sku]
    assert row["image"]["kind"] == "PHOTO"
