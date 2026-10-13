"""Ошибки импорта и экспорта каталога.

Ошибки в ДАННЫХ файла (неизвестная категория, неверная цена) сюда не
относятся: они возвращаются списком в отчёте предпросмотра с указанием
листа, строки и колонки. Здесь — отказы принять файл целиком и
нарушения порядка «предпросмотр -> подтверждение».
"""

from __future__ import annotations

from fastapi import status

from app.core.exceptions import AppError, ConflictError, NotFoundError


class ImportUploadError(AppError):
    code = "import_upload_invalid"
    message = "Ожидается multipart/form-data с одним файлом в поле file"


class ImportFileMissingError(AppError):
    status_code = 422
    code = "import_file_missing"
    message = "Файл не передан: ожидается поле file"


class ImportFileEmptyError(AppError):
    status_code = 422
    code = "import_file_empty"
    message = "Файл пуст"


class ImportFileTooLargeError(AppError):
    status_code = 413  # константа: имя в Starlette переименовано
    code = "import_file_too_large"
    message = "Файл слишком большой"


class ImportUnsupportedFileError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "import_unsupported_file"
    message = "Поддерживается только книга Excel в формате .xlsx"


class ImportFileCorruptedError(AppError):
    status_code = 422
    code = "import_file_corrupted"
    message = "Файл повреждён или не является книгой Excel"


class ImportJobNotFoundError(NotFoundError):
    code = "import_job_not_found"
    message = "Импорт не найден"


class ImportNotCommittableError(ConflictError):
    """Подтверждать можно только успешный непросроченный предпросмотр.

    Конкретная причина — в коде ошибки: import_not_valid,
    import_already_committed, import_failed, import_preview_expired.
    """

    code = "import_not_committable"
    message = "Этот импорт нельзя подтвердить"


class ImportFileMismatchError(ConflictError):
    code = "import_file_mismatch"
    message = "Файл отличается от проверенного при предпросмотре. Загрузите файл заново"


class ImportValidationFailedError(AppError):
    """Повторная проверка при подтверждении нашла ошибки.

    Файл тот же, но каталог успел измениться после предпросмотра
    (например, артикул заняли через админку).
    """

    status_code = 422
    code = "import_validation_failed"
    message = "Каталог изменился после предпросмотра: импорт не применён"


class ExportValueTooLongError(ConflictError):
    code = "export_value_too_long"
    message = "Значение не помещается в ячейку Excel (не больше 32 767 символов)"
