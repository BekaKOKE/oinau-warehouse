"""Соответствие ограничений целостности медиатеки доменным ошибкам.

Имена — из миграции 02b0358003e8 (naming convention в app/db/base.py).
Предварительные проверки в сервисе не защищают от гонки двух запросов;
последнее слово остаётся за базой, а эта таблица превращает её отказ
в понятный 409 вместо 500.
"""

from __future__ import annotations

from app.core.exceptions import AppError
from app.modules.media.exceptions import (
    ImageAlreadyAttachedError,
    MainImageConflictError,
    MediaInUseError,
)

MEDIA_CONSTRAINT_ERRORS: dict[str, type[AppError]] = {
    "uq_product_images_product_media": ImageAlreadyAttachedError,
    "uq_product_images_main": MainImageConflictError,
    # FK RESTRICT: файл привязали к товару между проверкой и удалением.
    "fk_product_images_media_file_id_media_files": MediaInUseError,
}
