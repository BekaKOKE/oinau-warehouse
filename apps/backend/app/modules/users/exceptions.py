"""Ошибки домена аутентификации."""

from __future__ import annotations

from fastapi import status

from app.core.exceptions import AppError, ConflictError, NotFoundError, PermissionDeniedError


class InvalidCredentialsError(AppError):
    """Единая ошибка для неверного пароля, несуществующего email
    и отключённой учётной записи.

    Различать их наружу нельзя: любое отличие в ответе позволяет
    перебрать, какие адреса заведены в системе.
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "invalid_credentials"
    message = "Неверный email или пароль"


class AccountLockedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "account_locked"
    message = "Учётная запись временно заблокирована из-за неудачных попыток входа"


class InvalidRefreshTokenError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "invalid_refresh_token"
    message = "Сессия недействительна, требуется повторный вход"


class EmailAlreadyExistsError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "email_exists"
    message = "Пользователь с таким email уже существует"


class UserNotFoundError(NotFoundError):
    code = "user_not_found"
    message = "Сотрудник не найден"


class SelfDeactivationError(ConflictError):
    """Отключить собственную учётную запись нельзя.

    Иначе единственный администратор одним переключателем закрывает себе
    вход, и восстановить доступ можно только правкой базы.
    """

    code = "self_deactivation"
    message = "Нельзя отключить собственную учётную запись"


class SelfRoleChangeError(ConflictError):
    """Свою роль сотрудник не меняет — по той же причине, что и выше:
    случайное понижение до VIEWER отбирает доступ к разделу навсегда."""

    code = "self_role_change"
    message = "Нельзя изменить собственную роль"


class SuperadminRequiredError(PermissionDeniedError):
    """Учётными записями суперадминистраторов управляет суперадминистратор.

    Право `user.manage` есть и у роли ADMIN. Без этого правила
    администратор завёл бы себе вторую учётную запись с ролью
    SUPERADMIN и получил бы права, которых у него нет (api_key.manage).
    """

    code = "superadmin_required"
    message = "Управлять суперадминистраторами может только суперадминистратор"
