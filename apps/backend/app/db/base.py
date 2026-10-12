"""Базовый класс моделей и общие миксины.

Naming convention критична: без неё Alembic генерирует автоимена ограничений,
и downgrade-миграции перестают работать на другой БД.
"""

from __future__ import annotations

import uuid as uuid_pkg
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, MetaData, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import LEN_EXTERNAL_ID

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IntPkMixin:
    """Внутренний числовой первичный ключ.

    BIGINT, а не INT: перевод последовательности на 64 бита в работающей
    системе — дорогая операция, а разница в размере на наших объёмах
    несущественна.
    """

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class PublicUuidMixin:
    """Публичный идентификатор для сущностей, чей ID утекает наружу.

    Автоинкремент наружу не отдаём: он раскрывает объёмы бизнеса
    и позволяет перебирать чужие объекты.
    """

    uuid: Mapped[uuid_pkg.UUID] = mapped_column(
        UUID(as_uuid=True),
        server_default=func.gen_random_uuid(),
        unique=True,
        nullable=False,
    )


class TimestampMixin:
    """created_at / updated_at для всех сущностей. Всегда TIMESTAMPTZ, всегда UTC."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Мягкое удаление. Жёсткий DELETE ломает историю заявок и синхронизацию с 1С."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ExternalSyncMixin:
    """Поля для будущего обмена с внешней учётной системой (1С).

    Сама интеграция не реализуется. Но добавить эти поля в пустую таблицу —
    минута, а сопоставить несколько тысяч товаров с 1С задним числом —
    недели ручной работы.

    external_id — GUID объекта во внешней системе.
    sync_source — кто последним записал строку: manual | excel | 1c.
    synced_at   — время последней успешной синхронизации.
    """

    external_id: Mapped[str | None] = mapped_column(String(LEN_EXTERNAL_ID), default=None)
    sync_source: Mapped[str] = mapped_column(String(16), server_default="manual", nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


# ---------------------------------------------------------------------------
# Регистрация моделей для Alembic autogenerate.
# Без этих импортов metadata пуста и autogenerate предложит удалить все таблицы.
# ---------------------------------------------------------------------------
from app.modules.audit import models as audit_models  # noqa: E402,F401
from app.modules.catalog import models as catalog_models  # noqa: E402,F401
from app.modules.colors import models as color_models  # noqa: E402,F401
from app.modules.content import models as content_models  # noqa: E402,F401
from app.modules.customers import models as customer_models  # noqa: E402,F401
from app.modules.geo import models as geo_models  # noqa: E402,F401
from app.modules.imports import models as import_models  # noqa: E402,F401
from app.modules.integration import models as integration_models  # noqa: E402,F401
from app.modules.inventory import models as inventory_models  # noqa: E402,F401
from app.modules.media import models as media_models  # noqa: E402,F401
from app.modules.notifications import models as notification_models  # noqa: E402,F401
from app.modules.pricing import models as pricing_models  # noqa: E402,F401
from app.modules.requests import models as request_models  # noqa: E402,F401
from app.modules.users import models as user_models  # noqa: E402,F401
from app.modules.warehouse import models as warehouse_models  # noqa: E402,F401
