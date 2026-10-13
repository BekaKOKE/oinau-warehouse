"""Журнал аудита.

НУЖЕН УЖЕ СЕЙЧАС — по трём причинам.

1. История не восстанавливается задним числом. Включить аудит через год
   означает потерять год данных. Стоимость сейчас — одна таблица.
2. Каталог правят несколько человек, плюс Excel-импорт, плюс в будущем
   1С. Вопрос "кто и когда поставил эту цену" возникнет неизбежно,
   а без журнала ответа на него не существует.
3. Заявки — коммерческие документы. Смена статуса и переназначение
   менеджера должны быть прослеживаемы.

Модель намеренно минимальная: одна таблица, JSONB-диф, без версионирования
сущностей, без восстановления состояния на момент времени и без
отдельного движка аудита. Полноценная event-sourcing система здесь была бы
на порядок дороже пользы.

Что журналируется (решается в сервисном слое, этап 5):
цены, остатки, товары и категории, заявки, пользователи и роли.
Чтение НЕ журналируется — это удвоило бы объём таблицы без пользы.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntPkMixin
from app.db.types import LEN_CODE, LEN_STATUS


class AuditLog(Base, IntPkMixin):
    """Запись об изменении данных.

    entity_type + entity_id — полиморфная ссылка без внешнего ключа.
    FK здесь невозможен (записи ссылаются на разные таблицы) и вреден:
    журнал должен пережить удаление объекта, о котором рассказывает.

    changes хранит только изменившиеся поля:
        {"price": {"old": "3500.00", "new": "3200.00"}}
    Полные снимки объектов раздули бы таблицу в разы без практической
    пользы — при разборе инцидента интересна дельта.
    """

    __tablename__ = "audit_log"

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # Действия могут выполняться не человеком: импорт, будущий обмен с 1С,
    # системная задача. Тогда user_id пуст, а actor описан здесь.
    actor: Mapped[str] = mapped_column(String(LEN_STATUS), server_default="user", nullable=False)

    action: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, default=None)

    changes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    ip_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    request_id: Mapped[str | None] = mapped_column(String(64), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        # Основной сценарий чтения: "вся история этого товара"
        Index("ix_audit_log_entity", "entity_type", "entity_id", text("created_at DESC")),
        Index("ix_audit_log_user_created", "user_id", text("created_at DESC")),
        Index("ix_audit_log_created_at", text("created_at DESC")),
    )
