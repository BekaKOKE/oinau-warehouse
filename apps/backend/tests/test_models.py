"""Тесты ограничений схемы.

Проверяется не работа SQLAlchemy, а то, что БД сама защищает данные:
эти ограничения должны срабатывать и при импорте из Excel, и при
будущем обмене с 1С, где кода приложения в цепочке нет.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.enums import AttributeValueType, ProductStatus
from app.modules.catalog.models import (
    Attribute,
    AttributeOption,
    Category,
    Product,
    ProductAttributeValue,
    ProductCategory,
    ProductTranslation,
)
from app.modules.inventory.models import Stock, Warehouse
from app.modules.pricing.enums import PricingType
from app.modules.pricing.models import PriceTier
from app.modules.requests.models import RequestItem
from app.modules.users.enums import UserRole
from app.modules.users.models import User
from tests.factories import (
    make_category,
    make_price_list,
    make_product,
    make_request,
    make_request_item,
    unique,
)


# ---------------------------------------------------------------- каталог
async def test_sku_is_unique(db: AsyncSession) -> None:
    sku = unique("SKU")
    await make_product(db, sku=sku)
    with pytest.raises(IntegrityError):
        await make_product(db, sku=sku)


async def test_soft_deleted_product_releases_sku(db: AsyncSession) -> None:
    """Частичный уникальный индекс: удалённый товар не блокирует артикул.

    Иначе повторное заведение позиции с тем же артикулом после ошибки
    оператора было бы невозможно без ручной правки базы.
    """
    sku = unique("SKU")
    product = await make_product(db, sku=sku)
    product.deleted_at = datetime.now(UTC)
    await db.flush()

    replacement = await make_product(db, sku=sku)
    assert replacement.id != product.id


async def test_product_slug_is_unique(db: AsyncSession) -> None:
    slug = unique("kanat")
    await make_product(db, slug=slug)
    with pytest.raises(IntegrityError):
        await make_product(db, slug=slug)


async def test_category_slug_is_unique(db: AsyncSession) -> None:
    slug = unique("kanaty")
    await make_category(db, slug=slug)
    with pytest.raises(IntegrityError):
        await make_category(db, slug=slug)


async def test_category_tree_relation(db: AsyncSession) -> None:
    """Дерево произвольной глубины, а не два уровня."""
    root = await make_category(db, path="1", depth=0)
    child = await make_category(db, parent_id=root.id, path=f"{root.id}.2", depth=1)
    grandchild = await make_category(db, parent_id=child.id, path=f"{root.id}.{child.id}", depth=2)

    await db.refresh(root)
    loaded = await db.get(Category, grandchild.id)
    assert loaded is not None
    assert loaded.parent_id == child.id
    assert loaded.depth == 2


async def test_category_cannot_be_its_own_parent(db: AsyncSession) -> None:
    category = await make_category(db)
    with pytest.raises(IntegrityError):
        await db.execute(
            text("UPDATE categories SET parent_id = :cid WHERE id = :cid"), {"cid": category.id}
        )
        await db.flush()


async def test_product_translation_is_unique_per_locale(db: AsyncSession) -> None:
    product = await make_product(db)  # фабрика уже создала перевод 'ru'
    db.add(ProductTranslation(product_id=product.id, locale="ru", name="Дубль"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_second_locale_is_allowed(db: AsyncSession) -> None:
    """Казахская версия добавляется без изменения схемы."""
    product = await make_product(db)
    db.add(ProductTranslation(product_id=product.id, locale="kk", name="Полипропилен арқаны"))
    await db.flush()

    rows = (
        (
            await db.execute(
                select(ProductTranslation).where(ProductTranslation.product_id == product.id)
            )
        )
        .scalars()
        .all()
    )
    assert {row.locale for row in rows} == {"ru", "kk"}


async def test_search_vector_is_generated(db: AsyncSession) -> None:
    """Генерируемая колонка заполняется самой БД, без триггеров и кода."""
    product = await make_product(db)
    vector = (
        await db.execute(
            text("SELECT search_vector::text FROM product_translations WHERE product_id = :pid"),
            {"pid": product.id},
        )
    ).scalar_one()
    assert "канат" in vector.lower()


async def test_only_one_primary_category(db: AsyncSession) -> None:
    product = await make_product(db)
    first = await make_category(db)
    second = await make_category(db)

    db.add(ProductCategory(product_id=product.id, category_id=first.id, is_primary=True))
    await db.flush()
    db.add(ProductCategory(product_id=product.id, category_id=second.id, is_primary=True))
    with pytest.raises(IntegrityError):
        await db.flush()


# ------------------------------------------------------------ характеристики
async def test_attribute_value_requires_exactly_one_value(db: AsyncSession) -> None:
    product = await make_product(db)
    attribute = Attribute(code=unique("diameter"), value_type=AttributeValueType.NUMBER.value)
    db.add(attribute)
    await db.flush()

    # Заполнены две колонки значения одновременно
    db.add(
        ProductAttributeValue(
            product_id=product.id,
            attribute_id=attribute.id,
            value_numeric=Decimal("16"),
            value_string="16 мм",
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_product_can_have_several_options_of_one_attribute(db: AsyncSession) -> None:
    """Товар бывает в нескольких цветах — но дубль того же цвета запрещён."""
    product = await make_product(db)
    attribute = Attribute(code=unique("color"), value_type=AttributeValueType.OPTION.value)
    db.add(attribute)
    await db.flush()
    red = AttributeOption(attribute_id=attribute.id, slug="red")
    blue = AttributeOption(attribute_id=attribute.id, slug="blue")
    db.add_all([red, blue])
    await db.flush()

    db.add(
        ProductAttributeValue(product_id=product.id, attribute_id=attribute.id, option_id=red.id)
    )
    db.add(
        ProductAttributeValue(product_id=product.id, attribute_id=attribute.id, option_id=blue.id)
    )
    await db.flush()

    db.add(
        ProductAttributeValue(product_id=product.id, attribute_id=attribute.id, option_id=red.id)
    )
    with pytest.raises(IntegrityError):
        await db.flush()


# ------------------------------------------------------------------- цены
async def test_price_is_exact_numeric(db: AsyncSession) -> None:
    """Деньги не теряют копейки: NUMERIC, а не float."""
    product = await make_product(db)
    price_list = await make_price_list(db)
    db.add(
        PriceTier(
            product_id=product.id,
            price_list_id=price_list.id,
            min_qty=Decimal("1"),
            price=Decimal("3500.55"),
        )
    )
    await db.flush()

    stored = (
        await db.execute(select(PriceTier.price).where(PriceTier.product_id == product.id))
    ).scalar_one()
    assert isinstance(stored, Decimal)
    assert stored == Decimal("3500.55")
    assert stored * 3 == Decimal("10501.65")


async def test_adjacent_tiers_are_allowed(db: AsyncSession) -> None:
    """Ступени 1–9, 10–49, 50–99, 100+ не считаются пересекающимися."""
    product = await make_product(db, pricing_type=PricingType.TIERED.value)
    price_list = await make_price_list(db)
    tiers = [
        (Decimal("1"), Decimal("9"), Decimal("3500")),
        (Decimal("10"), Decimal("49"), Decimal("3200")),
        (Decimal("50"), Decimal("99"), Decimal("2900")),
        (Decimal("100"), None, Decimal("2600")),
    ]
    for min_qty, max_qty, price in tiers:
        db.add(
            PriceTier(
                product_id=product.id,
                price_list_id=price_list.id,
                min_qty=min_qty,
                max_qty=max_qty,
                price=price,
            )
        )
    await db.flush()

    count = (
        await db.execute(
            text("SELECT count(*) FROM price_tiers WHERE product_id = :pid"), {"pid": product.id}
        )
    ).scalar_one()
    assert count == 4


async def test_overlapping_tiers_are_rejected(db: AsyncSession) -> None:
    """EXCLUDE-ограничение: база не даёт создать двусмысленную цену."""
    product = await make_product(db)
    price_list = await make_price_list(db)
    db.add(
        PriceTier(
            product_id=product.id,
            price_list_id=price_list.id,
            min_qty=Decimal("1"),
            max_qty=Decimal("50"),
            price=Decimal("3500"),
        )
    )
    await db.flush()

    db.add(
        PriceTier(
            product_id=product.id,
            price_list_id=price_list.id,
            min_qty=Decimal("40"),
            max_qty=Decimal("100"),
            price=Decimal("3200"),
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_same_range_allowed_in_different_price_lists(db: AsyncSession) -> None:
    """Ограничение действует внутри прайс-листа, а не глобально."""
    product = await make_product(db)
    retail = await make_price_list(db)
    dealer = await make_price_list(db)

    for price_list in (retail, dealer):
        db.add(
            PriceTier(
                product_id=product.id,
                price_list_id=price_list.id,
                min_qty=Decimal("1"),
                max_qty=Decimal("50"),
                price=Decimal("3500"),
            )
        )
    await db.flush()


async def test_on_request_product_has_no_price_rows(db: AsyncSession) -> None:
    """'Цена по запросу' — отсутствие строк, а не цена 0."""
    product = await make_product(db, pricing_type=PricingType.ON_REQUEST.value)
    count = (
        await db.execute(
            text("SELECT count(*) FROM price_tiers WHERE product_id = :pid"), {"pid": product.id}
        )
    ).scalar_one()
    assert count == 0
    assert product.pricing_type == PricingType.ON_REQUEST.value


# ---------------------------------------------------------------- остатки
async def test_quantity_keeps_fractional_precision(db: AsyncSession) -> None:
    """Канат меряется метрами: 12.5 м должно храниться как 12.5, а не 12."""
    product = await make_product(db, unit="m")
    warehouse = Warehouse(code=unique("wh"), name="Основной склад")
    db.add(warehouse)
    await db.flush()

    db.add(Stock(product_id=product.id, warehouse_id=warehouse.id, quantity=Decimal("12.500")))
    await db.flush()

    stored = (
        await db.execute(select(Stock.quantity).where(Stock.product_id == product.id))
    ).scalar_one()
    assert isinstance(stored, Decimal)
    assert stored == Decimal("12.500")


async def test_stock_is_unique_per_product_and_warehouse(db: AsyncSession) -> None:
    product = await make_product(db)
    warehouse = Warehouse(code=unique("wh"), name="Основной склад")
    db.add(warehouse)
    await db.flush()

    db.add(Stock(product_id=product.id, warehouse_id=warehouse.id, quantity=Decimal("10")))
    await db.flush()
    db.add(Stock(product_id=product.id, warehouse_id=warehouse.id, quantity=Decimal("5")))
    with pytest.raises(IntegrityError):
        await db.flush()


# ---------------------------------------------------------------- заявки
async def test_request_with_items(db: AsyncSession) -> None:
    product = await make_product(db)
    request = await make_request(db)
    await make_request_item(db, request, product, quantity=Decimal("25.500"))

    items = (
        (await db.execute(select(RequestItem).where(RequestItem.request_id == request.id)))
        .scalars()
        .all()
    )
    assert len(items) == 1
    assert items[0].quantity == Decimal("25.500")


async def test_item_snapshot_survives_product_removal(db: AsyncSession) -> None:
    """Ключевая проверка: заявка переживает удаление товара.

    Через полгода товар переименуют или снимут с производства — состав
    заявки обязан показывать то, что видел клиент.
    """
    product = await make_product(db, sku="KAN-16-PP-TEST")
    request = await make_request(db)
    await make_request_item(
        db,
        request,
        product,
        sku_snapshot=product.sku,
        name_snapshot="Канат 16 мм",
        unit_price_snapshot=Decimal("3500.00"),
        line_total_snapshot=Decimal("35000.00"),
    )

    item = (
        await db.execute(select(RequestItem).where(RequestItem.request_id == request.id))
    ).scalar_one()

    await db.execute(text("DELETE FROM products WHERE id = :pid"), {"pid": product.id})
    await db.flush()
    await db.refresh(item)
    assert item.product_id is None  # ссылка обнулилась
    assert item.sku_snapshot == "KAN-16-PP-TEST"  # снимок остался
    assert item.name_snapshot == "Канат 16 мм"
    assert item.unit_price_snapshot == Decimal("3500.00")


async def test_request_number_is_unique(db: AsyncSession) -> None:
    number = unique("R")
    await make_request(db, number=number)
    with pytest.raises(IntegrityError):
        await make_request(db, number=number)


async def test_idempotency_key_prevents_duplicates(db: AsyncSession) -> None:
    """Двойной клик и ретрай сети не создают вторую заявку."""
    key = unique("idem")
    await make_request(db, idempotency_key=key)
    with pytest.raises(IntegrityError):
        await make_request(db, idempotency_key=key)


async def test_several_requests_without_idempotency_key(db: AsyncSession) -> None:
    """NULL не конфликтует с NULL — заявки из админки ключа не имеют."""
    await make_request(db)
    await make_request(db)


async def test_bin_format_is_validated(db: AsyncSession) -> None:
    await make_request(db, bin="123456789012")
    with pytest.raises(IntegrityError):
        await make_request(db, bin="12345")


async def test_unknown_request_status_is_rejected(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await make_request(db, status="TOTALLY_UNKNOWN")


# ------------------------------------------------- пользователи и soft delete
async def test_user_email_is_case_insensitive(db: AsyncSession) -> None:
    """CITEXT: Ivan@ и ivan@ — один и тот же пользователь."""
    email = f"{unique('ivan')}@oinau-pro.kz"
    db.add(
        User(
            email=email,
            password_hash="argon2-hash",
            full_name="Иван",
            role=UserRole.MANAGER.value,
        )
    )
    await db.flush()

    db.add(
        User(
            email=email.upper(),
            password_hash="argon2-hash",
            full_name="Иван-дубль",
            role=UserRole.MANAGER.value,
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_unknown_role_is_rejected(db: AsyncSession) -> None:
    db.add(
        User(
            email=f"{unique('x')}@oinau-pro.kz",
            password_hash="h",
            full_name="X",
            role="ROOT",
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_soft_deleted_rows_remain_readable(db: AsyncSession) -> None:
    """Мягкое удаление не теряет данные — строка остаётся в таблице."""
    product = await make_product(db)
    product.deleted_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(product)

    loaded = await db.get(Product, product.id)
    assert loaded is not None
    assert loaded.deleted_at is not None
    assert loaded.status == ProductStatus.PUBLISHED.value


# --------------------------------------------------------------- external_id
async def test_external_id_is_unique_when_present(db: AsyncSession) -> None:
    """Один товар 1С не может быть сопоставлен двум карточкам."""
    guid = unique("1c-guid")
    await make_product(db, external_id=guid)
    with pytest.raises(IntegrityError):
        await make_product(db, external_id=guid)


async def test_many_products_without_external_id(db: AsyncSession) -> None:
    """До интеграции с 1С external_id пуст у всех товаров."""
    await make_product(db)
    await make_product(db)
    await make_product(db)


async def test_sync_source_defaults_to_manual(db: AsyncSession) -> None:
    product = await make_product(db)
    await db.refresh(product)
    assert product.sync_source == "manual"
    assert product.synced_at is None
