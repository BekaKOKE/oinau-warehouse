"""Alembic environment.

Использует async-движок приложения и метаданные из app.db.base.

DSN в `alembic.ini` намеренно НЕ задан: он берётся из настроек
приложения (.env), чтобы не было двух источников правды и секретов
в файле под Git. Сам `alembic.ini` держим в ASCII — Alembic читает
его кодировкой системной локали, и кириллица в нём ломает
`alembic upgrade` на Windows с cp1251/cp1252.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.db.base import Base

# Импорт моделей для autogenerate добавляется на этапе 3 в app/db/base.py

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _include_object(_object, name, type_, _reflected, _compare_to) -> bool:
    """Служебные таблицы вне управления Alembic."""
    return not (type_ == "table" and name in {"spatial_ref_sys"})


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
