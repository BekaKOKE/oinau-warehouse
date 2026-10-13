"""Сводка каталога для главного экрана админки.

Только счётчики. Сами товары этим эндпоинтом не отдаются: список
«что именно без цены» строится обычными списками с фильтрами.
"""

from __future__ import annotations

from pydantic import BaseModel


class ProductCounts(BaseModel):
    """Товары. Все счётчики, кроме `deleted`, — по неудалённым товарам."""

    total: int
    active: int
    inactive: int
    # По единому правилу app/modules/catalog/visibility.py
    publicly_visible: int
    featured: int
    draft: int
    published: int
    archived: int
    # Мягко удалённые — отдельно, в `total` не входят.
    deleted: int


class ProductContentCounts(BaseModel):
    """Незаполненные карточки."""

    # Ни одного привязанного изображения.
    without_images: int
    # Нет ни одного изображения в статусе READY — посетитель сайта не
    # видит ни одной картинки (включает `without_images`).
    without_ready_images: int
    # Тип цены не ON_REQUEST, но в публичном прайс-листе нет ни одной
    # ступени: на витрине такой товар остаётся без цены.
    without_price: int
    # Цена «по запросу» — осознанное состояние, не ошибка.
    price_on_request: int


class AvailabilityCounts(BaseModel):
    """Публичный статус наличия по неудалённым товарам.

    Считается тем же правилом, что витрина (resolve_availability).
    Точных количеств здесь нет — только число товаров в каждом статусе.
    """

    in_stock: int
    out_of_stock: int
    on_request: int
    # Сколько из них показываются по ручному переопределению.
    overridden: int


class CategoryCounts(BaseModel):
    """Категории. `total` и `active` — по неудалённым."""

    total: int
    active: int
    deleted: int


class CatalogSummaryRead(BaseModel):
    products: ProductCounts
    content: ProductContentCounts
    availability: AvailabilityCounts
    categories: CategoryCounts
