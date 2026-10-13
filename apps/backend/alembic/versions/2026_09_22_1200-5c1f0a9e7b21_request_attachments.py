"""Быстрый заказ: файлы, приложенные клиентом к заявке.

Одна новая таблица, существующие не меняются. Новые источники заявки
(QUICK_CALLBACK, ONE_CLICK, SKU_LIST, QUOTE_REQUEST) миграции не требуют:
у колонки requests.source нет CHECK-ограничения.

request_attachments — спецификация или ТЗ к запросу КП. Содержимое
хранится в самой БД (BYTEA), а не в R2: документ клиента привязан к его
контактам и может содержать ПДн, а ПДн живут только в PostgreSQL на
территории РК.

Revision ID: 5c1f0a9e7b21
Revises: d85586f23305
Create Date: 2026-09-22 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5c1f0a9e7b21"
down_revision: str | None = "d85586f23305"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "request_attachments",
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_request_attachments_size_positive")),
        sa.CheckConstraint(
            "length(filename) > 0", name=op.f("ck_request_attachments_filename_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name=op.f("fk_request_attachments_request_id_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_attachments")),
    )
    op.create_index(
        "ix_request_attachments_request_id", "request_attachments", ["request_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_request_attachments_request_id", table_name="request_attachments")
    op.drop_table("request_attachments")
