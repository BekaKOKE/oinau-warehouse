"""Правило публичной видимости товара — единственное место в проекте.

Условие нужно в двух формах: как SQL-предикат для выборок публичного
каталога и как проверка на объекте для admin-ответа. Разные формы
неизбежны, но правило одно, и живёт оно здесь. Продублировать его
в админке значило бы получить экран, который показывает «опубликован»
для товара, невидимого на витрине.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_

from app.modules.catalog.enums import ProductStatus
from app.modules.catalog.models import Product


def public_visibility_clause() -> ColumnElement[bool]:
    """SQL-условие: товар виден посетителю сайта."""
    return and_(
        Product.deleted_at.is_(None),
        Product.is_active.is_(True),
        Product.status == ProductStatus.PUBLISHED.value,
    )


def is_publicly_visible(product: Product) -> bool:
    """То же правило для загруженного объекта."""
    return (
        product.deleted_at is None
        and product.is_active
        and product.status == ProductStatus.PUBLISHED.value
    )
