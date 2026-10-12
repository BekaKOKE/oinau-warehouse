"""Складская упаковка: документы, строки, упаковки и роль кладовщика.

* `users.role` — ограничение `ck_users_role` пересоздаётся с новой ролью
  `WAREHOUSE`. Прежние пять ролей остаются.
* `stocks.reported_at` — когда 1С в последний раз упомянула строку в
  выгрузке остатков, даже если числа не изменились. Для строк из 1С
  заполняется значением `synced_at`. Сами остатки не меняются.
* `warehouse_document_number_seq` — номера складских документов
  (WH-2026-000123). Отдельная последовательность: номер не выдаётся
  повторно даже после аннулирования документа.
* `warehouse_documents` — сводный документ заявки, единственный документ
  списания для 1С.
* `warehouse_document_lines` — строки документа, снапшот позиций заявки.
* `warehouse_packages` — упаковки с токеном QR-кода.

Миграция только добавляет: существующие таблицы и колонки не удаляются
и не переименовываются.

ОТКАТ УНИЧТОЖАЕТ ВСЕ СКЛАДСКИЕ ДОКУМЕНТЫ: таблицы документов, строк и
упаковок удаляются вместе с данными. Откат отказывается работать, пока
в `users` есть хотя бы одна строка с ролью `WAREHOUSE` (включая
отключённых и удалённых сотрудников): старое ограничение `ck_users_role`
такую строку не пропустит, а молча менять людям роль миграция не должна.

Revision ID: e17c6f22c085
Revises: e7a2b9c4d150
Create Date: 2026-10-12 21:21:14.142223+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "e17c6f22c085"
down_revision: str | None = "e7a2b9c4d150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES_BEFORE = ("SUPERADMIN", "ADMIN", "MANAGER", "CONTENT_MANAGER", "VIEWER")
_ROLES_AFTER = (*_ROLES_BEFORE, "WAREHOUSE")


def _role_check(roles: Sequence[str]) -> str:
    values = ", ".join(f"'{role}'" for role in roles)
    return f"role IN ({values})"


def ensure_no_warehouse_users(connection: Connection) -> None:
    """Останавливает откат, пока в `users` есть роль `WAREHOUSE`.

    Считаются все строки, включая отключённых (`is_active = false`) и
    удалённых (`deleted_at`) сотрудников: CHECK проверяет каждую строку
    таблицы, а не только действующих.

    Соединение передаётся аргументом, чтобы проверку можно было вызвать
    из теста без запуска отката.
    """
    count = connection.execute(
        sa.text("SELECT count(*) FROM users WHERE role = 'WAREHOUSE'")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Откат миграции остановлен: в таблице users есть сотрудники с ролью "
            f"WAREHOUSE ({count}), считая отключённых и удалённых. Смените им роль "
            f"или удалите эти строки и повторите откат."
        )


def upgrade() -> None:
    # 1. Роль кладовщика.
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint(op.f("ck_users_role"), "users", _role_check(_ROLES_AFTER))

    # 2. Время последнего упоминания строки остатка в выгрузке 1С.
    op.add_column("stocks", sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE stocks SET reported_at = synced_at WHERE sync_source = '1c'")

    # 3. Номера складских документов.
    op.execute("CREATE SEQUENCE warehouse_document_number_seq START 1")

    # 4. Сводный документ.
    op.create_table(
        "warehouse_documents",
        sa.Column("number", sa.String(length=24), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("warehouse_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="CREATED", nullable=False),
        sa.Column("package_count", sa.SmallInteger(), nullable=False),
        sa.Column("stock_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stock_data_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column("packed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("packed_by_id", sa.BigInteger(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_id", sa.BigInteger(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("write_off_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('CREATED', 'PACKED', 'CANCELLED')",
            name=op.f("ck_warehouse_documents_status"),
        ),
        sa.CheckConstraint(
            "package_count > 0", name=op.f("ck_warehouse_documents_package_count_positive")
        ),
        sa.CheckConstraint(
            "status <> 'PACKED' OR packed_at IS NOT NULL",
            name=op.f("ck_warehouse_documents_packed_has_time"),
        ),
        sa.CheckConstraint(
            "(status = 'CANCELLED') = (cancelled_at IS NOT NULL)",
            name=op.f("ck_warehouse_documents_cancelled_iff_time"),
        ),
        sa.CheckConstraint(
            "exported_at IS NULL OR packed_at IS NOT NULL",
            name=op.f("ck_warehouse_documents_export_after_pack"),
        ),
        sa.CheckConstraint(
            "write_off_confirmed_at IS NULL OR exported_at IS NOT NULL",
            name=op.f("ck_warehouse_documents_write_off_after_export"),
        ),
        sa.CheckConstraint(
            "cancel_exported_at IS NULL OR (status = 'CANCELLED' AND exported_at IS NOT NULL)",
            name=op.f("ck_warehouse_documents_cancel_export_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name=op.f("fk_warehouse_documents_request_id_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name=op.f("fk_warehouse_documents_warehouse_id_warehouses"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_warehouse_documents_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["packed_by_id"],
            ["users.id"],
            name=op.f("fk_warehouse_documents_packed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by_id"],
            ["users.id"],
            name=op.f("fk_warehouse_documents_cancelled_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warehouse_documents")),
        sa.UniqueConstraint("uuid", name=op.f("uq_warehouse_documents_uuid")),
    )
    op.create_index(
        "uq_warehouse_documents_number", "warehouse_documents", ["number"], unique=True
    )
    op.create_index(
        "uq_warehouse_documents_active_request",
        "warehouse_documents",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('CREATED', 'PACKED')"),
    )
    op.create_index(
        "uq_warehouse_documents_idempotency_key",
        "warehouse_documents",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "uq_warehouse_documents_external_id",
        "warehouse_documents",
        ["external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index(
        "ix_warehouse_documents_request_id", "warehouse_documents", ["request_id"], unique=False
    )
    op.create_index(
        "ix_warehouse_documents_status_created",
        "warehouse_documents",
        ["status", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_warehouse_documents_onec_write_off_pending",
        "warehouse_documents",
        ["packed_at"],
        unique=False,
        postgresql_where=sa.text("status = 'PACKED' AND exported_at IS NULL"),
    )
    op.create_index(
        "ix_warehouse_documents_onec_cancel_pending",
        "warehouse_documents",
        ["cancelled_at"],
        unique=False,
        postgresql_where=sa.text(
            "status = 'CANCELLED' AND exported_at IS NOT NULL AND cancel_exported_at IS NULL"
        ),
    )

    # 5. Строки документа.
    op.create_table(
        "warehouse_document_lines",
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("request_item_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("sku_snapshot", sa.String(length=64), nullable=False),
        sa.Column("name_snapshot", sa.String(length=500), nullable=False),
        sa.Column("unit_snapshot", sa.String(length=16), nullable=False),
        sa.Column("color_name_snapshot", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("available_at_check", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "quantity > 0", name=op.f("ck_warehouse_document_lines_quantity_positive")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["warehouse_documents.id"],
            name=op.f("fk_warehouse_document_lines_document_id_warehouse_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_item_id"],
            ["request_items.id"],
            name=op.f("fk_warehouse_document_lines_request_item_id_request_items"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_warehouse_document_lines_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warehouse_document_lines")),
    )
    op.create_index(
        "uq_warehouse_document_lines_document_item",
        "warehouse_document_lines",
        ["document_id", "request_item_id"],
        unique=True,
    )
    op.create_index(
        "ix_warehouse_document_lines_product_id",
        "warehouse_document_lines",
        ["product_id"],
        unique=False,
    )

    # 6. Упаковки.
    op.create_table(
        "warehouse_packages",
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("line_id", sa.BigInteger(), nullable=False),
        sa.Column("seq", sa.SmallInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_warehouse_packages_quantity_positive")),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_warehouse_packages_seq_positive")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["warehouse_documents.id"],
            name=op.f("fk_warehouse_packages_document_id_warehouse_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["line_id"],
            ["warehouse_document_lines.id"],
            name=op.f("fk_warehouse_packages_line_id_warehouse_document_lines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warehouse_packages")),
        sa.UniqueConstraint("uuid", name=op.f("uq_warehouse_packages_uuid")),
    )
    op.create_index(
        "uq_warehouse_packages_document_seq",
        "warehouse_packages",
        ["document_id", "seq"],
        unique=True,
    )
    op.create_index(
        "ix_warehouse_packages_line_id", "warehouse_packages", ["line_id"], unique=False
    )


def downgrade() -> None:
    # Проверка идёт первой: до неё ничего не удаляется и не меняется.
    ensure_no_warehouse_users(op.get_bind())

    op.drop_index("ix_warehouse_packages_line_id", table_name="warehouse_packages")
    op.drop_index("uq_warehouse_packages_document_seq", table_name="warehouse_packages")
    op.drop_table("warehouse_packages")

    op.drop_index(
        "ix_warehouse_document_lines_product_id", table_name="warehouse_document_lines"
    )
    op.drop_index(
        "uq_warehouse_document_lines_document_item", table_name="warehouse_document_lines"
    )
    op.drop_table("warehouse_document_lines")

    op.drop_index("ix_warehouse_documents_onec_cancel_pending", table_name="warehouse_documents")
    op.drop_index(
        "ix_warehouse_documents_onec_write_off_pending", table_name="warehouse_documents"
    )
    op.drop_index("ix_warehouse_documents_status_created", table_name="warehouse_documents")
    op.drop_index("ix_warehouse_documents_request_id", table_name="warehouse_documents")
    op.drop_index("uq_warehouse_documents_external_id", table_name="warehouse_documents")
    op.drop_index("uq_warehouse_documents_idempotency_key", table_name="warehouse_documents")
    op.drop_index("uq_warehouse_documents_active_request", table_name="warehouse_documents")
    op.drop_index("uq_warehouse_documents_number", table_name="warehouse_documents")
    op.drop_table("warehouse_documents")

    op.execute("DROP SEQUENCE warehouse_document_number_seq")

    op.drop_column("stocks", "reported_at")

    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint(op.f("ck_users_role"), "users", _role_check(_ROLES_BEFORE))
