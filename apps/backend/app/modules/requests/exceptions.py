"""Ошибки домена заявок."""

from __future__ import annotations

from app.core.exceptions import AppError, ConflictError, NotFoundError

# Константа: имя 422 в Starlette переименовано (см. app/core/exceptions.py).
UNPROCESSABLE = 422


class RequestNotFoundError(NotFoundError):
    code = "request_not_found"
    message = "Заявка не найдена"


class RequestProductUnavailableError(AppError):
    """Позиция ссылается на товар, который нельзя заказать.

    Несуществующий, удалённый, черновик и отключённый товар дают одну
    и ту же ошибку: публичный API не должен подтверждать существование
    непубличных позиций каталога.
    """

    status_code = UNPROCESSABLE
    code = "product_unavailable"
    message = "Товар недоступен для заявки"


class RequestColorUnavailableError(AppError):
    """Цвета нет у товара или он отключён в справочнике."""

    status_code = UNPROCESSABLE
    code = "color_unavailable"
    message = "Товара нет в выбранном цвете"


class RequestRegionNotFoundError(AppError):
    status_code = UNPROCESSABLE
    code = "region_not_found"
    message = "Регион не найден"


class RequestQuantityBelowMinimumError(AppError):
    """Количество меньше минимальной партии товара (`min_order_qty`).

    Минимум и так показывается в карточке товара на витрине, поэтому
    в деталях он возвращается вместе с артикулом — фронтенду есть что
    подсказать клиенту.
    """

    status_code = UNPROCESSABLE
    code = "quantity_below_minimum"
    message = "Количество меньше минимальной партии товара"


class InvalidDateRangeError(AppError):
    status_code = UNPROCESSABLE
    code = "invalid_date_range"
    message = "Начало периода должно быть раньше его конца"


class RequestTotalTooLargeError(AppError):
    """Сумма не помещается в денежную колонку NUMERIC(14,2).

    Без проверки такая заявка упала бы на вставке с 500.
    """

    status_code = UNPROCESSABLE
    code = "request_total_too_large"
    message = "Слишком большое количество: сумма заявки превышает допустимую"


class IdempotencyKeyConflictError(ConflictError):
    """Ключ повторной отправки уже использован для заявки другого отправителя."""

    code = "idempotency_key_conflict"
    message = "Ключ повторной отправки уже использован"


class RequestAttachmentNotFoundError(NotFoundError):
    code = "request_attachment_not_found"
    message = "Файл заявки не найден"


# ----------------------------------------------------------- быстрый заказ


class QuickRequestFormError(AppError):
    """Тело запроса — не multipart/form-data или оборвано на середине."""

    code = "quick_request_form_invalid"
    message = "Ожидается multipart/form-data"


class QuickRequestEmptyError(AppError):
    """Заявка без предмета: пустой список артикулов, запрос КП без файла
    и без описания. Менеджеру нечего обрабатывать."""

    status_code = UNPROCESSABLE
    code = "quick_request_empty"
    message = "Опишите, что нужно: вставьте артикулы, приложите файл или напишите комментарий"


class RequestTooManyItemsError(AppError):
    status_code = UNPROCESSABLE
    code = "too_many_items"
    message = "Слишком много позиций в одной заявке"


class RequestAttachmentTooLargeError(AppError):
    status_code = 413  # константа: имя в Starlette переименовано
    code = "attachment_too_large"
    message = "Файл слишком большой"


class RequestAttachmentUnsupportedError(AppError):
    """Расширение не из списка или содержимое не совпадает с расширением.

    Проверка по сигнатуре, а не по заявленному типу: браузеры и ОС
    присылают что угодно, вплоть до application/octet-stream.
    """

    status_code = 415
    code = "attachment_unsupported"
    message = "Поддерживаются PDF, Excel, Word, DWG, DXF, CSV и изображения JPG и PNG"


class RequestAttachmentEmptyError(AppError):
    status_code = UNPROCESSABLE
    code = "attachment_empty"
    message = "Файл пуст"
