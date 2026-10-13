"""Схемы Admin API складов и остатков.

Публичные схемы не переиспользуются: витрина не должна знать ни точных
количеств, ни резервов, ни источника данных.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from app.modules.catalog.enums import ProductStatus
from app.modules.catalog.schemas_admin_products import ProductCategoryRead
from app.modules.inventory.enums import PublicAvailability, StockDisplayOverride
from app.modules.pricing.enums import PricingType

# Точность совпадает с колонкой NUMERIC(14,3): канат меряется метрами,
# крепёж бывает в килограммах, поэтому целых чисел недостаточно.
QuantityField = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]

MAX_STOCK_ENTRIES = 50


# ---------------------------------------------------------------- склады


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=255)
    region_id: int | None = Field(default=None, ge=1)
    is_active: bool = True
    external_id: str | None = Field(default=None, max_length=64)


class WarehouseUpdate(BaseModel):
    """Код склада не меняется.

    На него ссылается будущая выгрузка из 1С и внешние регламенты,
    а переименование кода тихо разорвало бы сопоставление. Отключение
    склада делается через `is_active`.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    region_id: int | None = Field(default=None, ge=1)
    is_active: bool | None = None
    external_id: str | None = Field(default=None, max_length=64)


class WarehouseRead(BaseModel):
    id: int
    code: str
    name: str
    region_id: int | None
    region_code: str | None = None
    region_name: str | None = None
    is_active: bool
    external_id: str | None
    sync_source: str


# --------------------------------------------------------------- остатки


class StockEntryInput(BaseModel):
    warehouse_id: int = Field(ge=1)
    quantity: QuantityField
    # Резерв заложен моделью, но пока не используется: заявки ничего
    # не резервируют. Поле появится в деле вместе с 1С.
    reserved: QuantityField = Decimal("0")

    @model_validator(mode="after")
    def _check_reserved(self) -> StockEntryInput:
        if self.reserved > self.quantity:
            raise ValueError(f"Резерв {self.reserved} больше остатка {self.quantity}")
        return self


class StockUpdate(BaseModel):
    """Ручная правка остатков.

    ВРЕМЕННЫЙ МЕХАНИЗМ. После интеграции с 1С источником истины по
    остаткам станет учётная система, и ручная правка либо исчезнет,
    либо останется аварийным инструментом. Поэтому здесь нет ни
    приходов/расходов, ни истории движений — только установка текущего
    значения.
    """

    items: list[StockEntryInput] = Field(min_length=1, max_length=MAX_STOCK_ENTRIES)

    @model_validator(mode="after")
    def _check_duplicates(self) -> StockUpdate:
        ids = [item.warehouse_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Склад указан в запросе несколько раз")
        return self


class StockEntryRead(BaseModel):
    warehouse_id: int
    warehouse_code: str
    warehouse_name: str
    warehouse_is_active: bool
    quantity: Decimal
    reserved: Decimal
    # Производная величина, в базе не хранится
    available: Decimal
    # Источник данных: manual | excel | 1c. Поле существующей модели,
    # новых состояний не вводится.
    sync_source: str | None = None
    synced_at: datetime | None = None
    external_id: str | None = None
    updated_at: datetime | None = None


class ProductStockRead(BaseModel):
    product_id: int
    sku: str
    unit: str
    entries: list[StockEntryRead] = Field(default_factory=list)
    # Итоги считаются ТОЛЬКО по активным складам — так же, как их
    # считает публичный расчёт наличия.
    total_quantity: Decimal
    total_reserved: Decimal
    total_available: Decimal
    # Что увидит посетитель сайта. Считается существующим resolver'ом.
    public_availability: PublicAvailability
    stock_display_override: StockDisplayOverride | None = None


class ProductStockListItem(ProductStockRead):
    """Строка списка остатков: остатки товара плюс то, что нужно таблице.

    Состав остатков тот же, что у GET /products/{id}/stock: по каждому
    складу количество, резерв, свободный остаток и поля синхронизации.
    Итоги — только по активным складам.
    """

    name: str | None = None
    status: ProductStatus
    is_active: bool
    pricing_type: PricingType
    # Внешний идентификатор товара — по нему 1С будет сопоставлять остатки.
    external_id: str | None = None
    # Основная категория товара — та же форма, что в списке товаров.
    primary_category: ProductCategoryRead | None = None
    # Последнее изменение любой строки остатка товара; null — строк нет.
    stock_updated_at: datetime | None = None


class AvailabilityOverrideUpdate(BaseModel):
    """Ручное переопределение публичного статуса наличия.

    Это НЕ остаток. Фактические количества не меняются: поле влияет
    только на то, что видит посетитель. `null` снимает переопределение,
    и статус снова вычисляется из остатков.
    """

    stock_display_override: StockDisplayOverride | None = None


class AvailabilityRead(BaseModel):
    product_id: int
    sku: str
    stock_display_override: StockDisplayOverride | None
    public_availability: PublicAvailability
    total_available: Decimal
