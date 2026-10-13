"""Схемы ответов публичного каталога.

ORM-модели наружу не отдаются никогда: они содержат `deleted_at`,
`external_id`, `sync_source`, точные остатки и служебные метки времени.
Отдельные схемы фиксируют стабильный контракт и делают невозможной
утечку внутреннего поля при добавлении колонки в модель.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.inventory.enums import PublicAvailability
from app.modules.pricing.enums import PricingType

# --------------------------------------------------------------- категории


class CategoryImage(BaseModel):
    """Обложка раздела из медиатеки.

    Та же форма, что у изображения товара: готовый URL, размер для
    резервирования места в вёрстке и карта вариантов. Ключ объекта
    в хранилище наружу не уходит.
    """

    url: str
    width: int | None = None
    height: int | None = None
    variants: dict[str, str] = Field(default_factory=dict)


class CategoryNode(BaseModel):
    """Узел дерева категорий.

    Внутреннего `id` нет: навигация строится по `slug`, он же служит
    ключом в React. Отдавать автоинкремент наружу незачем.
    """

    slug: str
    name: str
    depth: int
    # Своей обложки может не быть: витрина тогда подставляет фото
    # товара из раздела (см. CategoryGrid).
    image: CategoryImage | None = None
    # Товаров на странице категории с учётом подкатегорий. Витрина
    # выводит это число на карточке раздела, и считать его на клиенте
    # было бы нечем: список товаров она грузит постранично.
    product_count: int = 0
    children: list[CategoryNode] = Field(default_factory=list)


class CategoryDetail(BaseModel):
    """Данные страницы категории."""

    slug: str
    name: str
    description: str | None = None
    image: CategoryImage | None = None
    product_count: int = 0
    seo_title: str | None = None
    seo_description: str | None = None
    breadcrumbs: list[CategoryBreadcrumb] = Field(default_factory=list)
    children: list[CategoryNode] = Field(default_factory=list)


class CategoryBreadcrumb(BaseModel):
    slug: str
    name: str


# ------------------------------------------------------------------- цены


class PriceTierRead(BaseModel):
    """Ценовая ступень. `max_quantity=null` означает открытый диапазон «и выше»."""

    min_quantity: Decimal
    max_quantity: Decimal | None = None
    price: Decimal


class PriceInfo(BaseModel):
    """Публичное представление цены.

    `price` заполнено только для FIXED — там ступень одна и её можно
    показать без таблицы. Для TIERED и FROM фронтенд ориентируется
    на `from_price` в списке и на `tiers` в карточке. Для ON_REQUEST
    оба поля пусты: отсутствие цены — это состояние, а не ноль.
    """

    type: PricingType
    currency: str
    price: Decimal | None = None
    from_price: Decimal | None = None
    to_price: Decimal | None = None
    tiers: list[PriceTierRead] = Field(default_factory=list)


# ------------------------------------------------------------- изображения


class ImageRead(BaseModel):
    """Изображение товара.

    Наружу уходит только готовый URL. Внутренний ключ объекта в хранилище
    фронтенду не нужен, а раскрывать структуру бакета незачем: она
    подсказывает, как устроено хранилище, и привязывает клиента
    к текущему провайдеру.
    """

    url: str
    kind: str
    alt: str | None = None
    is_main: bool = False
    # Размер файла по ссылке `url` — чтобы вёрстка резервировала место
    # под картинку и страница не прыгала при загрузке.
    width: int | None = None
    height: int | None = None
    variants: dict[str, str] = Field(default_factory=dict)


class DocumentRead(BaseModel):
    """Схема или чертёж товара — отдельно от галереи фотографий.

    `url` ведёт на публичную копию файла в CDN: PDF открывается
    в браузере, DWG/DXF скачиваются. У схемы-изображения есть
    `preview_url` — уменьшенная копия для превью на странице.
    """

    url: str
    kind: str
    filename: str | None = None
    content_type: str
    size_bytes: int | None = None
    preview_url: str | None = None


# ---------------------------------------------------------- характеристики


class CharacteristicRead(BaseModel):
    """Характеристика в виде, готовом к выводу.

    Значение уже отформатировано с единицей измерения: фронтенд не
    должен знать, что число из `value_numeric`, а «мм» — из
    `attributes.unit`.
    """

    code: str
    name: str
    value: str


# ------------------------------------------------------------------ цвета


class ProductColorOption(BaseModel):
    """Цвет товара: образец для витрины и статус наличия.

    Точный остаток цвета наружу не уходит — как и остаток товара.
    """

    code: str
    name: str
    hex: str
    availability: PublicAvailability


class ProductColorDetail(ProductColorOption):
    """Цвет в карточке товара — с ценой: у цвета может быть надбавка."""

    price: PriceInfo


# ----------------------------------------------------------------- товары


class ProductListItem(BaseModel):
    """Строка списка товаров.

    Ступени цены (`price.tiers`) и характеристики отдаются и в списке:
    таблица товаров раздела сравнивает позиции по цене от объёма
    и параметрам, не открывая каждую карточку.
    """

    sku: str
    slug: str
    name: str
    short_description: str | None = None
    unit: str
    min_order_qty: Decimal = Decimal("1")
    is_featured: bool
    price: PriceInfo
    availability: PublicAvailability
    image: ImageRead | None = None
    characteristics: list[CharacteristicRead] = Field(default_factory=list)
    specs: dict[str, str] = Field(default_factory=dict)
    # Пусто — товар без выбора цвета.
    colors: list[ProductColorOption] = Field(default_factory=list)


class ProductDetail(BaseModel):
    sku: str
    slug: str
    name: str
    short_description: str | None = None
    description: str | None = None
    brand: str | None = None
    unit: str
    min_order_qty: Decimal
    is_featured: bool

    price: PriceInfo
    availability: PublicAvailability

    breadcrumbs: list[CategoryBreadcrumb] = Field(default_factory=list)
    categories: list[CategoryBreadcrumb] = Field(default_factory=list)
    images: list[ImageRead] = Field(default_factory=list)
    # Схемы и чертежи — отдельный блок страницы, не часть галереи.
    documents: list[DocumentRead] = Field(default_factory=list)
    characteristics: list[CharacteristicRead] = Field(default_factory=list)
    specs: dict[str, str] = Field(default_factory=dict)
    # Пусто — товар без выбора цвета. Иначе цвет выбирается при заказе.
    colors: list[ProductColorDetail] = Field(default_factory=list)

    seo_title: str | None = None
    seo_description: str | None = None


class FacetOptionRead(BaseModel):
    slug: str
    name: str
    # Сколько товаров раздела с этим значением.
    count: int


class FacetRead(BaseModel):
    """Фильтр раздела по характеристике типа OPTION (цвет, материал, ...)."""

    code: str
    name: str
    unit: str | None = None
    options: list[FacetOptionRead] = Field(default_factory=list)


CategoryNode.model_rebuild()
CategoryDetail.model_rebuild()
