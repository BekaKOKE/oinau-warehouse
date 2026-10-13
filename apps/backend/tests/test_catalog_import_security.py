"""Безопасность приёма XLSX: тип по содержимому, размер, ZIP, XML, имена."""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import Headers
from tests.import_helpers import (
    PREVIEW,
    build_workbook,
    preview,
    product_row,
    upload,
)


def valid_xlsx() -> bytes:
    return build_workbook({"Products": [product_row("SEC-1", categories="kanaty")]})


def rebuild_zip(
    data: bytes, replace: dict[str, bytes], *, extra: dict[str, bytes] | None = None
) -> bytes:
    """Копия книги с подменёнными частями."""
    source = zipfile.ZipFile(BytesIO(data))
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            target.writestr(item.filename, replace.get(item.filename, source.read(item.filename)))
        for name, content in (extra or {}).items():
            target.writestr(name, content)
    return buffer.getvalue()


def error_code(response) -> str:
    return response.json()["error"]["code"]


# ============================================================== тип файла
@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"sku;slug\nA-1;a-1\n", "not_xlsx"),  # CSV под видом .xlsx
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512, "not_xlsx"),  # старый .xls / OLE2
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "not_xlsx"),
    ],
)
async def test_non_xlsx_content_is_rejected(
    api: AsyncClient, admin: Headers, content: bytes, reason: str
) -> None:
    response = await upload(api, PREVIEW, admin, content)
    assert response.status_code == 415
    assert error_code(response) == "import_unsupported_file"
    assert response.json()["error"]["details"]["reason"] == reason


async def test_zip_that_is_not_a_workbook_is_rejected(api: AsyncClient, admin: Headers) -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hello")
    response = await upload(api, PREVIEW, admin, buffer.getvalue())
    assert response.status_code == 415


async def test_extension_and_declared_type_are_checked(api: AsyncClient, admin: Headers) -> None:
    data = valid_xlsx()
    response = await upload(api, PREVIEW, admin, data, filename="catalog.csv")
    assert response.status_code == 415
    assert response.json()["error"]["details"]["reason"] == "extension"

    response = await upload(api, PREVIEW, admin, data, content_type="text/csv")
    assert response.status_code == 415
    assert response.json()["error"]["details"]["reason"] == "content_type"

    # octet-stream допустим: реальная проверка — по содержимому.
    response = await upload(api, PREVIEW, admin, data, content_type="application/octet-stream")
    assert response.status_code == 200


async def test_macro_enabled_workbook_is_rejected(api: AsyncClient, admin: Headers) -> None:
    data = rebuild_zip(valid_xlsx(), {}, extra={"xl/vbaProject.bin": b"\x00" * 16})
    response = await upload(api, PREVIEW, admin, data, filename="catalog.xlsx")
    assert response.status_code == 415
    assert response.json()["error"]["details"]["reason"] == "macro_enabled"


async def test_xlsm_content_type_is_rejected(api: AsyncClient, admin: Headers) -> None:
    source = zipfile.ZipFile(BytesIO(valid_xlsx()))
    content_types = source.read("[Content_Types].xml").replace(
        b"spreadsheetml.sheet.main+xml", b"ms-excel.sheet.macroEnabled.main+xml"
    )
    data = rebuild_zip(valid_xlsx(), {"[Content_Types].xml": content_types})
    response = await upload(api, PREVIEW, admin, data)
    assert response.status_code == 415


# ================================================================= размер
async def test_too_large_file_is_rejected(
    api: AsyncClient, admin: Headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_MAX_SIZE_MB", 1)
    response = await upload(api, PREVIEW, admin, b"PK\x03\x04" + b"\x00" * (1024 * 1024 + 10))
    assert response.status_code == 413
    assert error_code(response) == "import_file_too_large"
    assert response.json()["error"]["details"]["max_size_mb"] == 1


async def test_zip_bomb_is_rejected_before_parsing(
    api: AsyncClient, admin: Headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "IMPORT_MAX_UNCOMPRESSED_MB", 1)
    # 3 МБ нулей сжимаются в несколько килобайт.
    data = rebuild_zip(valid_xlsx(), {}, extra={"xl/media/bomb.bin": b"\x00" * (3 * 1024 * 1024)})
    assert len(data) < 100_000

    response = await upload(api, PREVIEW, admin, data)
    assert response.status_code == 413
    assert response.json()["error"]["details"]["reason"] == "uncompressed_size"


async def test_too_many_rows_is_reported(
    api: AsyncClient, admin: Headers, catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "IMPORT_MAX_ROWS_PER_SHEET", 5)
    data = build_workbook({"Products": [product_row(f"R-{index}") for index in range(7)]})
    report = await preview(api, admin, data)
    assert report["valid"] is False
    assert [item["code"] for item in report["errors"]] == ["too_many_rows"]


# ======================================================== повреждённые файлы
async def test_truncated_xlsx_is_rejected(api: AsyncClient, admin: Headers) -> None:
    data = valid_xlsx()
    response = await upload(api, PREVIEW, admin, data[: len(data) // 2])
    assert response.status_code == 422
    assert error_code(response) == "import_file_corrupted"


async def test_malformed_workbook_xml_is_rejected(api: AsyncClient, admin: Headers) -> None:
    data = rebuild_zip(valid_xlsx(), {"xl/workbook.xml": b"<workbook><not-closed>"})
    response = await upload(api, PREVIEW, admin, data)
    assert response.status_code == 422
    assert error_code(response) == "import_file_corrupted"


async def test_xml_external_entities_are_not_resolved(api: AsyncClient, admin: Headers) -> None:
    """XXE: defusedxml запрещает DTD с сущностями — файл отвергается целиком."""
    source = zipfile.ZipFile(BytesIO(valid_xlsx()))
    sheet = source.read("xl/worksheets/sheet1.xml").decode()
    hostile = sheet.replace(
        "<worksheet",
        '<!DOCTYPE worksheet [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><worksheet',
        1,
    ).replace("SEC-1", "&xxe;", 1)
    data = rebuild_zip(valid_xlsx(), {"xl/worksheets/sheet1.xml": hostile.encode()})

    response = await upload(api, PREVIEW, admin, data)
    assert response.status_code == 422
    assert error_code(response) == "import_file_corrupted"
    assert "root:" not in response.text


async def test_billion_laughs_is_rejected(api: AsyncClient, admin: Headers) -> None:
    source = zipfile.ZipFile(BytesIO(valid_xlsx()))
    sheet = source.read("xl/worksheets/sheet1.xml").decode()
    entities = '<!ENTITY a "aaaaaaaaaa">' + "".join(
        f'<!ENTITY {chr(98 + index)} "{("&" + chr(97 + index) + ";") * 10}">' for index in range(8)
    )
    hostile = sheet.replace("<worksheet", f"<!DOCTYPE worksheet [{entities}]><worksheet", 1)
    data = rebuild_zip(valid_xlsx(), {"xl/worksheets/sheet1.xml": hostile.encode()})

    response = await upload(api, PREVIEW, admin, data)
    assert response.status_code == 422


async def test_unsafe_zip_paths_are_rejected(api: AsyncClient, admin: Headers) -> None:
    data = rebuild_zip(valid_xlsx(), {}, extra={"../../evil.txt": b"x"})
    response = await upload(api, PREVIEW, admin, data)
    assert response.status_code == 422
    assert response.json()["error"]["details"]["reason"] == "unsafe_path"


# ================================================================ запрос
async def test_missing_file_field(api: AsyncClient, admin: Headers) -> None:
    response = await api.post(
        PREVIEW, headers=admin, data={"note": "без файла"}, files={"other": ("x.txt", b"x")}
    )
    assert response.status_code == 422
    assert error_code(response) == "import_file_missing"


async def test_non_multipart_body(api: AsyncClient, admin: Headers) -> None:
    response = await api.post(PREVIEW, headers=admin, content=valid_xlsx())
    assert response.status_code == 400
    assert error_code(response) == "import_upload_invalid"


async def test_several_files_are_rejected(api: AsyncClient, admin: Headers) -> None:
    data = valid_xlsx()
    response = await api.post(
        PREVIEW,
        headers=admin,
        files=[("file", ("a.xlsx", data)), ("file", ("b.xlsx", data))],
    )
    assert response.status_code == 400


async def test_filename_is_sanitized(api: AsyncClient, admin: Headers, catalog) -> None:
    for raw in ("..\\..\\windows\\каталог.xlsx", "../../etc/каталог.xlsx"):
        response = await upload(api, PREVIEW, admin, valid_xlsx(), filename=raw)
        assert response.status_code == 200
        assert response.json()["job"]["filename"] == "каталог.xlsx"


async def test_errors_do_not_expose_internals(api: AsyncClient, admin: Headers) -> None:
    response = await upload(api, PREVIEW, admin, b"PK\x03\x04garbage")
    body = response.text
    assert "Traceback" not in body
    assert "zipfile" not in body.lower()
