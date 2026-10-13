"""Ошибки домена ценообразования."""

from __future__ import annotations

from fastapi import status

from app.core.exceptions import AppError, ConflictError


class DefaultPriceListMissingError(AppError):
    """Публичный прайс-лист не заведён.

    Это ошибка конфигурации сервера, а не пользователя: создавать
    прайс-лист «на лету» внутри запроса на изменение цены товара нельзя —
    так в базе молча появится сущность, которую никто не настраивал,
    с валютой по умолчанию и неизвестными условиями.
    """

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "default_price_list_missing"
    message = "Публичный прайс-лист не настроен"


class OverlappingTiersError(ConflictError):
    code = "overlapping_tiers"
    message = "Ценовые ступени пересекаются по количеству"
