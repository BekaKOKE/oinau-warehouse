"""Ошибки справочника цветов и цветов товара."""

from __future__ import annotations

from app.core.exceptions import ConflictError


class ColorCodeExistsError(ConflictError):
    code = "color_code_exists"
    message = "Цвет с таким кодом уже существует"


class ColorInUseError(ConflictError):
    code = "color_in_use"
    message = "Цвет используется в товарах: отключите его вместо удаления"


class ColorInactiveError(ConflictError):
    code = "color_inactive"
    message = "Цвет отключён в справочнике"


class DuplicateProductColorError(ConflictError):
    code = "duplicate_product_color"
    message = "Цвет указан у товара несколько раз"
