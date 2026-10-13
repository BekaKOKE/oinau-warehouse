"""Цвета товаров: справочник, остатки и надбавки по цветам, цвет в заявке.

* `colors` — общий справочник цветов (название и образец для витрины).
  Заполняется базовой палитрой: её правят в админке.
* `product_colors` — цвета товара: остаток и надбавка к цене по цвету.
* `request_items.color_code_snapshot` / `color_name_snapshot` — цвет
  позиции заявки. Снапшот, как и остальные поля позиции: переименование
  или отключение цвета не меняет уже отправленную заявку. NULL — цвет
  не выбран (товар без цветов или старая заявка).

Остатки по складам (`stocks`) не меняются.

Revision ID: e7a2b9c4d150
Revises: c4d7e9a1f203
Create Date: 2026-10-05 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a2b9c4d150"
down_revision: str | None = "c4d7e9a1f203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Базовая палитра: цвета канатов и пластика для детских площадок.
_PALETTE = [
    ("black", "Чёрный", "#1f1f1f"),
    ("white", "Белый", "#ffffff"),
    ("grey", "Серый", "#8c8c8c"),
    ("red", "Красный", "#d32f2f"),
    ("orange", "Оранжевый", "#f57c00"),
    ("yellow", "Жёлтый", "#fbc02d"),
    ("green", "Зелёный", "#388e3c"),
    ("blue", "Синий", "#1976d2"),
    ("brown", "Коричневый", "#795548"),
    ("beige", "Бежевый", "#d7c4a3"),
]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def upgrade() -> None:
    colors = op.create_table(
        "colors",
        sa.Column("code", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("hex", sa.String(length=7), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("hex ~ '^#[0-9a-f]{6}$'", name=op.f("ck_colors_hex_format")),
        sa.CheckConstraint("length(name) > 0", name=op.f("ck_colors_name_not_blank")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_colors")),
    )
    op.create_index("uq_colors_code", "colors", ["code"], unique=True)

    op.create_table(
        "product_colors",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("color_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), server_default="0", nullable=False),
        sa.Column("price_delta", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        *_timestamps(),
        sa.CheckConstraint("quantity >= 0", name=op.f("ck_product_colors_quantity_non_negative")),
        sa.CheckConstraint(
            "price_delta >= 0", name=op.f("ck_product_colors_price_delta_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_colors_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["color_id"],
            ["colors.id"],
            name=op.f("fk_product_colors_color_id_colors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_colors")),
    )
    op.create_index(
        "uq_product_colors_product_id_color_id",
        "product_colors",
        ["product_id", "color_id"],
        unique=True,
    )
    op.create_index("ix_product_colors_color_id", "product_colors", ["color_id"], unique=False)

    op.add_column(
        "request_items", sa.Column("color_code_snapshot", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "request_items", sa.Column("color_name_snapshot", sa.String(length=255), nullable=True)
    )

    op.bulk_insert(
        colors,
        [
            {"code": code, "name": name, "hex": hex_value, "sort_order": index * 10}
            for index, (code, name, hex_value) in enumerate(_PALETTE)
        ],
    )


def downgrade() -> None:
    op.drop_column("request_items", "color_name_snapshot")
    op.drop_column("request_items", "color_code_snapshot")
    op.drop_index("ix_product_colors_color_id", table_name="product_colors")
    op.drop_index("uq_product_colors_product_id_color_id", table_name="product_colors")
    op.drop_table("product_colors")
    op.drop_index("uq_colors_code", table_name="colors")
    op.drop_table("colors")
