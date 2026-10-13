"""import jobs

Этап 5E: Excel-импорт каталога.

import_jobs — история импортов: кто и когда загрузил файл, итог
предпросмотра, кто подтвердил, сколько товаров создано и обновлено,
ошибки (JSONB, не больше 500 записей). Сам XLSX не хранится — только
имя, размер и SHA-256: хеш связывает подтверждение с предпросмотром.

Отдельной таблицы import_job_errors нет: ошибки читаются только целиком
вместе с импортом.

Revision ID: 9dba1f2533c1
Revises: 8b39d8bdc896
Create Date: 2026-09-11 13:19:05.585382+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '9dba1f2533c1'
down_revision: str | None = '8b39d8bdc896'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('import_jobs',
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('file_size', sa.BigInteger(), nullable=False),
    sa.Column('file_sha256', sa.String(length=64), nullable=False),
    sa.Column('rows_total', sa.Integer(), server_default='0', nullable=False),
    sa.Column('products_created', sa.Integer(), server_default='0', nullable=False),
    sa.Column('products_updated', sa.Integer(), server_default='0', nullable=False),
    sa.Column('products_unchanged', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('warning_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('errors', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('warnings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('created_by_id', sa.BigInteger(), nullable=True),
    sa.Column('committed_by_id', sa.BigInteger(), nullable=True),
    sa.Column('committed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_code', sa.String(length=64), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('catalog')", name=op.f('ck_import_jobs_kind')),
    sa.CheckConstraint("status IN ('VALID', 'INVALID', 'COMMITTED', 'FAILED')", name=op.f('ck_import_jobs_status')),
    sa.CheckConstraint('file_size > 0', name=op.f('ck_import_jobs_file_size_positive')),
    sa.ForeignKeyConstraint(['committed_by_id'], ['users.id'], name=op.f('fk_import_jobs_committed_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_import_jobs_created_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_jobs')),
    sa.UniqueConstraint('uuid', name=op.f('uq_import_jobs_uuid'))
    )
    op.create_index('ix_import_jobs_kind_created', 'import_jobs', ['kind', sa.literal_column('created_at DESC')], unique=False)


def downgrade() -> None:
    op.drop_index('ix_import_jobs_kind_created', table_name='import_jobs')
    op.drop_table('import_jobs')
