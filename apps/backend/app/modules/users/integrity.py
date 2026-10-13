"""Соответствие ограничений целостности пользователей доменным ошибкам.

Имя индекса задано в модели (`uq_users_email`, частичный — только по
неудалённым строкам). Предварительный SELECT по email гонку не
закрывает: два запроса могут одновременно убедиться, что адрес свободен.
Последняя гарантия — база, и её отказ переводится здесь в 409.
"""

from __future__ import annotations

from app.core.exceptions import AppError
from app.modules.users.exceptions import EmailAlreadyExistsError

USER_UNIQUE_ERRORS: dict[str, type[AppError]] = {
    "uq_users_email": EmailAlreadyExistsError,
}
