"""Изображение категории.

Обложка раздела берётся из той же медиатеки, что и фото товаров:
отдельного хранилища у категорий нет, ссылка ведёт на `media_files`,
а публичный URL собирается общим правилом (`app/modules/media/urls.py`).

Колонка, а не таблица связи: обложка у категории одна, порядка и
alt-текста на несколько картинок здесь не нужно. Этим она отличается
от `product_images`, где изображений много.

ON DELETE RESTRICT — как у `product_images`: файл, который где-то
показывается, удалить нельзя. Проверка в сервисе медиатеки отвечает
на это понятным 409, а внешний ключ страхует от гонки.

Revision ID: b8e41d6ca207
Revises: a3f7c2d94e81
Create Date: 2026-09-22 17:30:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e41d6ca207"
down_revision: str | None = "a3f7c2d94e81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("image_media_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        op.f("fk_categories_image_media_id_media_files"),
        "categories",
        "media_files",
        ["image_media_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # Нужен проверке «файл занят» при удалении из медиатеки.
    op.create_index(
        "ix_categories_image_media_id",
        "categories",
        ["image_media_id"],
        unique=False,
        postgresql_where=sa.text("image_media_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_categories_image_media_id", table_name="categories")
    op.drop_constraint(
        op.f("fk_categories_image_media_id_media_files"), "categories", type_="foreignkey"
    )
    op.drop_column("categories", "image_media_id")
