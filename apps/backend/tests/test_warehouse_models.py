"""Ограничения схемы складских документов (_docs/warehouse-design.md §1, §9.1).

Как и в test_models.py, проверяется не работа SQLAlchemy, а то, что БД
сама защищает данные: правила должны держаться и тогда, когда строку
пишет не сервис упаковки, а обмен с 1С или ручная правка.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.models import Stock
from app.modules.users.enums import UserRole
from app.modules.users.models import User
from app.modules.warehouse.enums import WarehouseDocumentStatus
from tests.factories import make_product, make_request, make_request_item, unique
from tests.warehouse_helpers import make_document, make_line, make_package, make_warehouse

BACKEND_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_REVISION = "e17c6f22c085"

NOW = datetime.now(UTC)

CREATED = WarehouseDocumentStatus.CREATED.value
PACKED = WarehouseDocumentStatus.PACKED.value
CANCELLED = WarehouseDocumentStatus.CANCELLED.value


def _document_fields(status: str) -> dict[str, object]:
    """Минимальный набор полей, с которым документ в этом статусе допустим."""
    if status == PACKED:
        return {"status": PACKED, "packed_at": NOW}
    if status == CANCELLED:
        return {"status": CANCELLED, "cancelled_at": NOW}
    return {"status": CREATED}


# ------------------------------------------------------- значения по умолчанию
async def test_new_document_gets_created_status_and_uuid(db: AsyncSession) -> None:
    document = await make_document(db)
    await db.refresh(document)

    assert document.status == CREATED
    assert isinstance(document.uuid, uuid.UUID)


async def test_package_gets_uuid_from_database(db: AsyncSession) -> None:
    """uuid упаковки — токен QR-кода: его выдаёт БД, и он у каждой свой."""
    document = await make_document(db, package_count=2)
    line = await make_line(db, document)
    first = await make_package(db, document, line, seq=1)
    second = await make_package(db, document, line, seq=2)
    await db.refresh(first)
    await db.refresh(second)

    assert isinstance(first.uuid, uuid.UUID)
    assert isinstance(second.uuid, uuid.UUID)
    assert first.uuid != second.uuid


# -------------------------------------------------------- статус и количество
async def test_unknown_document_status_is_rejected(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_warehouse_documents_status"):
        await make_document(db, status="SHIPPED")


async def test_zero_package_count_is_rejected(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_warehouse_documents_package_count_positive"):
        await make_document(db, package_count=0)


# ---------------------------------------------------------- метки времени
async def test_packed_document_requires_packed_at(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_warehouse_documents_packed_has_time"):
        await make_document(db, status=PACKED)


async def test_cancelled_document_requires_cancelled_at(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_warehouse_documents_cancelled_iff_time"):
        await make_document(db, status=CANCELLED)


async def test_cancelled_at_requires_cancelled_status(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_warehouse_documents_cancelled_iff_time"):
        await make_document(db, status=CREATED, cancelled_at=NOW)


async def test_exported_at_requires_packed_at(db: AsyncSession) -> None:
    """1С никогда не видит документ, который не был упакован."""
    with pytest.raises(IntegrityError, match="ck_warehouse_documents_export_after_pack"):
        await make_document(db, status=CREATED, exported_at=NOW)


async def test_write_off_confirmation_requires_export(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_warehouse_documents_write_off_after_export"):
        await make_document(db, status=PACKED, packed_at=NOW, write_off_confirmed_at=NOW)


async def test_cancel_export_requires_cancelled_status(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_warehouse_documents_cancel_export_valid"):
        await make_document(
            db, status=PACKED, packed_at=NOW, exported_at=NOW, cancel_exported_at=NOW
        )


async def test_cancel_export_requires_export(db: AsyncSession) -> None:
    """Аннулирование до чтения документа 1С её не касается."""
    with pytest.raises(IntegrityError, match="ck_warehouse_documents_cancel_export_valid"):
        await make_document(db, status=CANCELLED, cancelled_at=NOW, cancel_exported_at=NOW)


async def test_complete_exchange_with_1c_is_accepted(db: AsyncSession) -> None:
    """Обе полные цепочки допустимы: списание и аннулирование после чтения."""
    await make_document(
        db, status=PACKED, packed_at=NOW, exported_at=NOW, write_off_confirmed_at=NOW
    )
    await make_document(
        db,
        status=CANCELLED,
        packed_at=NOW,
        exported_at=NOW,
        cancelled_at=NOW,
        cancel_exported_at=NOW,
    )


# ------------------------------------------- один действующий документ на заявку
@pytest.mark.parametrize("first", [CREATED, PACKED])
@pytest.mark.parametrize("second", [CREATED, PACKED])
async def test_second_active_document_for_request_is_rejected(
    db: AsyncSession, first: str, second: str
) -> None:
    request = await make_request(db)
    await make_document(db, request=request, **_document_fields(first))
    with pytest.raises(IntegrityError, match="uq_warehouse_documents_active_request"):
        await make_document(db, request=request, **_document_fields(second))


async def test_new_document_is_allowed_after_cancellation(db: AsyncSession) -> None:
    """Аннулированный документ не блокирует новое разбиение заявки."""
    request = await make_request(db)
    document = await make_document(db, request=request)
    document.status = CANCELLED
    document.cancelled_at = NOW
    await db.flush()

    await make_document(db, request=request)
    # И второй аннулированный документ той же заявки тоже допустим.
    await make_document(db, request=request, **_document_fields(CANCELLED))


# ------------------------------------------------------------- уникальность
async def test_document_number_is_unique(db: AsyncSession) -> None:
    number = unique("WH")
    await make_document(db, number=number)
    with pytest.raises(IntegrityError, match="uq_warehouse_documents_number"):
        await make_document(db, number=number)


async def test_idempotency_key_is_unique_when_present(db: AsyncSession) -> None:
    key = unique("idem")
    await make_document(db, idempotency_key=key)
    with pytest.raises(IntegrityError, match="uq_warehouse_documents_idempotency_key"):
        await make_document(db, idempotency_key=key)


async def test_several_documents_without_idempotency_key(db: AsyncSession) -> None:
    """NULL не конфликтует с NULL."""
    await make_document(db)
    await make_document(db)


async def test_external_id_is_unique_when_present(db: AsyncSession) -> None:
    external_id = unique("1c")
    await make_document(db, external_id=external_id)
    with pytest.raises(IntegrityError, match="uq_warehouse_documents_external_id"):
        await make_document(db, external_id=external_id)


async def test_several_documents_without_external_id(db: AsyncSession) -> None:
    await make_document(db)
    await make_document(db)


# -------------------------------------------------------------------- строки
@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-1")])
async def test_line_quantity_must_be_positive(db: AsyncSession, quantity: Decimal) -> None:
    document = await make_document(db)
    with pytest.raises(IntegrityError, match="ck_warehouse_document_lines_quantity_positive"):
        await make_line(db, document, quantity=quantity)


async def test_line_is_unique_per_document_and_request_item(db: AsyncSession) -> None:
    request = await make_request(db)
    product = await make_product(db)
    request_item = await make_request_item(db, request, product)
    document = await make_document(db, request=request)
    await make_line(db, document, request_item=request_item)

    with pytest.raises(IntegrityError, match="uq_warehouse_document_lines_document_item"):
        await make_line(db, document, request_item=request_item, sort_order=1)


# ------------------------------------------------------------------ упаковки
@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-1")])
async def test_package_quantity_must_be_positive(db: AsyncSession, quantity: Decimal) -> None:
    document = await make_document(db)
    line = await make_line(db, document)
    with pytest.raises(IntegrityError, match="ck_warehouse_packages_quantity_positive"):
        await make_package(db, document, line, quantity=quantity)


async def test_package_seq_starts_at_one(db: AsyncSession) -> None:
    document = await make_document(db)
    line = await make_line(db, document)
    with pytest.raises(IntegrityError, match="ck_warehouse_packages_seq_positive"):
        await make_package(db, document, line, seq=0)


async def test_package_seq_is_unique_within_document(db: AsyncSession) -> None:
    document = await make_document(db, package_count=2)
    line = await make_line(db, document)
    await make_package(db, document, line, seq=1)
    with pytest.raises(IntegrityError, match="uq_warehouse_packages_document_seq"):
        await make_package(db, document, line, seq=1)


# ---------------------------------------------------------- роль кладовщика
async def test_warehouse_role_is_accepted(db: AsyncSession) -> None:
    db.add(_warehouse_user())
    await db.flush()


# ------------------------------------------------------------------- остатки
async def test_stock_reported_at_is_empty_until_set(db: AsyncSession) -> None:
    product = await make_product(db)
    warehouse = await make_warehouse(db)
    stock = Stock(product_id=product.id, warehouse_id=warehouse.id, quantity=Decimal("5"))
    db.add(stock)
    await db.flush()

    query = select(Stock.reported_at).where(Stock.product_id == product.id)
    assert (await db.execute(query)).scalar_one() is None

    stock.reported_at = NOW
    await db.flush()
    assert (await db.execute(query)).scalar_one() == NOW


# ------------------------------------------------------------ номера документов
async def test_document_number_sequence_grows(db: AsyncSession) -> None:
    query = text("SELECT nextval('warehouse_document_number_seq')")
    first = (await db.execute(query)).scalar_one()
    second = (await db.execute(query)).scalar_one()

    assert first >= 1
    assert second > first


# ------------------------------------------------------------ откат миграции
def _warehouse_user(**kwargs: object) -> User:
    return User(
        email=f"{unique('wh')}@oinau-pro.kz",
        password_hash="h",
        full_name="Кладовщик",
        role=UserRole.WAREHOUSE.value,
        **kwargs,  # type: ignore[arg-type]
    )


def _load_migration() -> ModuleType:
    """Модуль миграции складской упаковки — без запуска самой миграции."""
    scripts = ScriptDirectory(str(BACKEND_ROOT / "alembic"))
    revision = scripts.get_revision(WAREHOUSE_REVISION)
    assert revision is not None
    return revision.module


async def _run_downgrade_guard(db: AsyncSession) -> None:
    guard = _load_migration().ensure_no_warehouse_users
    await db.run_sync(lambda session: guard(session.connection()))


async def test_downgrade_guard_passes_without_warehouse_users(db: AsyncSession) -> None:
    await _run_downgrade_guard(db)


async def test_downgrade_guard_stops_on_warehouse_user(db: AsyncSession) -> None:
    db.add(_warehouse_user())
    await db.flush()

    with pytest.raises(RuntimeError, match="WAREHOUSE"):
        await _run_downgrade_guard(db)


@pytest.mark.parametrize(
    "fields",
    [{"is_active": False}, {"deleted_at": NOW}],
    ids=["inactive", "soft-deleted"],
)
async def test_downgrade_guard_counts_inactive_and_deleted_users(
    db: AsyncSession, fields: dict[str, object]
) -> None:
    """Старый CHECK проверил бы и такие строки, поэтому откат стоит и на них."""
    db.add(_warehouse_user(**fields))
    await db.flush()

    with pytest.raises(RuntimeError, match="WAREHOUSE"):
        await _run_downgrade_guard(db)
