"""Складские документы упаковки: сводный документ, его строки и упаковки.

Одна заявка превращается в один сводный документ и несколько упаковок
(_docs/warehouse-design.md §1). Списывает товар в 1С только сводный
документ; упаковки — состав коробок и QR-коды, они остаток не трогают.

Сайт по-прежнему не меняет остатки: эти таблицы только читают stocks.
Документы не удаляются, а аннулируются, поэтому мягкого удаления нет.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntPkMixin, PublicUuidMixin, TimestampMixin
from app.db.types import (
    LEN_CODE,
    LEN_EXTERNAL_ID,
    LEN_NAME,
    LEN_SHORT_NAME,
    LEN_STATUS,
    LEN_UNIT,
    enum_check,
    qty_type,
)
from app.modules.warehouse.enums import WarehouseDocumentStatus


class WarehouseDocument(Base, IntPkMixin, PublicUuidMixin, TimestampMixin):
    """Сводный складской документ — единственный документ списания для 1С.

    uuid — идентификатор документа в обмене с 1С. number — человекочитаемый
    номер вида WH-2026-000123 из warehouse_document_number_seq, он никогда
    не выдаётся повторно, даже после аннулирования.

    Состояние на складе (status) и то, что знает 1С (exported_at,
    write_off_confirmed_at, cancel_exported_at), хранятся раздельно.
    """

    __tablename__ = "warehouse_documents"

    number: Mapped[str] = mapped_column(String(24), nullable=False)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("requests.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(LEN_STATUS), server_default=WarehouseDocumentStatus.CREATED.value, nullable=False
    )
    # Всего упаковок в документе — для подписи «3/5».
    package_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # Проверка остатка — снимок без резервирования, поэтому на документе
    # хранится момент расчёта и самая старая дата данных 1С среди строк.
    stock_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stock_data_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Ключ приходит из админки при создании разбиения; request_hash —
    # SHA-256 тела запроса, чтобы отличить повтор от чужого запроса
    # с тем же ключом.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), default=None)
    request_hash: Mapped[str | None] = mapped_column(String(64), default=None)

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    packed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    packed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    cancelled_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text, default=None)

    # ------------------------------------------------------------- обмен с 1С
    # external_id — номер или GUID документа в 1С, приходит с подтверждением
    # чтения. Метки времени ставятся по одному разу.
    external_id: Mapped[str | None] = mapped_column(String(LEN_EXTERNAL_ID), default=None)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    write_off_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    cancel_exported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    __table_args__ = (
        enum_check("status", WarehouseDocumentStatus, "status"),
        CheckConstraint("package_count > 0", name="package_count_positive"),
        CheckConstraint("status <> 'PACKED' OR packed_at IS NOT NULL", name="packed_has_time"),
        CheckConstraint(
            "(status = 'CANCELLED') = (cancelled_at IS NOT NULL)", name="cancelled_iff_time"
        ),
        # 1С никогда не видит документ, который не был упакован.
        CheckConstraint("exported_at IS NULL OR packed_at IS NOT NULL", name="export_after_pack"),
        CheckConstraint(
            "write_off_confirmed_at IS NULL OR exported_at IS NOT NULL",
            name="write_off_after_export",
        ),
        CheckConstraint(
            "cancel_exported_at IS NULL OR (status = 'CANCELLED' AND exported_at IS NOT NULL)",
            name="cancel_export_valid",
        ),
        Index("uq_warehouse_documents_number", "number", unique=True),
        # Не больше одного действующего документа на заявку. Проверка в коде
        # не защищает от гонки двух одновременных разбиений — защищает БД.
        Index(
            "uq_warehouse_documents_active_request",
            "request_id",
            unique=True,
            postgresql_where=text("status IN ('CREATED', 'PACKED')"),
        ),
        Index(
            "uq_warehouse_documents_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "uq_warehouse_documents_external_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        # История документов заявки, включая аннулированные.
        Index("ix_warehouse_documents_request_id", "request_id"),
        # Список документов в админке: новые сверху.
        Index("ix_warehouse_documents_status_created", "status", text("created_at DESC")),
        # Выборки 1С: что списать и какие аннулирования прочитать.
        Index(
            "ix_warehouse_documents_onec_write_off_pending",
            "packed_at",
            postgresql_where=text("status = 'PACKED' AND exported_at IS NULL"),
        ),
        Index(
            "ix_warehouse_documents_onec_cancel_pending",
            "cancelled_at",
            postgresql_where=text(
                "status = 'CANCELLED' AND exported_at IS NOT NULL AND cancel_exported_at IS NULL"
            ),
        ),
    )


class WarehouseDocumentLine(Base, IntPkMixin):
    """Строка сводного документа — одна позиция заявки целиком.

    Название, артикул, единица и цвет — снапшот из позиции заявки, как и
    там: документ обязан показывать то, что собирал склад, даже если
    товар потом переименуют. Цен в строке нет.

    available_at_check — доступный остаток товара на момент проверки,
    до этого документа. Может быть отрицательным, если резерв 1С больше
    остатка.
    """

    __tablename__ = "warehouse_document_lines"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse_documents.id", ondelete="CASCADE"), nullable=False
    )
    request_item_id: Mapped[int] = mapped_column(
        ForeignKey("request_items.id", ondelete="RESTRICT"), nullable=False
    )
    # В отличие от позиции заявки, товар обязателен: без него нечего
    # сверять с остатком. Непривязанная позиция блокирует упаковку.
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )

    sku_snapshot: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    name_snapshot: Mapped[str] = mapped_column(String(LEN_NAME), nullable=False)
    unit_snapshot: Mapped[str] = mapped_column(String(LEN_UNIT), nullable=False)
    color_name_snapshot: Mapped[str | None] = mapped_column(String(LEN_SHORT_NAME), default=None)

    quantity: Mapped[Decimal] = mapped_column(qty_type(), nullable=False)
    available_at_check: Mapped[Decimal] = mapped_column(qty_type(), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index(
            "uq_warehouse_document_lines_document_item",
            "document_id",
            "request_item_id",
            unique=True,
        ),
        # Расчёт доступного остатка ищет строки по товару.
        Index("ix_warehouse_document_lines_product_id", "product_id"),
    )


class WarehousePackage(Base, IntPkMixin, PublicUuidMixin):
    """Упаковка (коробка): один товар в одной коробке.

    uuid — токен QR-кода. Он случайный, поэтому публичную страницу
    проверки нельзя перебрать по номеру заявки и упаковки.

    Подпись «WH-2026-000123-3/5» не хранится, а собирается из номера
    документа, seq и package_count — так она не может с ними разойтись.
    """

    __tablename__ = "warehouse_packages"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse_documents.id", ondelete="CASCADE"), nullable=False
    )
    line_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse_document_lines.id", ondelete="CASCADE"), nullable=False
    )
    # Номер упаковки внутри документа: 1…N.
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(qty_type(), nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        Index("uq_warehouse_packages_document_seq", "document_id", "seq", unique=True),
        Index("ix_warehouse_packages_line_id", "line_id"),
    )
