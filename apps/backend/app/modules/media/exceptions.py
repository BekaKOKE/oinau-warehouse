"""Ошибки бизнес-правил медиатеки."""

from __future__ import annotations

from app.core.exceptions import AppError, ConflictError, NotFoundError


class MediaNotFoundError(NotFoundError):
    code = "media_not_found"
    message = "Файл медиатеки не найден"


class ProductImageNotFoundError(NotFoundError):
    code = "product_image_not_found"
    message = "Изображение товара не найдено"


class MediaInUseError(ConflictError):
    code = "media_in_use"
    message = "Файл используется: сначала отвяжите его от товаров и контента"


class MediaFailedError(ConflictError):
    code = "media_failed"
    message = "Файл отвергнут при проверке — загрузите его заново"


class MediaUploadMissingError(ConflictError):
    code = "upload_not_found"
    message = "Файл ещё не загружен в хранилище"


class MediaUploadRejectedError(AppError):
    """Загруженный объект не прошёл проверку.

    422, а не 409: дело не в состоянии сервера, а в самом файле. Запись
    к этому моменту уже переведена в FAILED и сохранена.
    """

    status_code = 422
    code = "upload_rejected"
    message = "Файл не прошёл проверку"


class ImageAlreadyAttachedError(ConflictError):
    code = "image_already_attached"
    message = "Этот файл уже привязан к товару"


class ProductImageLimitError(ConflictError):
    code = "product_image_limit"
    message = "Достигнуто максимальное число изображений товара"


class ImageOrderMismatchError(ConflictError):
    code = "image_order_mismatch"
    message = "Порядок должен перечислять ровно все изображения товара"


class MainImageConflictError(ConflictError):
    code = "main_image_conflict"
    message = "Главное изображение товара изменено параллельно, повторите запрос"


class DocumentKindError(ConflictError):
    """Документ (PDF, DWG, DXF) — только схема, чертёж или сертификат.

    Фотографией и обложкой карточки он быть не может: картинки у него нет,
    и витрина показала бы пустое место.
    """

    code = "document_kind_invalid"
    message = "Документ можно привязать только как схему, чертёж или сертификат"
