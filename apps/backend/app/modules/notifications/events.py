"""Бизнес-события → записи outbox.

Слой между доменом и доставкой. Сервис заявок не должен знать ни про
Telegram, ни про список деловых адресов: он вызывает одно событие,
а кому и куда — решается здесь, по настройкам.

Здесь же собирается payload. Правило: в деловой канал кладём то,
что нужно для работы с заявкой; клиенту — только то, что он и так
знает про свою заявку. Токены и внутренние идентификаторы в payload
не попадают, кроме одноразовой ссылки писем аутентификации.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.service import BaseService
from app.modules.notifications.enums import NotificationChannel, NotificationEvent
from app.modules.notifications.models import NotificationOutbox
from app.modules.notifications.service import NotificationService, build_dedup_key
from app.modules.requests.models import Request

# Время в уведомлениях — местное: сотрудник читает Telegram в Алматы,
# а не в UTC.
DISPLAY_TZ = ZoneInfo("Asia/Almaty")

# Позиции в payload деловых уведомлений. Полный состав — в карточке.
MAX_PAYLOAD_ITEMS = 20
# Комментарий в уведомлении обрезается: Telegram ограничивает сообщение
# 4096 символами, полный текст — в карточке заявки.
MAX_PAYLOAD_COMMENT = 1000

_STATUS_LABELS: dict[str, str] = {
    "NEW": "принята",
    "IN_PROGRESS": "в работе",
    "WAITING_CLIENT": "ожидает вашего ответа",
    "QUOTE_SENT": "отправлено коммерческое предложение",
    "APPROVED": "согласована",
    "COMPLETED": "выполнена",
    "CANCELLED": "отменена",
}


def _format_moment(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(DISPLAY_TZ).strftime("%d.%m.%Y %H:%M")


def request_payload(
    request: Request,
    *,
    region_name: str | None = None,
    attachments: Sequence[str] = (),
) -> dict[str, Any]:
    """Снимок заявки для делового уведомления.

    Берётся из снапшотов позиций, а не из живого каталога: уведомление
    должно описывать то, что отправил клиент.

    Название региона и имена файлов передаются явно: связи `region`
    и `attachments` ленивые, и их чтение здесь означало бы неожиданный
    запрос (в асинхронной сессии — прямую ошибку) внутри чужой транзакции.

    Комментарий клиента входит в payload: у обратного звонка и запроса
    КП он и есть суть заявки. Сам файл в уведомление не попадает —
    только имя; скачивают его из карточки в админке.
    """
    items = sorted(request.items, key=lambda item: (item.sort_order, item.id or 0))
    payload: dict[str, Any] = {
        "request_id": request.id,
        "number": request.number,
        "customer_name": request.customer_name,
        "company": request.company,
        "phone": request.phone,
        "email": request.email,
        "region": region_name,
        "source": request.source,
        "items_count": len(items),
        "items": [
            {
                "sku": item.sku_snapshot,
                "name": item.name_snapshot,
                "quantity": str(item.quantity),
                "unit": item.unit_snapshot,
                # Цвет — только у позиций с цветом.
                **({"color": item.color_name_snapshot} if item.color_name_snapshot else {}),
            }
            for item in items[:MAX_PAYLOAD_ITEMS]
        ],
        "total_estimate": str(request.total_estimate) if request.total_estimate else None,
        "currency": request.currency,
        "created_at": _format_moment(request.created_at),
    }
    # Необязательные ключи — только когда есть что сказать: обычная
    # заявка из корзины выглядит в уведомлении ровно как раньше.
    if request.comment:
        payload["comment"] = request.comment[:MAX_PAYLOAD_COMMENT]
    if attachments:
        payload["attachments"] = list(attachments)
    return payload


class NotificationEvents(BaseService):
    """Фасад событий. Ничего не отправляет и не коммитит."""

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        self.outbox = NotificationService(session)

    # ------------------------------------------------------------- заявки

    def request_created(
        self,
        request: Request,
        *,
        region_name: str | None = None,
        attachments: Sequence[str] = (),
    ) -> list[NotificationOutbox]:
        """Новая заявка — в Telegram и на деловую почту.

        Клиенту письмо здесь не отправляется: заявку оставляют и без
        регистрации, а подтверждение приёма он видит на сайте сразу.
        """
        payload = request_payload(request, region_name=region_name, attachments=attachments)
        subject_id = str(request.id)
        entries = self.outbox.enqueue_many(
            event=NotificationEvent.REQUEST_CREATED,
            channel=NotificationChannel.TELEGRAM,
            recipients=list(settings.TELEGRAM_CHAT_ID),
            payload=payload,
            subject_id=subject_id,
        )
        entries.extend(
            self.outbox.enqueue_many(
                event=NotificationEvent.REQUEST_CREATED,
                channel=NotificationChannel.EMAIL,
                recipients=list(settings.NOTIFY_EMAILS),
                payload=payload,
                subject_id=subject_id,
            )
        )
        return entries

    def request_status_changed(
        self, *, request: Request, email: str, status: str, customer_name: str | None = None
    ) -> list[NotificationOutbox]:
        """Смена статуса — письмо клиенту с подтверждённым адресом.

        Статус показывается словами клиента: внутренние SPAM и
        CANCELLED для него одно и то же — «отменена».
        """
        entry = self.outbox.enqueue(
            event=NotificationEvent.REQUEST_STATUS_CHANGED,
            channel=NotificationChannel.EMAIL,
            recipient=email,
            payload={
                "number": request.number,
                "status": status,
                "status_label": _STATUS_LABELS.get(status, "обновлён"),
                "customer_name": customer_name,
            },
            # Ключ включает статус: два разных перехода — два письма,
            # повтор одного и того же перехода — одно.
            dedup_key=build_dedup_key(
                NotificationEvent.REQUEST_STATUS_CHANGED.value,
                NotificationChannel.EMAIL.value,
                email,
                f"{request.id}:{status}",
            ),
        )
        return [entry] if entry is not None else []

    def request_comment_added(
        self,
        *,
        request: Request,
        email: str,
        comment_id: int,
        customer_name: str | None = None,
    ) -> list[NotificationOutbox]:
        """Видимый комментарий менеджера — письмо клиенту.

        Вызывать ТОЛЬКО для is_internal=False: внутренние заметки
        сотрудников клиенту не показываются нигде, включая почту.
        """
        entry = self.outbox.enqueue(
            event=NotificationEvent.REQUEST_COMMENT_ADDED,
            channel=NotificationChannel.EMAIL,
            recipient=email,
            payload={"number": request.number, "customer_name": customer_name},
            dedup_key=build_dedup_key(
                NotificationEvent.REQUEST_COMMENT_ADDED.value,
                NotificationChannel.EMAIL.value,
                email,
                f"{request.id}:{comment_id}",
            ),
        )
        return [entry] if entry is not None else []

    # ----------------------------------------------------- аутентификация

    # Письма аутентификации намеренно БЕЗ ключа от дублей: «отправить
    # ссылку ещё раз» — это осознанное действие человека, и подавлять
    # повтор значило бы сломать единственный способ восстановить доступ.
    # От рассылки защищает ограничение частоты (по IP и по адресу).

    def email_verification(self, *, email: str, link: str) -> list[NotificationOutbox]:
        """Письмо подтверждения адреса.

        В payload кладётся готовая ссылка, а не токен отдельно: у записи
        outbox нет других применений, а отдельный токен в базе соблазнял
        бы использовать его где-то ещё.
        """
        entry = self.outbox.enqueue(
            event=NotificationEvent.CUSTOMER_EMAIL_VERIFICATION,
            channel=NotificationChannel.EMAIL,
            recipient=email,
            payload={
                "link": link,
                "ttl_hours": settings.CUSTOMER_EMAIL_VERIFICATION_TTL_HOURS,
            },
        )
        return [entry] if entry is not None else []

    def password_reset(self, *, email: str, link: str) -> list[NotificationOutbox]:
        entry = self.outbox.enqueue(
            event=NotificationEvent.CUSTOMER_PASSWORD_RESET,
            channel=NotificationChannel.EMAIL,
            recipient=email,
            payload={
                "link": link,
                "ttl_minutes": settings.CUSTOMER_PASSWORD_RESET_TTL_MINUTES,
            },
        )
        return [entry] if entry is not None else []
