"""Быстрый заказ — POST /api/v1/public/quick-requests и файлы в админке."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.config import settings
from app.modules.audit.models import AuditLog
from app.modules.notifications.models import NotificationOutbox
from app.modules.requests.models import Request, RequestAttachment, RequestItem
from app.modules.requests.sku_list import parse_sku_list
from app.modules.users.enums import UserRole
from tests.catalog_fixtures import CatalogFixture
from tests.customer_helpers import CUSTOMER, REQUESTS_URL
from tests.request_helpers import (
    ADMIN_REQUESTS,
    CUSTOMER_EMAIL,
    CUSTOMER_NAME,
    CUSTOMER_PHONE,
    CUSTOMER_PHONE_NORMALIZED,
    load_request,
)

QUICK = "/api/v1/public/quick-requests"
CUSTOMER_QUICK = f"{CUSTOMER}/quick-requests"
ROPE = "KAN-16-PP"  # TIERED: 1–9 → 3500, 10–49 → 3200
FASTENER = "KRP-M10"  # FIXED: 1200
PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _form(mode: str, **fields: Any) -> dict[str, str]:
    body = {"mode": mode, "name": CUSTOMER_NAME, "phone": CUSTOMER_PHONE}
    body.update({key: str(value) for key, value in fields.items()})
    return body


async def _post(
    api: AsyncClient,
    data: dict[str, str],
    *,
    file: tuple[str, bytes, str] | None = None,
    headers: dict[str, str] | None = None,
    url: str = QUICK,
) -> Response:
    """multipart/form-data, как шлёт браузер через FormData.

    Поля передаются частями без имени файла: так httpx собирает
    multipart и тогда, когда файла нет.
    """
    parts: list[tuple[str, Any]] = [(key, (None, value)) for key, value in data.items()]
    if file is not None:
        parts.append(("file", file))
    return await api.post(url, files=parts, headers=headers)


async def _created(api: AsyncClient, data: dict[str, str], **kwargs: Any) -> dict[str, Any]:
    response = await _post(api, data, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


async def _count(session: AsyncSession, model: Any) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def _items(session: AsyncSession, number: str) -> list[RequestItem]:
    request = await load_request(session, number)
    query = (
        select(RequestItem)
        .where(RequestItem.request_id == request.id)
        .order_by(RequestItem.sort_order)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(query)).scalars().all())


# ======================================================= разбор списка
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("OIN-1042 × 20", [("OIN-1042", "20")]),
        ("OIN-1042 x 20\nOIN-2210 - 4 шт", [("OIN-1042", "20"), ("OIN-2210", "4")]),
        ("OIN-1042 × 20, OIN-2210 × 4", [("OIN-1042", "20"), ("OIN-2210", "4")]),
        ("KAN-16-PP 12,5 м", [("KAN-16-PP", "12.5")]),
        ("OIN-1042: 7", [("OIN-1042", "7")]),
        ("OIN-1042", [("OIN-1042", None)]),
        # Строка из Excel: запятая в названии — не граница позиций
        ("OIN-1042\tПодвес, оцинк.\t20", [("OIN-1042", "20")]),
        # Два числа подряд — неоднозначно, количество не угадываем
        ("OIN-1042 20 30", [("OIN-1042", None)]),
        ("  \n\n", []),
    ],
)
def test_parse_sku_list(text: str, expected: list[tuple[str, str | None]]) -> None:
    entries = parse_sku_list(text)
    assert [
        (entry.candidates[0][0], str(qty) if (qty := entry.candidates[0][1]) is not None else None)
        for entry in entries
    ] == expected


def test_parse_glued_sku_offers_split_variant() -> None:
    """«KRP-M10x5»: сначала слово целиком, затем разрезанное по «x»."""
    [entry] = parse_sku_list("KRP-M10x5")
    assert entry.candidates == (("KRP-M10x5", None), ("KRP-M10", Decimal("5")))


# ================================================== обратный звонок
async def test_callback_creates_request_without_items(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    body = await _created(
        api, _form("CALLBACK", company="ТОО Площадка", comment="Нужны подвесы на 5 качелей")
    )

    assert re.fullmatch(r"R-\d{4}-\d{6}", body["number"])
    assert body["mode"] == "CALLBACK"
    assert body["items"] == []
    assert body["total_estimate"] is None
    assert body["unrecognized"] == []
    assert body["attachment"] is None

    request = await load_request(committed_session, body["number"])
    assert request.kind == "GENERAL"
    assert request.source == "QUICK_CALLBACK"
    assert request.status == "NEW"
    assert request.customer_name == CUSTOMER_NAME
    assert request.phone == CUSTOMER_PHONE_NORMALIZED
    assert request.company == "ТОО Площадка"
    assert request.comment == "Нужны подвесы на 5 качелей"
    # Регион в быстрой форме не спрашивается
    assert request.region_id is None


async def test_one_click_adds_product_with_minimum_quantity(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    catalog.products["fastener"].min_order_qty = Decimal("4")
    await committed_session.commit()

    body = await _created(api, _form("CALLBACK", product_sku=FASTENER))

    request = await load_request(committed_session, body["number"])
    assert request.kind == "CART"
    assert request.source == "ONE_CLICK"
    [item] = await _items(committed_session, body["number"])
    assert (item.sku_snapshot, item.quantity, item.unit_price_snapshot) == (
        FASTENER,
        Decimal("4.000"),
        Decimal("1200.00"),
    )
    assert Decimal(body["total_estimate"]) == Decimal("4800.00")


async def test_one_click_with_explicit_quantity_uses_price_tiers(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    body = await _created(api, _form("CALLBACK", product_sku=ROPE, quantity="10"))
    assert body["items"][0]["unit_price"] == "3200.00"


async def test_one_click_rejects_hidden_product(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    response = await _post(api, _form("CALLBACK", product_sku="DRAFT-1"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "product_unavailable"
    assert await _count(committed_session, Request) == 0


async def test_one_click_rejects_quantity_below_minimum(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    catalog.products["rope"].min_order_qty = Decimal("5")
    await committed_session.commit()

    response = await _post(api, _form("CALLBACK", product_sku=ROPE, quantity="2"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "quantity_below_minimum"


# =================================================== список артикулов
async def test_sku_list_resolves_known_and_keeps_unknown(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    text = "kan-16-pp × 10\nKRP-M10x3\nNOPE-1 × 2\nKAN-16-PP 5\nСиденье синее 4 шт"
    body = await _created(api, _form("SKU_LIST", sku_list=text, email=CUSTOMER_EMAIL))

    assert body["mode"] == "SKU_LIST"
    # Регистр не важен, повтор артикула складывается в одну позицию
    assert [(item["sku"], item["quantity"]) for item in body["items"]] == [
        (ROPE, "15.000"),
        (FASTENER, "3.000"),
    ]
    assert body["unrecognized"] == ["NOPE-1 × 2", "Сиденье синее 4 шт"]
    assert Decimal(body["total_estimate"]) == Decimal("51600.00")  # 15 × 3200 + 3 × 1200

    request = await load_request(committed_session, body["number"])
    assert request.kind == "CART"
    assert request.source == "SKU_LIST"
    assert request.email == CUSTOMER_EMAIL
    # Нераспознанное менеджер видит в комментарии как есть
    assert request.comment is not None
    assert "Не найдено в каталоге:\nNOPE-1 × 2\nСиденье синее 4 шт" in request.comment


async def test_sku_list_without_quantity_uses_minimum(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    catalog.products["rope"].min_order_qty = Decimal("25")
    await committed_session.commit()

    body = await _created(api, _form("SKU_LIST", sku_list=ROPE))
    assert body["items"][0]["quantity"] == "25.000"
    assert body["below_minimum"] == []


async def test_sku_list_below_minimum_is_accepted_with_warning(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    catalog.products["rope"].min_order_qty = Decimal("10")
    await committed_session.commit()

    body = await _created(api, _form("SKU_LIST", sku_list=f"{ROPE} × 3"))

    assert body["below_minimum"] == [{"sku": ROPE, "quantity": "3", "min_order_qty": "10.000"}]
    request = await load_request(committed_session, body["number"])
    assert request.comment == f"Меньше минимальной партии:\n{ROPE}: 3 (минимум 10)"


async def test_sku_list_with_nothing_recognized_still_reaches_manager(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    body = await _created(api, _form("SKU_LIST", sku_list="Канат 16 мм — 40 метров"))

    assert body["items"] == []
    request = await load_request(committed_session, body["number"])
    assert request.kind == "GENERAL"
    assert "Канат 16 мм — 40 метров" in (request.comment or "")


@pytest.mark.parametrize("text", ["", "   ", ",,,"])
async def test_sku_list_must_not_be_empty(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession, text: str
) -> None:
    response = await _post(api, _form("SKU_LIST", sku_list=text))
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"validation_error", "quick_request_empty"}
    assert await _count(committed_session, Request) == 0


async def test_sku_list_too_long_is_rejected(api: AsyncClient, catalog: CatalogFixture) -> None:
    text = "\n".join(f"SKU-{index} × 1" for index in range(101))
    response = await _post(api, _form("SKU_LIST", sku_list=text))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "too_many_items"


# ======================================================== запрос КП
async def test_quote_with_file_stores_attachment_in_database(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    body = await _created(
        api,
        _form("QUOTE", email=CUSTOMER_EMAIL, company="ТОО Площадка", bin="123456789012"),
        file=("Спецификация объекта.pdf", PDF, "application/pdf"),
    )

    assert body["mode"] == "QUOTE"
    assert body["attachment"] == {"filename": "Спецификация объекта.pdf", "size_bytes": len(PDF)}

    request = await load_request(committed_session, body["number"])
    assert request.kind == "GENERAL"
    assert request.source == "QUOTE_REQUEST"
    assert request.bin == "123456789012"
    [attachment] = (
        (
            await committed_session.execute(
                select(RequestAttachment)
                .where(RequestAttachment.request_id == request.id)
                # Содержимое в модели отложено — в тесте оно нужно сразу.
                .options(undefer(RequestAttachment.data))
            )
        )
        .scalars()
        .all()
    )
    assert attachment.filename == "Спецификация объекта.pdf"
    assert attachment.content_type == "application/pdf"
    assert attachment.size_bytes == len(PDF)
    assert attachment.sha256 == hashlib.sha256(PDF).hexdigest()
    assert attachment.data == PDF


async def test_quote_with_comment_only_is_accepted(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    body = await _created(
        api, _form("QUOTE", email=CUSTOMER_EMAIL, comment="Комплектация на 3 площадки")
    )
    assert body["attachment"] is None


async def test_quote_without_file_and_comment_is_rejected(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    response = await _post(api, _form("QUOTE", email=CUSTOMER_EMAIL))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "quick_request_empty"
    assert await _count(committed_session, Request) == 0


async def test_quote_requires_email(api: AsyncClient, catalog: CatalogFixture) -> None:
    response = await _post(api, _form("QUOTE", comment="КП на канаты"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("virus.exe", b"MZ\x90\x00"),
        ("page.html", b"<html><script>alert(1)</script></html>"),
        # Расширение PDF, содержимое — PNG
        ("spec.pdf", PNG),
        # Текстовый формат с нулевыми байтами — не текст
        ("list.csv", b"sku,qty\x00\x00\x00"),
    ],
)
async def test_quote_rejects_unsupported_files(
    api: AsyncClient,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
    filename: str,
    content: bytes,
) -> None:
    response = await _post(
        api,
        _form("QUOTE", email=CUSTOMER_EMAIL),
        file=(filename, content, "application/octet-stream"),
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "attachment_unsupported"
    assert await _count(committed_session, Request) == 0


async def test_quote_accepts_known_formats_by_signature(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    for filename, content in [
        ("plan.dwg", b"AC1032" + b"\x00" * 16),
        ("list.xlsx", b"PK\x03\x04" + b"\x00" * 16),
        ("old.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16),
        ("photo.JPG", b"\xff\xd8\xff\xe0" + b"\x00" * 16),
        ("list.csv", "артикул;количество\nKAN-16-PP;10".encode()),
    ]:
        body = await _created(
            api,
            _form("QUOTE", email=CUSTOMER_EMAIL),
            file=(filename, content, "application/octet-stream"),
        )
        assert body["attachment"]["filename"] == filename


async def test_quote_rejects_too_large_file(
    api: AsyncClient,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "REQUEST_ATTACHMENT_MAX_SIZE_MB", 1)
    response = await _post(
        api,
        _form("QUOTE", email=CUSTOMER_EMAIL),
        file=("big.pdf", PDF + b"0" * (1024 * 1024), "application/pdf"),
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "attachment_too_large"
    assert await _count(committed_session, Request) == 0


async def test_file_is_accepted_only_for_quote(api: AsyncClient, catalog: CatalogFixture) -> None:
    response = await _post(api, _form("CALLBACK"), file=("spec.pdf", PDF, "application/pdf"))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "quick_request_form_invalid"


# ============================================================ форма
async def test_json_body_is_rejected(api: AsyncClient, catalog: CatalogFixture) -> None:
    response = await api.post(QUICK, json=_form("CALLBACK"))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "quick_request_form_invalid"


async def test_unknown_field_is_rejected(api: AsyncClient, catalog: CatalogFixture) -> None:
    """Цена и статус от клиента не принимаются — как и у корзины."""
    response = await _post(api, _form("CALLBACK", status="COMPLETED"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "fields",
    [
        {"phone": "12"},
        {"name": " "},
        {"bin": "12345"},
        {"mode": "ORDER"},
        {"quantity": "5"},  # количество без товара
    ],
)
async def test_invalid_fields_are_rejected(
    api: AsyncClient, catalog: CatalogFixture, fields: dict[str, str]
) -> None:
    response = await _post(api, {**_form("CALLBACK"), **fields})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_idempotency_key_returns_same_request(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession
) -> None:
    headers = {"Idempotency-Key": "quick-0001-abcdef"}
    data = _form("QUOTE", email=CUSTOMER_EMAIL, comment="КП")
    first = await _created(api, data, headers=headers, file=("a.pdf", PDF, "application/pdf"))
    second = await _created(api, data, headers=headers, file=("a.pdf", PDF, "application/pdf"))

    assert second["number"] == first["number"]
    assert second["attachment"] == first["attachment"]
    assert await _count(committed_session, Request) == 1
    assert await _count(committed_session, RequestAttachment) == 1


async def test_audit_and_outbox_have_no_file_content(
    api: AsyncClient,
    catalog: CatalogFixture,
    committed_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "NOTIFY_EMAILS", ["sales@oinau-pro.kz"])
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", [])
    body = await _created(
        api,
        _form("QUOTE", email=CUSTOMER_EMAIL, comment="КП на канаты"),
        file=("Спецификация.pdf", PDF, "application/pdf"),
    )

    [entry] = (await committed_session.execute(select(AuditLog))).scalars().all()
    assert entry.changes["source"] == "QUOTE_REQUEST"
    assert entry.changes["attachments_count"] == 1
    dumped = str(entry.changes)
    assert CUSTOMER_NAME not in dumped
    assert CUSTOMER_PHONE_NORMALIZED not in dumped

    [outbox] = (await committed_session.execute(select(NotificationOutbox))).scalars().all()
    assert outbox.payload["number"] == body["number"]
    assert outbox.payload["source"] == "QUOTE_REQUEST"
    assert outbox.payload["comment"] == "КП на канаты"
    assert outbox.payload["attachments"] == ["Спецификация.pdf"]


# ========================================================== админка
async def test_admin_sees_and_downloads_attachment(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession, admin: dict
) -> None:
    body = await _created(
        api,
        _form("QUOTE", email=CUSTOMER_EMAIL),
        file=("Спецификация объекта.pdf", PDF, "application/pdf"),
    )
    request = await load_request(committed_session, body["number"])

    detail = (await api.get(f"{ADMIN_REQUESTS}/{request.id}", headers=admin)).json()
    assert detail["source"] == "QUOTE_REQUEST"
    assert detail["kind"] == "GENERAL"
    [attachment] = detail["attachments"]
    assert attachment["filename"] == "Спецификация объекта.pdf"
    assert attachment["size_bytes"] == len(PDF)
    assert "data" not in attachment

    response = await api.get(
        f"{ADMIN_REQUESTS}/{request.id}/attachments/{attachment['id']}", headers=admin
    )
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''%D0%A1" in disposition


async def test_attachment_of_another_request_is_not_found(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession, admin: dict
) -> None:
    with_file = await _created(
        api, _form("QUOTE", email=CUSTOMER_EMAIL), file=("a.pdf", PDF, "application/pdf")
    )
    other = await _created(api, _form("CALLBACK"))
    owner = await load_request(committed_session, with_file["number"])
    stranger = await load_request(committed_session, other["number"])
    [attachment_id] = (
        (
            await committed_session.execute(
                select(RequestAttachment.id).where(RequestAttachment.request_id == owner.id)
            )
        )
        .scalars()
        .all()
    )

    response = await api.get(
        f"{ADMIN_REQUESTS}/{stranger.id}/attachments/{attachment_id}", headers=admin
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "request_attachment_not_found"


async def test_attachment_download_requires_request_read(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession, login_as
) -> None:
    body = await _created(
        api, _form("QUOTE", email=CUSTOMER_EMAIL), file=("a.pdf", PDF, "application/pdf")
    )
    request = await load_request(committed_session, body["number"])
    headers = await login_as(UserRole.CONTENT_MANAGER)

    response = await api.get(f"{ADMIN_REQUESTS}/{request.id}/attachments/1", headers=headers)
    assert response.status_code == 403
    anonymous = await api.get(f"{ADMIN_REQUESTS}/{request.id}/attachments/1")
    assert anonymous.status_code == 401


async def test_admin_list_filters_by_source(
    api: AsyncClient, catalog: CatalogFixture, admin: dict
) -> None:
    await _created(api, _form("CALLBACK"))
    quote = await _created(api, _form("QUOTE", email=CUSTOMER_EMAIL, comment="КП"))

    body = (await api.get(ADMIN_REQUESTS, params={"source": "QUOTE_REQUEST"}, headers=admin)).json()
    assert [item["number"] for item in body["items"]] == [quote["number"]]
    assert body["items"][0]["source"] == "QUOTE_REQUEST"
    assert body["items"][0]["items_count"] == 0


# ========================================================== кабинет
async def test_customer_quick_request_appears_in_cabinet(
    api: AsyncClient, catalog: CatalogFixture, committed_session: AsyncSession, customer_headers
) -> None:
    customer, headers = await customer_headers()
    body = await _created(
        api, _form("SKU_LIST", sku_list=f"{ROPE} × 10"), headers=headers, url=CUSTOMER_QUICK
    )

    request = await load_request(committed_session, body["number"])
    assert request.customer_id == customer.id

    listing = (await api.get(REQUESTS_URL, headers=headers)).json()
    assert [(item["number"], item["source"]) for item in listing["items"]] == [
        (body["number"], "SKU_LIST")
    ]


async def test_customer_quick_request_requires_token(
    api: AsyncClient, catalog: CatalogFixture
) -> None:
    response = await _post(api, _form("CALLBACK"), url=CUSTOMER_QUICK)
    assert response.status_code == 401
