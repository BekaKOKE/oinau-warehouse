"""Правило изменяемости товара — одно на весь проект.

Мягко удалённый товар доступен только на чтение и восстановление.
Любая другая правка бессмысленна: товар не показывается на витрине,
не участвует в поиске и не может быть добавлен в заявку, поэтому смена
его категорий, характеристик или цены ничего не меняет, но создаёт
записи в аудите и вводит в заблуждение того, кто их потом читает.

Правило вынесено сюда, потому что его применяют два разных модуля
(каталог и цены). Копия в каждом сервисе рано или поздно разошлась бы —
именно так и появилось расхождение, которое этот модуль устраняет.
"""

from __future__ import annotations

from app.modules.catalog.exceptions import ProductDeletedError
from app.modules.catalog.models import Product


def is_mutable(product: Product) -> bool:
    return product.deleted_at is None


def ensure_mutable(product: Product) -> Product:
    """Бросает ProductDeletedError, если товар удалён.

    Восстановление — единственная мутация, которая обходит эту проверку,
    поэтому `restore` вызывает её намеренно не через этот helper.
    """
    if not is_mutable(product):
        raise ProductDeletedError(details={"product_id": product.id})
    return product
