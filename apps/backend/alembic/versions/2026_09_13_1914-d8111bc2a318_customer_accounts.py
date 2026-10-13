"""customer accounts

Этап 7: B2B-кабинет клиентов.

customers               — учётные записи клиентов (отдельно от users:
                          другие политики, жизненный цикл и доступ)
customer_refresh_tokens — сессии клиентов с ротацией и цепочками (family_id)
customer_action_tokens  — одноразовые токены подтверждения email и сброса
                          пароля (хранится только SHA-256)
customer_favorites      — избранное, уникально по (клиент, товар)
customer_projects       — проекты клиента; customer_project_items — позиции
                          со снапшотом артикула и названия
customer_notifications  — уведомления в кабинете (основа будущих каналов)
requests.customer_id    — заявка из кабинета; requests.project_id — связь
                          с проектом. Обе колонки необязательны, SET NULL.

Revision ID: d8111bc2a318
Revises: 9dba1f2533c1
Create Date: 2026-09-13 19:14:38.362516+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'd8111bc2a318'
down_revision: str | None = '9dba1f2533c1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('customers',
    sa.Column('email', postgresql.CITEXT(), nullable=False),
    sa.Column('password_hash', sa.String(length=128), nullable=False),
    sa.Column('contact_name', sa.String(length=255), nullable=False),
    sa.Column('company_name', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=False),
    sa.Column('region_id', sa.BigInteger(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_login_count', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('length(contact_name) > 0', name=op.f('ck_customers_contact_name_not_blank')),
    sa.CheckConstraint('length(phone) >= 5', name=op.f('ck_customers_phone_min_length')),
    sa.ForeignKeyConstraint(['region_id'], ['regions.id'], name=op.f('fk_customers_region_id_regions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customers')),
    sa.UniqueConstraint('uuid', name=op.f('uq_customers_uuid'))
    )
    op.create_index('ix_customers_region_id', 'customers', ['region_id'], unique=False)
    op.create_index('uq_customers_email', 'customers', ['email'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('customer_action_tokens',
    sa.Column('customer_id', sa.BigInteger(), nullable=False),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('token_hash', sa.String(length=128), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ip_hash', sa.String(length=64), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.CheckConstraint("purpose IN ('EMAIL_VERIFICATION', 'PASSWORD_RESET')", name=op.f('ck_customer_action_tokens_purpose')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_customer_action_tokens_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_action_tokens'))
    )
    op.create_index('ix_customer_action_tokens_customer_purpose', 'customer_action_tokens', ['customer_id', 'purpose'], unique=False)
    op.create_index('uq_customer_action_tokens_token_hash', 'customer_action_tokens', ['token_hash'], unique=True)
    op.create_table('customer_favorites',
    sa.Column('customer_id', sa.BigInteger(), nullable=False),
    sa.Column('product_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_customer_favorites_customer_id_customers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_customer_favorites_product_id_products'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_favorites'))
    )
    op.create_index('ix_customer_favorites_customer_created', 'customer_favorites', ['customer_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('uq_customer_favorites_customer_product', 'customer_favorites', ['customer_id', 'product_id'], unique=True)
    op.create_table('customer_notifications',
    sa.Column('customer_id', sa.BigInteger(), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.CheckConstraint("type IN ('REQUEST_STATUS_CHANGED', 'REQUEST_COMMENT_ADDED', 'ACCOUNT', 'SYSTEM')", name=op.f('ck_customer_notifications_type')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_customer_notifications_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_notifications')),
    sa.UniqueConstraint('uuid', name=op.f('uq_customer_notifications_uuid'))
    )
    op.create_index('ix_customer_notifications_customer_created', 'customer_notifications', ['customer_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('ix_customer_notifications_unread', 'customer_notifications', ['customer_id'], unique=False, postgresql_where=sa.text('read_at IS NULL'))
    op.create_table('customer_projects',
    sa.Column('customer_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('region_id', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.String(length=32), server_default='PLANNING', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('PLANNING', 'ACTIVE', 'ON_HOLD', 'COMPLETED', 'ARCHIVED')", name=op.f('ck_customer_projects_status')),
    sa.CheckConstraint('length(name) > 0', name=op.f('ck_customer_projects_name_not_blank')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_customer_projects_customer_id_customers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['region_id'], ['regions.id'], name=op.f('fk_customer_projects_region_id_regions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_projects')),
    sa.UniqueConstraint('uuid', name=op.f('uq_customer_projects_uuid'))
    )
    op.create_index('ix_customer_projects_customer_created', 'customer_projects', ['customer_id', sa.literal_column('created_at DESC')], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('customer_refresh_tokens',
    sa.Column('customer_id', sa.BigInteger(), nullable=False),
    sa.Column('token_hash', sa.String(length=128), nullable=False),
    sa.Column('family_id', sa.UUID(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('ip_hash', sa.String(length=64), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_customer_refresh_tokens_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_refresh_tokens'))
    )
    op.create_index('ix_customer_refresh_tokens_customer_id', 'customer_refresh_tokens', ['customer_id'], unique=False)
    op.create_index('ix_customer_refresh_tokens_family_id', 'customer_refresh_tokens', ['family_id'], unique=False)
    op.create_index('uq_customer_refresh_tokens_token_hash', 'customer_refresh_tokens', ['token_hash'], unique=True)
    op.create_table('customer_project_items',
    sa.Column('project_id', sa.BigInteger(), nullable=False),
    sa.Column('product_id', sa.BigInteger(), nullable=True),
    sa.Column('sku_snapshot', sa.String(length=64), nullable=False),
    sa.Column('name_snapshot', sa.String(length=500), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantity IS NULL OR quantity > 0', name=op.f('ck_customer_project_items_quantity_positive')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_customer_project_items_product_id_products'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['customer_projects.id'], name=op.f('fk_customer_project_items_project_id_customer_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_project_items'))
    )
    op.create_index('uq_customer_project_items_project_sku', 'customer_project_items', ['project_id', 'sku_snapshot'], unique=True)
    op.add_column('requests', sa.Column('customer_id', sa.BigInteger(), nullable=True))
    op.add_column('requests', sa.Column('project_id', sa.BigInteger(), nullable=True))
    op.create_index('ix_requests_customer_created', 'requests', ['customer_id', sa.literal_column('created_at DESC')], unique=False, postgresql_where=sa.text('customer_id IS NOT NULL'))
    op.create_index('ix_requests_project_id', 'requests', ['project_id'], unique=False, postgresql_where=sa.text('project_id IS NOT NULL'))
    op.create_foreign_key(op.f('fk_requests_customer_id_customers'), 'requests', 'customers', ['customer_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_requests_project_id_customer_projects'), 'requests', 'customer_projects', ['project_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(op.f('fk_requests_project_id_customer_projects'), 'requests', type_='foreignkey')
    op.drop_constraint(op.f('fk_requests_customer_id_customers'), 'requests', type_='foreignkey')
    op.drop_index('ix_requests_project_id', table_name='requests', postgresql_where=sa.text('project_id IS NOT NULL'))
    op.drop_index('ix_requests_customer_created', table_name='requests', postgresql_where=sa.text('customer_id IS NOT NULL'))
    op.drop_column('requests', 'project_id')
    op.drop_column('requests', 'customer_id')
    op.drop_index('uq_customer_project_items_project_sku', table_name='customer_project_items')
    op.drop_table('customer_project_items')
    op.drop_index('uq_customer_refresh_tokens_token_hash', table_name='customer_refresh_tokens')
    op.drop_index('ix_customer_refresh_tokens_family_id', table_name='customer_refresh_tokens')
    op.drop_index('ix_customer_refresh_tokens_customer_id', table_name='customer_refresh_tokens')
    op.drop_table('customer_refresh_tokens')
    op.drop_index('ix_customer_projects_customer_created', table_name='customer_projects', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('customer_projects')
    op.drop_index('ix_customer_notifications_unread', table_name='customer_notifications', postgresql_where=sa.text('read_at IS NULL'))
    op.drop_index('ix_customer_notifications_customer_created', table_name='customer_notifications')
    op.drop_table('customer_notifications')
    op.drop_index('uq_customer_favorites_customer_product', table_name='customer_favorites')
    op.drop_index('ix_customer_favorites_customer_created', table_name='customer_favorites')
    op.drop_table('customer_favorites')
    op.drop_index('uq_customer_action_tokens_token_hash', table_name='customer_action_tokens')
    op.drop_index('ix_customer_action_tokens_customer_purpose', table_name='customer_action_tokens')
    op.drop_table('customer_action_tokens')
    op.drop_index('uq_customers_email', table_name='customers', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_customers_region_id', table_name='customers')
    op.drop_table('customers')
