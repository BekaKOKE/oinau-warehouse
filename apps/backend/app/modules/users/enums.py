"""Роли пользователей."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """Роли сотрудников.

    Клиентов здесь нет: заявка оставляется без регистрации, а будущий
    B2B-кабинет получит отдельную таблицу customers. Смешивать сотрудников
    и клиентов в одной таблице нельзя — у них разные политики паролей,
    блокировки и разный жизненный цикл.
    """

    SUPERADMIN = "SUPERADMIN"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    CONTENT_MANAGER = "CONTENT_MANAGER"
    VIEWER = "VIEWER"
