"""Очередь исходящих уведомлений (outbox).

ЗАЧЕМ ТАБЛИЦА, А НЕ ПРЯМОЙ ВЫЗОВ ОЧЕРЕДИ.

Уведомление нельзя отправлять внутри транзакции бизнес-операции:
внешний вызов внутри транзакции держит блокировки на время сетевого
таймаута, а откат транзакции уже не отменит отправленное письмо.
Постановка в Redis сразу после коммита решает первую проблему, но не
вторую: если процесс упадёт между коммитом заявки и enqueue, событие
исчезнет молча, и никто не узнает, что заявка пришла.

Поэтому событие пишется строкой в ту же транзакцию, что и заявка.
Коммит заявки = коммит намерения отправить. Дальше воркер забирает
запись, отправляет и отмечает результат. Redis остаётся ускорителем
(разбудить воркер сразу), но перестаёт быть носителем правды:
периодический проход по таблице подберёт всё, что Redis потерял.

Содержимое письма не хранится — хранится `payload`, из которого
сообщение собирается при отправке. Так изменение шаблона применяется
и к ещё не отправленным событиям, а персональные данные не дублируются
в базе лишний раз.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntPkMixin, PublicUuidMixin, TimestampMixin
from app.db.types import LEN_CODE, LEN_SHORT_NAME, LEN_STATUS, enum_check
from app.modules.notifications.enums import NotificationChannel, OutboxStatus

# Ключ защиты от дублей: «событие + канал + получатель + объект».
LEN_DEDUP_KEY = 200
# Текст последней ошибки. Длиннее в журнале не нужно, а поле не должно
# расти бесконтрольно от чужих сообщений.
LEN_ERROR = 500


class NotificationOutbox(Base, IntPkMixin, PublicUuidMixin, TimestampMixin):
    __tablename__ = "notification_outbox"

    event: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    channel: Mapped[str] = mapped_column(String(LEN_STATUS), nullable=False)
    # Адрес получателя: email или chat_id Telegram.
    recipient: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)

    status: Mapped[str] = mapped_column(
        String(LEN_STATUS), server_default=OutboxStatus.PENDING.value, nullable=False
    )

    # Всё, что нужно шаблону: номер заявки, состав, ссылка, токен.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )

    # Уникальный ключ события. Повторный вызов с тем же ключом не создаёт
    # второй записи — защита от двойной отправки при ретрае обработчика.
    dedup_key: Mapped[str | None] = mapped_column(String(LEN_DEDUP_KEY), default=None)

    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0", nullable=False)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="5", nullable=False)
    # Когда запись можно брать в работу: сдвигается при экспоненциальном
    # откате. Индекс по (status, available_at) — основной запрос воркера.
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    last_error: Mapped[str | None] = mapped_column(String(LEN_ERROR), default=None)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        enum_check("status", OutboxStatus, "status"),
        enum_check("channel", NotificationChannel, "channel"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        # Дубль невозможен физически: гонка двух обработчиков одного
        # события упрётся в ограничение, а не создаст второе письмо.
        Index(
            "uq_notification_outbox_dedup_key",
            "dedup_key",
            unique=True,
            postgresql_where=text("dedup_key IS NOT NULL"),
        ),
        # Основная выборка воркера: что готово к отправке прямо сейчас.
        Index(
            "ix_notification_outbox_due",
            "available_at",
            postgresql_where=text("status IN ('pending', 'sending')"),
        ),
        Index("ix_notification_outbox_status_created", "status", text("created_at DESC")),
    )


class SyncLog(Base, IntPkMixin, PublicUuidMixin):
    """Журнал обменов с внешней системой.

    Отдельно от audit_log: там — «что изменилось в бизнес-объекте»,
    здесь — «как прошёл обмен». Смешивать их означало бы утопить
    историю товара в технических записях о каждом пакете остатков.

    Само содержимое пакета не хранится: только контрольная сумма.
    Пакет может содержать весь прайс-лист, а хранить его копию в базе
    ради разбора инцидента слишком дорого.
    """

    __tablename__ = "sync_log"

    direction: Mapped[str] = mapped_column(String(LEN_STATUS), nullable=False)
    entity: Mapped[str] = mapped_column(String(LEN_CODE), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(LEN_SHORT_NAME), nullable=False)
    status: Mapped[str] = mapped_column(String(LEN_STATUS), nullable=False)

    # Кто прислал пакет. Без FK: журнал переживает удаление ключа.
    api_key_name: Mapped[str | None] = mapped_column(String(LEN_SHORT_NAME), default=None)

    received: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    created: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    updated: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    failed: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    duration_ms: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    error: Mapped[str | None] = mapped_column(String(LEN_ERROR), default=None)

    # SHA-256 тела запроса: повтор того же пакета узнаётся без хранения
    # самого пакета и отдаёт прежний результат вместо повторной записи.
    payload_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    request_id: Mapped[str | None] = mapped_column(String(LEN_CODE), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("direction IN ('inbound', 'outbound')", name="direction"),
        CheckConstraint("status IN ('success', 'partial', 'failed')", name="status"),
        Index("ix_sync_log_created_at", text("created_at DESC")),
        Index("ix_sync_log_entity_created", "entity", text("created_at DESC")),
        # Поиск повтора пакета: только успешные и только свежие.
        Index(
            "ix_sync_log_payload_hash",
            "payload_hash",
            "entity",
            postgresql_where=text("payload_hash IS NOT NULL"),
        ),
    )
