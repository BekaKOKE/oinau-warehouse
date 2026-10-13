"""Ошибки домена клиентского кабинета."""

from __future__ import annotations

from fastapi import status

from app.core.exceptions import AppError, ConflictError, NotFoundError

UNPROCESSABLE = 422


class CustomerInvalidCredentialsError(AppError):
    """Единая ошибка для неверного пароля, несуществующего email,
    отключённого и удалённого аккаунта: различать их наружу нельзя."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "invalid_credentials"
    message = "Неверный email или пароль"


class CustomerEmailNotVerifiedError(AppError):
    """Сообщается только тому, кто предъявил верный пароль: иначе вход
    стал бы детектором зарегистрированных адресов."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "email_not_verified"
    message = "Подтвердите email: ссылка отправлена на почту при регистрации"


class CustomerAccountLockedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "account_locked"
    message = "Учётная запись временно заблокирована из-за неудачных попыток входа"


class CustomerInvalidRefreshTokenError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "invalid_refresh_token"
    message = "Сессия недействительна, требуется повторный вход"


class CustomerInvalidActionTokenError(AppError):
    """Неизвестный, использованный, просроченный или чужого назначения
    токен — одна и та же ошибка."""

    status_code = UNPROCESSABLE
    code = "invalid_token"
    message = "Ссылка недействительна или устарела. Запросите новую"


class CustomerRegionNotFoundError(AppError):
    status_code = UNPROCESSABLE
    code = "region_not_found"
    message = "Регион не найден"


class FavoriteProductUnavailableError(AppError):
    """Непубличный и несуществующий товар неразличимы, как на витрине."""

    status_code = UNPROCESSABLE
    code = "product_unavailable"
    message = "Товар недоступен"


class FavoriteNotFoundError(NotFoundError):
    code = "favorite_not_found"
    message = "Товара нет в избранном"


class CustomerRequestNotFoundError(NotFoundError):
    """Чужая заявка и несуществующая дают одинаковый 404: номер заявки
    не должен подтверждаться чужому клиенту."""

    code = "request_not_found"
    message = "Заявка не найдена"


class ProjectNotFoundError(NotFoundError):
    code = "project_not_found"
    message = "Проект не найден"


class ProjectItemExistsError(ConflictError):
    code = "project_item_exists"
    message = "Товар уже есть в проекте"


class ProjectItemNotFoundError(NotFoundError):
    code = "project_item_not_found"
    message = "Позиции нет в проекте"


class NotificationNotFoundError(NotFoundError):
    code = "notification_not_found"
    message = "Уведомление не найдено"
