"""media metadata and content sections

Этап 5D: медиатека и структурированный CMS.

media_files — два nullable-поля, заполняются только новыми записями:
  * original_filename — имя файла у пользователя, только для показа
    в медиатеке (в ключ объекта не попадает);
  * failure_reason — код причины для статуса FAILED.
Бинарные данные по-прежнему не хранятся в PostgreSQL.

content_sections — одна строка на раздел сайта (главная, контакты,
доставка, FAQ, реквизиты, общие настройки). Форма данных задана
Pydantic-схемами раздела; набор ключей ограничен CHECK.

Revision ID: 8b39d8bdc896
Revises: 02b0358003e8
Create Date: 2026-09-11 09:47:19.152219+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '8b39d8bdc896'
down_revision: str | None = '02b0358003e8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('content_sections',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('updated_by_id', sa.BigInteger(), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("key IN ('home', 'contacts', 'delivery', 'faq', 'requisites', 'settings')", name=op.f('ck_content_sections_key')),
    sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], name=op.f('fk_content_sections_updated_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_content_sections'))
    )
    op.create_index('uq_content_sections_key', 'content_sections', ['key'], unique=True)
    op.add_column('media_files', sa.Column('original_filename', sa.String(length=255), nullable=True))
    op.add_column('media_files', sa.Column('failure_reason', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('media_files', 'failure_reason')
    op.drop_column('media_files', 'original_filename')
    op.drop_index('uq_content_sections_key', table_name='content_sections')
    op.drop_table('content_sections')
