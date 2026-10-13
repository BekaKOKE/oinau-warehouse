"""Наполнение каталога для интеграционных тестов.

Набор небольшой, но покрывает все ветки публичного API: три типа
ценообразования, три статуса наличия, скрытый прайс-лист, невидимые
товары и категории.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.enums import AttributeValueType, ProductStatus
from app.modules.catalog.models import (
    Attribute,
    AttributeOption,
    Category,
    CategoryTranslation,
    Product,
    ProductAttributeValue,
    ProductCategory,
    ProductTranslation,
)
from app.modules.geo.models import Region
from app.modules.inventory.models import Stock, Warehouse
from app.modules.pricing.enums import PricingType
from app.modules.pricing.models import PriceList, PriceTier


@dataclass
class CatalogFixture:
    public_price_list: PriceList
    dealer_price_list: PriceList
    warehouse: Warehouse
    region: Region
    categories: dict[str, Category] = field(default_factory=dict)
    products: dict[str, Product] = field(default_factory=dict)


async def _add_category(
    session: AsyncSession,
    *,
    slug: str,
    name: str,
    parent: Category | None = None,
    is_active: bool = True,
    deleted: bool = False,
    description: str | None = None,
) -> Category:
    from datetime import UTC, datetime

    category = Category(
        slug=slug,
        parent_id=parent.id if parent else None,
        depth=(parent.depth + 1) if parent else 0,
        is_active=is_active,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    session.add(category)
    await session.flush()
    # Материализованный путь: "1", "1.4", "1.4.9"
    category.path = f"{parent.path}.{category.id}" if parent else str(category.id)
    session.add(
        CategoryTranslation(
            category_id=category.id, locale="ru", name=name, description=description
        )
    )
    await session.flush()
    return category


async def _add_product(
    session: AsyncSession,
    *,
    sku: str,
    slug: str,
    name: str,
    categories: list[Category],
    pricing_type: PricingType = PricingType.FIXED,
    status: ProductStatus = ProductStatus.PUBLISHED,
    is_active: bool = True,
    deleted: bool = False,
    unit: str = "pcs",
    short_description: str | None = None,
    description: str | None = None,
    is_featured: bool = False,
    specs: dict[str, str] | None = None,
) -> Product:
    from datetime import UTC, datetime

    product = Product(
        sku=sku,
        slug=slug,
        status=status.value,
        is_active=is_active,
        is_featured=is_featured,
        unit=unit,
        pricing_type=pricing_type.value,
        specs=specs or {},
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    session.add(product)
    await session.flush()

    session.add(
        ProductTranslation(
            product_id=product.id,
            locale="ru",
            name=name,
            short_description=short_description,
            description=description,
        )
    )
    for index, category in enumerate(categories):
        session.add(
            ProductCategory(
                product_id=product.id,
                category_id=category.id,
                is_primary=index == 0,
            )
        )
    await session.flush()
    return product


async def build_catalog(session: AsyncSession) -> CatalogFixture:
    region = Region(code="almaty", name="Алматы")
    session.add(region)
    await session.flush()

    warehouse = Warehouse(code="main", name="Основной склад", region_id=region.id)
    # Прайс по умолчанию заводит миграция, но уборка между тестами
    # чистит все таблицы. Поэтому берём существующий, а если его уже
    # вынесло — создаём: двух строк с code='default' быть не должно.
    public_price_list = (
        await session.execute(select(PriceList).where(PriceList.code == "default"))
    ).scalar_one_or_none()
    if public_price_list is None:
        public_price_list = PriceList(
            code="default", name="Основной прайс", currency="KZT", is_default=True
        )
        session.add(public_price_list)
    dealer_price_list = PriceList(
        code="dealer", name="Дилерский прайс", currency="KZT", is_default=False
    )
    session.add_all([warehouse, dealer_price_list])
    await session.flush()

    # -------------------------------------------------------------- категории
    root = await _add_category(
        session, slug="komplektuyushchie", name="Комплектующие", description="Всё для площадок"
    )
    ropes = await _add_category(session, slug="kanaty", name="Канаты", parent=root)
    fasteners = await _add_category(session, slug="krepleniya", name="Крепления", parent=root)
    hidden = await _add_category(session, slug="skrytaya", name="Скрытая", is_active=False)

    # ------------------------------------------------------------ атрибуты
    diameter = Attribute(
        code="diameter",
        name_i18n={"ru": "Диаметр"},
        unit="мм",
        value_type=AttributeValueType.NUMBER.value,
        sort_order=1,
    )
    material = Attribute(
        code="material",
        name_i18n={"ru": "Материал"},
        value_type=AttributeValueType.OPTION.value,
        sort_order=2,
    )
    certified = Attribute(
        code="certified",
        name_i18n={"ru": "Сертифицирован"},
        value_type=AttributeValueType.BOOLEAN.value,
        sort_order=3,
    )
    internal = Attribute(
        code="internal_note",
        name_i18n={"ru": "Служебная пометка"},
        value_type=AttributeValueType.STRING.value,
        is_visible=False,
    )
    session.add_all([diameter, material, certified, internal])
    await session.flush()

    polypropylene = AttributeOption(
        attribute_id=material.id, slug="pp", value_i18n={"ru": "Полипропилен"}
    )
    session.add(polypropylene)
    await session.flush()

    # --------------------------------------------------------------- товары
    rope = await _add_product(
        session,
        sku="KAN-16-PP",
        slug="kanat-16-pp",
        name="Канат полипропиленовый 16 мм",
        short_description="Армированный канат для лазательных элементов",
        description="Подробное описание каната.",
        categories=[ropes],
        pricing_type=PricingType.TIERED,
        unit="m",
        is_featured=True,
        specs={"Страна": "Казахстан"},
    )
    session.add_all(
        [
            ProductAttributeValue(
                product_id=rope.id, attribute_id=diameter.id, value_numeric=Decimal("16.000")
            ),
            ProductAttributeValue(
                product_id=rope.id, attribute_id=material.id, option_id=polypropylene.id
            ),
            ProductAttributeValue(product_id=rope.id, attribute_id=certified.id, value_bool=True),
            ProductAttributeValue(
                product_id=rope.id, attribute_id=internal.id, value_string="не показывать"
            ),
        ]
    )
    for min_qty, max_qty, price in [
        (Decimal("1"), Decimal("9"), Decimal("3500.00")),
        (Decimal("10"), Decimal("49"), Decimal("3200.00")),
        (Decimal("50"), Decimal("99"), Decimal("2900.00")),
        (Decimal("100"), None, Decimal("2600.00")),
    ]:
        session.add(
            PriceTier(
                product_id=rope.id,
                price_list_id=public_price_list.id,
                min_qty=min_qty,
                max_qty=max_qty,
                price=price,
            )
        )
    # Дилерская цена того же товара — в публичный ответ попасть не должна
    session.add(
        PriceTier(
            product_id=rope.id,
            price_list_id=dealer_price_list.id,
            min_qty=Decimal("1"),
            price=Decimal("1111.00"),
        )
    )
    session.add(Stock(product_id=rope.id, warehouse_id=warehouse.id, quantity=Decimal("152.500")))

    fastener = await _add_product(
        session,
        sku="KRP-M10",
        slug="kreplenie-m10",
        name="Крепление М10 оцинкованное",
        categories=[fasteners],
        pricing_type=PricingType.FIXED,
    )
    session.add(
        PriceTier(
            product_id=fastener.id,
            price_list_id=public_price_list.id,
            min_qty=Decimal("1"),
            price=Decimal("1200.00"),
        )
    )
    session.add(Stock(product_id=fastener.id, warehouse_id=warehouse.id, quantity=Decimal("0")))

    seat = await _add_product(
        session,
        sku="SID-01",
        slug="sidenie-kachelej",
        name="Сиденье качелей HDPE",
        categories=[fasteners],
        pricing_type=PricingType.ON_REQUEST,
    )

    draft = await _add_product(
        session,
        sku="DRAFT-1",
        slug="chernovik",
        name="Черновик товара",
        categories=[ropes],
        status=ProductStatus.DRAFT,
    )
    removed = await _add_product(
        session,
        sku="DEL-1",
        slug="udalennyj",
        name="Удалённый товар",
        categories=[ropes],
        deleted=True,
    )
    inactive = await _add_product(
        session,
        sku="OFF-1",
        slug="otklyuchennyj",
        name="Отключённый товар",
        categories=[ropes],
        is_active=False,
    )

    await session.commit()

    return CatalogFixture(
        public_price_list=public_price_list,
        dealer_price_list=dealer_price_list,
        warehouse=warehouse,
        region=region,
        categories={
            "root": root,
            "ropes": ropes,
            "fasteners": fasteners,
            "hidden": hidden,
        },
        products={
            "rope": rope,
            "fastener": fastener,
            "seat": seat,
            "draft": draft,
            "removed": removed,
            "inactive": inactive,
        },
    )
