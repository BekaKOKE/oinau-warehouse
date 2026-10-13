"""Создание уведомлений клиента — единственная точка входа.

Сейчас уведомление — только запись в кабинете. Внешние каналы (email,
Telegram) подключатся отдельным этапом здесь же: `notify` останется
тем же вызовом для всех источников событий (админка, будущий обмен
с 1С), а доставка станет задачей воркера по свежим записям.

Метод не коммитит: уведомление фиксируется той же транзакцией, что
и событие. Иначе клиент мог бы получить «статус заявки изменён» при
откате самой смены статуса.
"""

from __future__ import annotations

from typing import Any

from app.core.service import BaseService
from app.modules.customers.enums import NotificationType
from app.modules.customers.models import CustomerNotification
from app.modules.customers.service_requests import customer_status
from app.modules.requests.enums import RequestStatus

_STATUS_TITLES: dict[str, str] = {
    "NEW": "Заявка принята",
    "IN_PROGRESS": "Заявка в работе",
    "WAITING_CLIENT": "Нужен ваш ответ",
    "QUOTE_SENT": "Коммерческое предложение отправлено",
    "APPROVED": "Заявка согласована",
    "COMPLETED": "Заявка выполнена",
    "CANCELLED": "Заявка отменена",
}


class CustomerNotificationService(BaseService):
    def notify(
        self,
        *,
        customer_id: int,
        type: NotificationType,
        title: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> CustomerNotification:
        notification = CustomerNotification(
            customer_id=customer_id,
            type=type.value,
            title=title,
            message=message,
            payload=payload or {},
        )
        self.session.add(notification)
        return notification

    def request_status_changed(
        self, *, customer_id: int, number: str, status: RequestStatus
    ) -> CustomerNotification:
        """Смена статуса глазами клиента (SPAM выглядит как отмена)."""
        visible = customer_status(status.value)
        return self.notify(
            customer_id=customer_id,
            type=NotificationType.REQUEST_STATUS_CHANGED,
            title=_STATUS_TITLES.get(visible.value, "Статус заявки изменён"),
            message=f"Статус заявки {number} изменён.",
            payload={"request_number": number, "status": visible.value},
        )

    def request_comment_added(self, *, customer_id: int, number: str) -> CustomerNotification:
        """Текст комментария в уведомление не копируется: он читается
        в карточке заявки, а уведомление может уйти во внешний канал."""
        return self.notify(
            customer_id=customer_id,
            type=NotificationType.REQUEST_COMMENT_ADDED,
            title="Новый ответ по заявке",
            message=f"Менеджер оставил комментарий к заявке {number}.",
            payload={"request_number": number},
        )
