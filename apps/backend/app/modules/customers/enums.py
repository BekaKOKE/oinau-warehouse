"""Перечисления B2B-кабинета клиентов."""

from __future__ import annotations

from enum import StrEnum


class CustomerTokenPurpose(StrEnum):
    """Назначение одноразового токена.

    Назначение хранится в строке токена и проверяется при использовании:
    токен из письма подтверждения нельзя предъявить как токен сброса
    пароля, даже если строки случайно совпадут по формату.
    """

    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
    PASSWORD_RESET = "PASSWORD_RESET"  # noqa: S105


class ProjectStatus(StrEnum):
    """Статус проекта клиента.

    Фундамент без workflow: клиент сам отмечает стадию проекта. Когда
    появятся согласования и сметы, список расширится без смены схемы
    (VARCHAR + CHECK).
    """

    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class NotificationType(StrEnum):
    """Тип уведомления клиента.

    Тип определяет, как фронтенд покажет уведомление и куда поведёт
    по клику (`payload` содержит ссылку на объект).
    """

    REQUEST_STATUS_CHANGED = "REQUEST_STATUS_CHANGED"
    REQUEST_COMMENT_ADDED = "REQUEST_COMMENT_ADDED"
    ACCOUNT = "ACCOUNT"
    SYSTEM = "SYSTEM"


class CustomerRequestStatus(StrEnum):
    """Статус заявки в том виде, в котором его видит клиент.

    Внутренний статус SPAM клиенту не показывается: пометка «спам»
    на собственной заявке звучит как обвинение и раскрывает внутреннюю
    разметку менеджеров. Такая заявка выглядит для клиента отменённой.
    """

    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_CLIENT = "WAITING_CLIENT"
    QUOTE_SENT = "QUOTE_SENT"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
