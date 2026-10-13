"""Ошибки интеграционного API."""

from __future__ import annotations

from fastapi import status

from app.core.exceptions import AppError


class IntegrationAuthError(AppError):
    """Ключ отсутствует, отозван, просрочен или неизвестен.

    Причина намеренно не уточняется: подробный ответ превращает
    эндпоинт в оракул для проверки украденных ключей.
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "integration_unauthenticated"
    message = "Неизвестный или отозванный ключ интеграции"


class IntegrationScopeError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "integration_scope_denied"
    message = "Ключу не разрешена эта операция"


class IntegrationIpDeniedError(AppError):
    """Адрес вне списка разрешённых.

    Тот же 401, что и у неизвестного ключа: иначе перебор адресов
    подсказывал бы, что ключ верен.
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "integration_unauthenticated"
    message = "Неизвестный или отозванный ключ интеграции"


class IntegrationDisabledError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "integration_disabled"
    message = "Обмен выключен настройкой ONE_C_INTEGRATION_ENABLED"


class PayloadTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "payload_too_large"
    message = "Тело запроса больше допустимого"


class BatchTooLargeError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "batch_too_large"
    message = "Слишком много позиций в одном пакете"
