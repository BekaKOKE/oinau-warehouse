"""Демонстрационные данные для локальной разработки.

Наполняет пустую базу так, чтобы сразу после `alembic upgrade head`
на сайте было что показать: дерево категорий, два десятка товаров
со всеми четырьмя типами цен и тремя статусами наличия, характеристики,
остатки и разделы CMS.

Скрипт НЕ является миграцией и в production не запускается: он
защищён проверкой ENV. Все данные выдуманы.

Запуск:
    python -m app.scripts.seed            # добавить, что отсутствует
    python -m app.scripts.seed --reset    # пересоздать демо-набор
    python -m app.scripts.seed --no-images  # без картинок (без MinIO)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import configure_logging
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
from app.modules.content.enums import ContentSectionKey
from app.modules.content.models import ContentSection
from app.modules.content.schemas_admin import SECTION_SCHEMAS
from app.modules.geo.models import Region
from app.modules.inventory.models import Stock, Warehouse
from app.modules.media.enums import ImageKind, MediaPurpose, MediaStatus
from app.modules.media.models import MediaFile, ProductImage
from app.modules.media.service_admin import build_original_key
from app.modules.media.service_processing import MediaProcessingService
from app.modules.pricing.models import PriceList, PriceTier
from app.scripts import seed_data
from app.scripts.seed_data import (
    ATTRIBUTES,
    CATEGORIES,
    CONTENT_SECTIONS,
    PRODUCTS,
    AttributeSeed,
    ProductSeed,
)

PRICE_LIST_CODE = "default"
WAREHOUSE_CODE = "main"
REGION_CODE = settings.DEFAULT_REGION_CODE


def _log(message: str) -> None:
    print(message)


# --------------------------------------------------------------- справочники


async def _ensure_region(session: AsyncSession) -> Region:
    region = (
        await session.execute(select(Region).where(Region.code == REGION_CODE))
    ).scalar_one_or_none()
    if region is None:
        region = Region(code=REGION_CODE, name="Алматы", sort_order=0)
        session.add(region)
        await session.flush()
        # Второй регион нужен, чтобы форма заявки показывала настоящий
        # выбор, а не единственный неизменяемый пункт.
        session.add(Region(code="astana", name="Астана", sort_order=1))
        await session.flush()
    return region


async def _ensure_price_list(session: AsyncSession) -> PriceList:
    price_list = (
        await session.execute(select(PriceList).where(PriceList.code == PRICE_LIST_CODE))
    ).scalar_one_or_none()
    if price_list is None:
        price_list = PriceList(
            code=PRICE_LIST_CODE,
            name="Основной прайс",
            currency=settings.DEFAULT_CURRENCY,
            is_default=True,
            is_active=True,
        )
        session.add(price_list)
        await session.flush()
    return price_list


async def _ensure_warehouse(session: AsyncSession, region: Region) -> Warehouse:
    warehouse = (
        await session.execute(select(Warehouse).where(Warehouse.code == WAREHOUSE_CODE))
    ).scalar_one_or_none()
    if warehouse is None:
        warehouse = Warehouse(
            code=WAREHOUSE_CODE, name="Склад Алматы", region_id=region.id, is_active=True
        )
        session.add(warehouse)
        await session.flush()
    return warehouse


# ---------------------------------------------------------------- категории


async def _seed_categories(session: AsyncSession) -> dict[str, Category]:
    existing = {
        category.slug: category
        for category in (await session.execute(select(Category))).scalars().all()
    }
    result: dict[str, Category] = {}

    for item in CATEGORIES:
        category = existing.get(item.slug)
        if category is None:
            parent = result.get(item.parent) if item.parent else None
            category = Category(
                slug=item.slug,
                parent_id=parent.id if parent else None,
                depth=(parent.depth + 1) if parent else 0,
                sort_order=len(result),
                is_active=True,
            )
            session.add(category)
            await session.flush()
            # Материализованный путь строится после получения id.
            category.path = f"{parent.path}.{category.id}" if parent else str(category.id)
            session.add(
                CategoryTranslation(
                    category_id=category.id,
                    locale=settings.DEFAULT_LOCALE,
                    name=item.name,
                    description=item.description,
                )
            )
            await session.flush()
        result[item.slug] = category

    return result


# --------------------------------------------------------------- атрибуты


async def _seed_attributes(
    session: AsyncSession,
) -> tuple[dict[str, Attribute], dict[tuple[str, str], AttributeOption]]:
    attributes: dict[str, Attribute] = {
        item.code: item for item in (await session.execute(select(Attribute))).scalars().all()
    }
    options: dict[tuple[str, str], AttributeOption] = {}

    for spec in ATTRIBUTES:
        attribute = attributes.get(spec.code)
        if attribute is None:
            attribute = _build_attribute(spec)
            session.add(attribute)
            await session.flush()
            attributes[spec.code] = attribute

        existing_options = (
            (
                await session.execute(
                    select(AttributeOption).where(AttributeOption.attribute_id == attribute.id)
                )
            )
            .scalars()
            .all()
        )
        by_slug = {option.slug: option for option in existing_options}
        for index, (slug, label) in enumerate(spec.options):
            option = by_slug.get(slug)
            if option is None:
                option = AttributeOption(
                    attribute_id=attribute.id,
                    slug=slug,
                    value_i18n={settings.DEFAULT_LOCALE: label},
                    sort_order=index,
                )
                session.add(option)
                await session.flush()
            options[(spec.code, slug)] = option

    return attributes, options


def _build_attribute(spec: AttributeSeed) -> Attribute:
    return Attribute(
        code=spec.code,
        name_i18n={settings.DEFAULT_LOCALE: spec.name},
        unit=spec.unit,
        value_type=spec.value_type.value,
        sort_order=spec.sort_order,
        is_visible=True,
        is_active=True,
    )


# ------------------------------------------------------------------ товары


async def _seed_products(
    session: AsyncSession,
    *,
    categories: dict[str, Category],
    attributes: dict[str, Attribute],
    options: dict[tuple[str, str], AttributeOption],
    price_list: PriceList,
    warehouse: Warehouse,
) -> list[Product]:
    existing = {
        product.sku: product for product in (await session.execute(select(Product))).scalars().all()
    }
    created: list[Product] = []

    for spec in PRODUCTS:
        if spec.sku in existing:
            continue
        product = Product(
            sku=spec.sku,
            slug=spec.slug,
            status=ProductStatus.PUBLISHED.value,
            is_active=True,
            is_featured=spec.is_featured,
            unit=spec.unit,
            min_order_qty=spec.min_order_qty,
            pricing_type=spec.pricing_type.value,
            stock_display_override=(
                spec.stock_display_override.value if spec.stock_display_override else None
            ),
            brand=spec.brand,
            specs=dict(spec.specs),
        )
        session.add(product)
        await session.flush()

        session.add(
            ProductTranslation(
                product_id=product.id,
                locale=settings.DEFAULT_LOCALE,
                name=spec.name,
                short_description=spec.short_description,
                description=spec.description,
            )
        )
        session.add(
            ProductCategory(
                product_id=product.id,
                category_id=categories[spec.category].id,
                is_primary=True,
            )
        )
        _add_attribute_values(session, product, spec, attributes, options)
        for tier in spec.tiers:
            session.add(
                PriceTier(
                    product_id=product.id,
                    price_list_id=price_list.id,
                    min_qty=tier.min_qty,
                    max_qty=tier.max_qty,
                    price=tier.price,
                )
            )
        if spec.stock is not None:
            session.add(
                Stock(
                    product_id=product.id,
                    warehouse_id=warehouse.id,
                    quantity=spec.stock,
                    reserved=Decimal("0"),
                )
            )
        await session.flush()
        created.append(product)

    return created


def _add_attribute_values(
    session: AsyncSession,
    product: Product,
    spec: ProductSeed,
    attributes: dict[str, Attribute],
    options: dict[tuple[str, str], AttributeOption],
) -> None:
    for code, raw in spec.attributes.items():
        attribute = attributes[code]
        value_type = AttributeValueType(attribute.value_type)
        value = ProductAttributeValue(product_id=product.id, attribute_id=attribute.id)
        if value_type is AttributeValueType.OPTION:
            value.option_id = options[(code, str(raw))].id
        elif value_type is AttributeValueType.NUMBER:
            value.value_numeric = Decimal(str(raw))
        elif value_type is AttributeValueType.BOOLEAN:
            value.value_bool = bool(raw)
        else:
            value.value_string = str(raw)
        session.add(value)


# --------------------------------------------------------------------- CMS


async def _seed_content(session: AsyncSession) -> int:
    existing = {
        section.key: section
        for section in (await session.execute(select(ContentSection))).scalars().all()
    }
    written = 0
    for raw_key, payload in CONTENT_SECTIONS.items():
        key = ContentSectionKey(raw_key)
        if key.value in existing:
            continue
        # Данные проходят ту же схему, что и запись из админки:
        # демо-набор не может внести в CMS то, чего админка не приняла бы.
        model = SECTION_SCHEMAS[key].model_validate(payload)
        session.add(ContentSection(key=key.value, data=model.model_dump(mode="json")))
        written += 1
    return written


# ------------------------------------------------------------- изображения


def _placeholder_png(sku: str, name: str) -> bytes:
    """Брендированная плашка вместо фотографии.

    Демо-набор не может содержать настоящие снимки товаров, но пустая
    галерея не даёт проверить ни витрину, ни раздачу файлов из MinIO.
    """
    import io

    from PIL import Image, ImageDraw

    width, height = 1200, 900
    image = Image.new("RGB", (width, height), seed_data.PLACEHOLDER_BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, width - 40, height - 40), outline=seed_data.PLACEHOLDER_FG, width=3)
    draw.text((72, 72), "OINAU PRO", fill=seed_data.PLACEHOLDER_FG)
    draw.text((72, 110), sku, fill=(255, 255, 255))
    draw.text((72, 140), name[:48], fill=(160, 178, 200))
    draw.text((72, height - 100), "DEMO IMAGE", fill=(90, 110, 135))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def _seed_images(session: AsyncSession, products: list[Product]) -> int:
    """Прогоняет заглушки через настоящий конвейер медиатеки.

    Файл кладётся в хранилище и обрабатывается тем же сервисом, что
    и загрузка из админки: если варианты собрались и статус стал READY,
    значит локальные MinIO, политика бакета и CDN-URL настроены верно.
    """
    from app.infrastructure.storage.s3 import get_object_storage

    storage = get_object_storage()
    created = 0

    for product in products:
        media_uuid = uuid.uuid4()
        key = build_original_key(MediaPurpose.PRODUCT, media_uuid, "image/png")
        data = _placeholder_png(product.sku, product.slug)
        await storage.write(key, data, content_type="image/png")

        media = MediaFile(
            uuid=media_uuid,
            storage_key=key,
            bucket=settings.S3_BUCKET,
            mime_type="image/png",
            size_bytes=len(data),
            original_filename=f"{product.sku}.png",
            status=MediaStatus.PROCESSING.value,
        )
        session.add(media)
        await session.flush()

        session.add(
            ProductImage(
                product_id=product.id,
                media_file_id=media.id,
                kind=ImageKind.PHOTO.value,
                sort_order=0,
                is_main=True,
                alt_i18n={settings.DEFAULT_LOCALE: f"{product.sku} — демонстрационное изображение"},
            )
        )
        await session.commit()

        status = await MediaProcessingService(session, storage=storage).process(media.id)
        if status == MediaStatus.READY.value:
            created += 1
        else:
            _log(f"  изображение {product.sku}: статус {status}")

    return created


# ------------------------------------------------------------------ сброс


async def _reset(session: AsyncSession) -> None:
    """Удаляет демо-набор целиком, чтобы загрузить его заново.

    Затрагивает только объекты, созданные этим скриптом: товары с
    известными артикулами, их категории и разделы CMS. Заявки, файлы
    в хранилище и пользователи не трогаются.
    """
    skus = [item.sku for item in PRODUCTS]
    slugs = [item.slug for item in CATEGORIES]

    product_ids = list(
        (await session.execute(select(Product.id).where(Product.sku.in_(skus)))).scalars().all()
    )
    if product_ids:
        media_ids = list(
            (
                await session.execute(
                    select(ProductImage.media_file_id).where(
                        ProductImage.product_id.in_(product_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        await session.execute(delete(ProductImage).where(ProductImage.product_id.in_(product_ids)))
        if media_ids:
            await session.execute(delete(MediaFile).where(MediaFile.id.in_(media_ids)))
        await session.execute(delete(Product).where(Product.id.in_(product_ids)))

    await session.execute(delete(Category).where(Category.slug.in_(slugs)))
    await session.execute(
        delete(ContentSection).where(ContentSection.key.in_(list(CONTENT_SECTIONS)))
    )
    await session.commit()
    _log("Демо-набор удалён")


# ------------------------------------------------------------------- запуск


async def seed(*, reset: bool, with_images: bool) -> int:
    from app.db.session import SessionFactory, dispose_engine

    try:
        async with SessionFactory() as session:
            if reset:
                await _reset(session)

            region = await _ensure_region(session)
            price_list = await _ensure_price_list(session)
            warehouse = await _ensure_warehouse(session, region)
            categories = await _seed_categories(session)
            attributes, options = await _seed_attributes(session)
            products = await _seed_products(
                session,
                categories=categories,
                attributes=attributes,
                options=options,
                price_list=price_list,
                warehouse=warehouse,
            )
            sections = await _seed_content(session)
            await session.commit()

            _log(f"Категорий: {len(categories)}")
            _log(f"Товаров добавлено: {len(products)}")
            _log(f"Разделов CMS добавлено: {sections}")

            if with_images and products:
                try:
                    ready = await _seed_images(session, products)
                    _log(f"Изображений готово: {ready}")
                except Exception as exc:
                    # Отсутствие MinIO не должно ронять загрузку данных.
                    await session.rollback()
                    _log(
                        "Изображения пропущены: хранилище недоступно "
                        f"({type(exc).__name__}). Каталог покажет заглушки."
                    )
    finally:
        await dispose_engine()

    _log("Готово. Откройте http://localhost:3000")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Демо-данные для локальной разработки")
    parser.add_argument("--reset", action="store_true", help="Удалить демо-набор перед загрузкой")
    parser.add_argument("--no-images", action="store_true", help="Не создавать изображения")
    args = parser.parse_args()

    if settings.is_production:
        print("Демо-данные нельзя загружать в production", file=sys.stderr)
        return 1

    configure_logging()
    return asyncio.run(seed(reset=args.reset, with_images=not args.no_images))


if __name__ == "__main__":
    raise SystemExit(main())
