"""Контракт интеграционного API.

ЭТО НЕ ФОРМАТ 1С. Схемы намеренно нейтральны: они описывают то, что
нужно сайту, а не то, как устроена номенклатура в конкретной
конфигурации 1С. Преобразование формата — задача обработки на стороне
1С или тонкого адаптера (docs/architecture.md, 7.3). Если структура 1С
протечёт сюда, проект окажется привязан к текущей конфигурации навсегда.

Пока настоящая спецификация обмена от заказчика не получена, этот
контракт — предложение сайта. Он реализован полностью и покрыт
тестами, но перед включением боевого обмена должен быть сверен
с выгрузкой 1С.

Деньги и количества — Decimal и только Decimal. Pydantic принимает их
строкой, поэтому в JSON цену можно и нужно передавать строкой:
"3200.00", а не 3200.0. float потерял бы копейки на первой же тысяче
позиций.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.types import LEN_CODE, LEN_EXTERNAL_ID, LEN_NAME, LEN_UNIT

ExternalId = Annotated[str, Field(min_length=1, max_length=LEN_EXTERNAL_ID)]
Sku = Annotated[str, Field(min_length=1, max_length=LEN_CODE)]


class IntegrationModel(BaseModel):
    """Лишние поля запрещены.

    Обмен обязан ломаться громко: молча проигнорированное поле — это
    цена, которая «обновлялась» полгода и не обновилась ни разу.
    """

    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------ сопоставление


class ProductRef(IntegrationModel):
    """Ссылка на товар.

    Сопоставление только по стабильным идентификаторам: сначала
    `external_id` (GUID 1С), при его отсутствии — `sku`. Сопоставления
    по названию нет и не будет: переименование товара в 1С создало бы
    дубль в каталоге.
    """

    external_id: ExternalId | None = None
    sku: Sku | None = None

    @field_validator("external_id", "sku", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    def key(self) -> str:
        """Ключ строки для отчёта: то, по чему 1С узнает свою позицию."""
        return self.external_id or self.sku or "?"


class ReferencedModel(ProductRef):
    """Строка, обязанная нести хотя бы один стабильный идентификатор.

    Проверка в `model_validator`, а не в `model_post_init`: только так
    ошибка становится обычным 422 с указанием строки, а не пятисоткой.
    """

    @model_validator(mode="after")
    def _reference_present(self) -> ReferencedModel:
        if not self.external_id and not self.sku:
            raise ValueError("Нужен external_id или sku")
        return self


# ------------------------------------------------------------------ товары


class ProductUpsert(ReferencedModel):
    """Товар из учётной системы.

    Поля, которых 1С не касается (описание, SEO, изображения,
    характеристики для фильтров), в схеме отсутствуют — см. матрицу
    владения полями в docs/architecture.md, 7.2. Их нельзя затереть
    обменом, потому что их нельзя и передать.

    `None` означает «не менять». Чтобы отключить товар, нужно прислать
    `is_active: false` явно.
    """

    name: Annotated[str, Field(min_length=1, max_length=LEN_NAME)] | None = None
    unit: Annotated[str, Field(min_length=1, max_length=LEN_UNIT)] | None = None
    is_active: bool | None = None
    min_order_qty: Annotated[Decimal, Field(gt=0, decimal_places=3)] | None = None
    # Категории и бренд — необязательные подсказки; структура каталога
    # ведётся на сайте, и обмен её не переписывает.
    brand: Annotated[str, Field(max_length=255)] | None = None


class ProductBatch(IntegrationModel):
    items: list[ProductUpsert] = Field(min_length=1)


# ------------------------------------------------------------------- цены


class PriceTierIn(IntegrationModel):
    """Ступень цены: «от min_qty до max_qty — такая цена».

    Обычная цена — одна ступень с min_qty=1 и max_qty=null.
    """

    min_qty: Annotated[Decimal, Field(gt=0, decimal_places=3)] = Decimal(1)
    max_qty: Annotated[Decimal, Field(gt=0, decimal_places=3)] | None = None
    price: Annotated[Decimal, Field(ge=0, decimal_places=2)]


class PriceUpsert(ReferencedModel):
    """Цены одного товара.

    `tiers` заменяет ВЕСЬ набор ступеней товара в указанном прайс-листе:
    частичное обновление ступеней невозможно осмысленно — пересечение
    диапазонов дало бы две цены на одно количество.
    """

    price_list_code: Annotated[str, Field(min_length=1, max_length=LEN_CODE)] | None = None
    currency: Annotated[str, Field(min_length=3, max_length=3)] | None = None
    tiers: list[PriceTierIn] = Field(min_length=1)


class PriceBatch(IntegrationModel):
    items: list[PriceUpsert] = Field(min_length=1)


# ---------------------------------------------------------------- остатки


class StockUpsertItem(ReferencedModel):
    """Остаток товара на складе.

    Склад определяется по `warehouse_external_id` или `warehouse_code`.
    Новых складов обмен не создаёт: склад — объект с адресом, регионом
    и признаком активности, и заводить его вслепую из пакета остатков
    значит однажды показать витрине остаток с несуществующей площадки.
    """

    warehouse_external_id: ExternalId | None = None
    warehouse_code: Annotated[str, Field(min_length=1, max_length=LEN_CODE)] | None = None

    quantity: Annotated[Decimal, Field(ge=0, decimal_places=3)]
    reserved: Annotated[Decimal, Field(ge=0, decimal_places=3)] | None = None

    @model_validator(mode="after")
    def _warehouse_present(self) -> StockUpsertItem:
        if not self.warehouse_external_id and not self.warehouse_code:
            raise ValueError("Нужен warehouse_external_id или warehouse_code")
        return self


class StockBatch(IntegrationModel):
    items: list[StockUpsertItem] = Field(min_length=1)


# ------------------------------------------------------------------ отчёт


class RowOutcome(IntegrationModel):
    """Результат по одной строке пакета.

    1С обязана понимать, что именно не прошло: без построчного ответа
    разбор «почему цены не обновились» превращается в гадание.
    """

    key: str
    status: Literal["created", "updated", "skipped", "failed"]
    # Код ошибки машиночитаемый, message — для человека в журнале 1С.
    code: str | None = None
    message: str | None = None


class SyncResult(IntegrationModel):
    """Итог пакета.

    `received` всегда равно числу присланных строк; сумма остальных
    счётчиков равна `received`.
    """

    sync_uuid: str
    received: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    duration_ms: int = 0
    # Повтор того же пакета: изменений не делалось, отдан прежний итог.
    duplicate: bool = False
    rows: list[RowOutcome] = Field(default_factory=list)


# ------------------------------------------------------------------ заявки


class IntegrationRequestItem(IntegrationModel):
    sku: str | None = None
    name: str
    unit: str
    quantity: Decimal
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    # Код и название цвета из справочника сайта; null — без цвета.
    color: str | None = None
    color_name: str | None = None


class IntegrationRequest(IntegrationModel):
    """Заявка для выгрузки в учётную систему.

    Состав берётся из снапшотов позиций: заявка — коммерческий
    документ и должна выгружаться такой, какой её отправил клиент.
    """

    uuid: str
    number: str
    status: str
    created_at: str
    customer_name: str
    company: str | None = None
    phone: str | None = None
    email: str | None = None
    region: str | None = None
    comment: str | None = None
    currency: str
    total_estimate: Decimal | None = None
    items: list[IntegrationRequestItem]
    exported_at: str | None = None


class IntegrationRequestPage(IntegrationModel):
    items: list[IntegrationRequest]
    total: int


class AckResult(IntegrationModel):
    """Подтверждение приёма заявки учётной системой."""

    uuid: str
    external_id: str | None = None
    exported_at: str


class IntegrationHealth(IntegrationModel):
    """Проверка связи. Реквизитов и версий наружу не отдаёт."""

    status: Literal["ok"]
    enabled: bool
    key_name: str
    scopes: list[str]
    server_time: str
