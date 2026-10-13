"""Круговой тест: каталог -> экспорт -> предпросмотр -> подтверждение.

Главная гарантия формата: выгруженный файл возвращается импортом без
ручного преобразования, и возврат неизменённого файла не меняет
в каталоге ничего — ни одной строки, ни одной записи аудита о товаре.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.audit.models import AuditLog
from app.modules.catalog.models import (
    Attribute,
    AttributeOption,
    Category,
    CategoryAttribute,
    CategoryTranslation,
    Product,
    ProductAttributeValue,
    ProductCategory,
    ProductTranslation,
)
from app.modules.inventory.models import Stock
from app.modules.pricing.models import PriceList, PriceTier
from tests.conftest import Headers
from tests.import_helpers import (
    EXPORT,
    PUBLIC_PRODUCTS,
    Sheet,
    append_row,
    commit_url,
    edit_workbook,
    preview,
    read_sheet,
    set_cell,
    upload,
)


async def catalog_state(session: AsyncSession) -> dict[str, Any]:
    """Снимок каталога только через колонки — без объектов identity map."""
    state: dict[str, Any] = {}
    state["products"] = sorted(
        (
            await session.execute(
                select(
                    Product.sku,
                    Product.slug,
                    Product.status,
                    Product.is_active,
                    Product.is_featured,
                    Product.unit,
                    Product.min_order_qty,
                    Product.brand,
                    Product.external_id,
                    Product.pricing_type,
                    Product.specs,
                    Product.deleted_at.is_(None),
                )
            )
        ).all(),
        key=str,
    )
    state["product_translations"] = sorted(
        (
            await session.execute(
                select(
                    Product.sku,
                    ProductTranslation.locale,
                    ProductTranslation.name,
                    ProductTranslation.short_description,
                    ProductTranslation.description,
                    ProductTranslation.seo_title,
                    ProductTranslation.seo_description,
                ).join(Product, Product.id == ProductTranslation.product_id)
            )
        ).all(),
        key=str,
    )
    state["product_categories"] = sorted(
        (
            await session.execute(
                select(
                    Product.sku,
                    Category.slug,
                    ProductCategory.is_primary,
                    ProductCategory.sort_order,
                )
                .join(Product, Product.id == ProductCategory.product_id)
                .join(Category, Category.id == ProductCategory.category_id)
            )
        ).all(),
        key=str,
    )
    state["product_values"] = sorted(
        (
            await session.execute(
                select(
                    Product.sku,
                    Attribute.code,
                    ProductAttributeValue.value_string,
                    ProductAttributeValue.value_numeric,
                    ProductAttributeValue.value_bool,
                    AttributeOption.slug,
                )
                .join(Product, Product.id == ProductAttributeValue.product_id)
                .join(Attribute, Attribute.id == ProductAttributeValue.attribute_id)
                .outerjoin(AttributeOption, AttributeOption.id == ProductAttributeValue.option_id)
            )
        ).all(),
        key=str,
    )
    state["tiers"] = sorted(
        (
            await session.execute(
                select(
                    Product.sku,
                    PriceList.code,
                    PriceTier.min_qty,
                    PriceTier.max_qty,
                    PriceTier.price,
                )
                .join(Product, Product.id == PriceTier.product_id)
                .join(PriceList, PriceList.id == PriceTier.price_list_id)
            )
        ).all(),
        key=str,
    )
    parent = aliased(Category)
    state["categories"] = sorted(
        (
            await session.execute(
                select(
                    Category.slug,
                    parent.slug,
                    Category.path,
                    Category.depth,
                    Category.sort_order,
                    Category.is_active,
                    Category.external_id,
                    Category.deleted_at.is_(None),
                ).outerjoin(parent, parent.id == Category.parent_id)
            )
        ).all(),
        key=str,
    )
    state["category_translations"] = sorted(
        (
            await session.execute(
                select(
                    Category.slug,
                    CategoryTranslation.locale,
                    CategoryTranslation.name,
                    CategoryTranslation.description,
                    CategoryTranslation.seo_title,
                    CategoryTranslation.seo_description,
                ).join(Category, Category.id == CategoryTranslation.category_id)
            )
        ).all(),
        key=str,
    )
    state["category_attributes"] = sorted(
        (
            await session.execute(
                select(
                    Category.slug,
                    Attribute.code,
                    CategoryAttribute.sort_order,
                    CategoryAttribute.is_required,
                )
                .join(Category, Category.id == CategoryAttribute.category_id)
                .join(Attribute, Attribute.id == CategoryAttribute.attribute_id)
            )
        ).all(),
        key=str,
    )
    state["attributes"] = sorted(
        (
            await session.execute(
                select(
                    Attribute.code,
                    Attribute.value_type,
                    Attribute.unit,
                    Attribute.is_filterable,
                    Attribute.is_visible,
                    Attribute.is_active,
                    Attribute.sort_order,
                    Attribute.name_i18n,
                )
            )
        ).all(),
        key=str,
    )
    state["options"] = sorted(
        (
            await session.execute(
                select(
                    Attribute.code,
                    AttributeOption.slug,
                    AttributeOption.sort_order,
                    AttributeOption.value_i18n,
                ).join(Attribute, Attribute.id == AttributeOption.attribute_id)
            )
        ).all(),
        key=str,
    )
    state["stocks"] = sorted(
        (
            await session.execute(
                select(Product.sku, Stock.quantity).join(Product, Product.id == Stock.product_id)
            )
        ).all(),
        key=str,
    )
    return state


def sheet_data(data: bytes) -> dict[str, list[dict[str, Any]]]:
    return {sheet.value: read_sheet(data, sheet.value) for sheet in Sheet}


async def test_unchanged_export_roundtrip_is_a_no_op(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    before = await catalog_state(committed_session)

    exported = await api.get(EXPORT, headers=admin)
    assert exported.status_code == 200
    data = exported.content

    report = await preview(api, admin, data)
    assert report["valid"], report["errors"]
    assert report["error_count"] == 0
    summary = report["summary"]
    # Удалённый товар DEL-1 не выгружается: 5 живых товаров.
    assert summary["products"] == {"create": 0, "update": 0, "unchanged": 5}
    assert summary["categories"] == {"create": 0, "update": 0, "unchanged": 4}
    assert summary["attributes"] == {"create": 0, "update": 0, "unchanged": 4}
    assert summary["attribute_options"] == {"create": 0, "update": 0, "unchanged": 1}
    assert report["changes"] == []

    committed = await upload(api, commit_url(report["job"]["uuid"]), admin, data)
    assert committed.status_code == 200, committed.text
    assert committed.json()["job"]["status"] == "COMMITTED"

    committed_session.expire_all()
    after = await catalog_state(committed_session)
    assert after == before

    # Ни одного события об изменении товара — только события самого импорта.
    actions = set(
        (
            await committed_session.execute(
                select(AuditLog.action).where(AuditLog.action.not_like("auth.%"))
            )
        )
        .scalars()
        .all()
    )
    assert actions == {"catalog_import.previewed", "catalog_import.committed"}

    # Повторная выгрузка совпадает с первой построчно.
    again = await api.get(EXPORT, headers=admin)
    assert sheet_data(again.content) == sheet_data(data)


async def test_edited_export_roundtrip_applies_only_edits(
    api: AsyncClient, admin: Headers, catalog, committed_session: AsyncSession
) -> None:
    before = await catalog_state(committed_session)
    data = (await api.get(EXPORT, headers=admin)).content

    def edit(workbook: Any) -> None:
        # правка существующего товара: название и одна ступень цены
        set_cell(workbook, "Products", ("sku", "KRP-M10"), "name_ru", "Крепление М10 (новое)")
        set_cell(workbook, "Prices", ("sku", "KRP-M10"), "price", 1350.5)
        # новый товар с ценой, категорией и характеристикой
        append_row(
            workbook,
            "Products",
            {
                "sku": "NEW-100",
                "slug": "novyj-tovar",
                "name_ru": "Новый товар",
                "status": "PUBLISHED",
                "is_active": True,
                "is_featured": False,
                "categories": "krepleniya; kanaty",
                "unit": "m",
                "min_order_qty": 2.5,
                "pricing_type": "FROM",
            },
        )
        append_row(
            workbook, "Prices", {"sku": "NEW-100", "min_qty": 1, "max_qty": 9, "price": 99.99}
        )
        append_row(
            workbook, "Prices", {"sku": "NEW-100", "min_qty": 10, "max_qty": None, "price": 89.5}
        )
        append_row(
            workbook,
            "ProductAttributes",
            {"sku": "NEW-100", "attribute_code": "diameter", "value": 12.5},
        )

    edited = edit_workbook(data, edit)
    report = await preview(api, admin, edited)
    assert report["valid"], report["errors"]
    assert report["summary"]["products"] == {"create": 1, "update": 1, "unchanged": 4}
    changes = {item["sku"]: item for item in report["changes"]}
    assert changes["NEW-100"]["action"] == "create"
    assert changes["KRP-M10"]["action"] == "update"
    assert changes["KRP-M10"]["changed"] == ["translations", "pricing"]

    committed = await upload(api, commit_url(report["job"]["uuid"]), admin, edited)
    assert committed.status_code == 200, committed.text

    committed_session.expire_all()
    after = await catalog_state(committed_session)

    # Изменились только правленые товары.
    untouched = {"KAN-16-PP", "SID-01", "DRAFT-1", "OFF-1", "DEL-1"}
    for key in ("products", "product_translations", "product_categories", "product_values"):
        assert [row for row in after[key] if row[0] in untouched] == [
            row for row in before[key] if row[0] in untouched
        ]
    assert [row for row in after["tiers"] if row[0] in untouched] == [
        row for row in before["tiers"] if row[0] in untouched
    ]
    assert after["stocks"] == before["stocks"]
    assert after["categories"] == before["categories"]

    fastener = (await api.get(f"{PUBLIC_PRODUCTS}/kreplenie-m10")).json()
    assert fastener["name"] == "Крепление М10 (новое)"
    assert Decimal(fastener["price"]["price"]) == Decimal("1350.50")

    created = (await api.get(f"{PUBLIC_PRODUCTS}/novyj-tovar")).json()
    assert created["price"]["type"] == "FROM"
    assert Decimal(created["price"]["from_price"]) == Decimal("89.50")
    assert Decimal(created["min_order_qty"]) == Decimal("2.5")

    # Повторная выгрузка содержит правки — круг замкнулся.
    again = read_sheet((await api.get(EXPORT, headers=admin)).content, "Prices")
    new_tiers = [
        (row["min_qty"], row["max_qty"], row["price"]) for row in again if row["sku"] == "NEW-100"
    ]
    assert new_tiers == [(1, 9, 99.99), (10, None, 89.5)]
