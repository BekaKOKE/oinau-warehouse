"""Соответствие ограничений таблиц цветов доменным ошибкам."""

from __future__ import annotations

from app.core.exceptions import AppError
from app.modules.colors.exceptions import ColorCodeExistsError, DuplicateProductColorError

COLOR_CONSTRAINT_ERRORS: dict[str, type[AppError]] = {
    "uq_colors_code": ColorCodeExistsError,
    # Два параллельных сохранения цветов одного товара.
    "uq_product_colors_product_id_color_id": DuplicateProductColorError,
}
