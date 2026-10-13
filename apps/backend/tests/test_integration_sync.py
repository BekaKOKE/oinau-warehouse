"""Обмен с учётной системой: товары, цены, остатки, заявки.

Ключевые свойства, которые проверяются здесь:
  * сопоставление только по external_id и sku, никогда по названию;
  * Decimal без потерь на float;
  * частичный успех: битая строка не отменяет пакет;
  * идемпотентность и защита от повторной отправки;
  * отсутствие в пакете НЕ означает удаление.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.catalog.models import Product, ProductTranslation
from app.modules.inventory.models import Stock, Warehouse
from app.modules.notifications.models import SyncLog
from app.modules.pricing.models import PriceTier
from tests.catalog_fixtures import CatalogFixture
from tests.integration_helpers import (
    INVENTORY_URL,
    PRICING_URL,
    PRODUCTS_URL,
    REQUESTS_URL,
    auth_headers,
    make_api_key,
)
from tests.request_helpers import PUBLIC_REQUESTS, request_payload

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def integration_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "ONE_C_INTEGRATION_ENABLED", True)
    monkeypatch.setattr(settings, "INTEGRATION_IP_ALLOWLIST", [])


@pytest.fixture
async def api_key(committed_session: AsyncSession):
    return await make_api_key(committed_session)


# populate_existing вместо expire_all(): expire_all сбрасывает и объекты
# фикстуры каталога, после чего обращение к ним пытается лениво
# подгрузиться — в асинхронной сессии это ошибка.
async def load_product(session: AsyncSession, sku: str) -> Product:
    return (
        await session.execute(
            select(Product).where(Product.sku == sku).execution_options(populate_existing=True)
        )
    ).scalar_one()


async def load_stock(session: AsyncSession, product_id: int, warehouse_id: int) -> Stock | None:
    return (
        await session.execute(
            select(Stock)
            .where(Stock.product_id == product_id, Stock.warehouse_id == warehouse_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


class TestProductSync:
    async def test_обновляет_товар_по_артикулу_и_проставляет_guid(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        response = await api.post(
            PRODUCTS_URL,
            json={
                "items": [
                    {
                        "sku": "KAN-16-PP",
                        "external_id": "1c-guid-0001",
                        "unit": "m",
                        "min_order_qty": "2.500",
                    }
                ]
            },
            headers=auth_headers(),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["received"] == 1
        assert body["updated"] == 1
        assert body["rows"][0]["status"] == "updated"

        product = await load_product(committed_session, "KAN-16-PP")
        assert product.external_id == "1c-guid-0001"
        assert product.min_order_qty == Decimal("2.500")
        assert product.sync_source == "1c"
        assert product.synced_at is not None

    async def test_дальше_товар_находится_по_guid_даже_если_артикул_сменился(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        """GUID стабилен, артикул переименовывают — приоритет у GUID."""
        product = await load_product(committed_session, "KAN-16-PP")
        product.external_id = "1c-guid-0001"
        await committed_session.commit()

        response = await api.post(
            PRODUCTS_URL,
            json={
                "items": [{"external_id": "1c-guid-0001", "sku": "ДРУГОЙ", "brand": "Канатторг"}]
            },
            headers=auth_headers(),
        )

        assert response.json()["updated"] == 1
        assert (await load_product(committed_session, "KAN-16-PP")).brand == "Канатторг"

    async def test_неизвестный_товар_пропускается_а_не_создаётся(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        """Обмен не заводит товары: у них нет slug, описания и картинок."""
        before = len((await committed_session.execute(select(Product))).scalars().all())

        response = await api.post(
            PRODUCTS_URL,
            json={"items": [{"sku": "НЕТ-ТАКОГО", "unit": "pcs"}]},
            headers=auth_headers(),
        )

        body = response.json()
        assert body["skipped"] == 1
        assert body["rows"][0]["code"] == "product_not_found"
        after = len((await committed_session.execute(select(Product))).scalars().all())
        assert after == before

    async def test_название_обменом_не_переписывается(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        """Название живёт в переводах: пока нет контракта — не трогаем."""
        await api.post(
            PRODUCTS_URL,
            json={"items": [{"sku": "KAN-16-PP", "name": "ИМЯ ИЗ 1С"}]},
            headers=auth_headers(),
        )

        names = (
            (
                await committed_session.execute(
                    select(ProductTranslation.name)
                    .join(Product, Product.id == ProductTranslation.product_id)
                    .where(Product.sku == "KAN-16-PP")
                )
            )
            .scalars()
            .all()
        )
        assert "ИМЯ ИЗ 1С" not in names

    async def test_пустое_поле_означает_не_менять(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        before = await load_product(committed_session, "KAN-16-PP")
        original_unit, original_active = before.unit, before.is_active

        await api.post(
            PRODUCTS_URL,
            json={"items": [{"sku": "KAN-16-PP", "brand": "Только бренд"}]},
            headers=auth_headers(),
        )

        product = await load_product(committed_session, "KAN-16-PP")
        assert product.unit == original_unit
        assert product.is_active == original_active

    async def test_отключение_товара_требует_явного_признака(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        await api.post(
            PRODUCTS_URL,
            json={"items": [{"sku": "KAN-16-PP", "is_active": False}]},
            headers=auth_headers(),
        )

        assert (await load_product(committed_session, "KAN-16-PP")).is_active is False

    async def test_повторный_пакет_ничего_не_меняет(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        """Идемпотентность: та же выгрузка не создаёт изменений."""
        body = {"items": [{"sku": "KAN-16-PP", "unit": "m"}]}

        first = await api.post(PRODUCTS_URL, json=body, headers=auth_headers())
        second = await api.post(PRODUCTS_URL, json=body, headers=auth_headers())

        assert first.json()["duplicate"] is False
        # Тот же пакет узнан по контрольной сумме — прежний итог.
        assert second.json()["duplicate"] is True
        assert second.json()["sync_uuid"] == first.json()["sync_uuid"]

    async def test_строка_без_идентификатора_отклоняется_валидацией(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        """Сопоставления по названию нет и не будет."""
        response = await api.post(
            PRODUCTS_URL, json={"items": [{"name": "Канат 16 мм"}]}, headers=auth_headers()
        )

        assert response.status_code == 422

    async def test_лишнее_поле_ломает_обмен_громко(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        """Молча проигнорированное поле — это цена, которая не обновилась."""
        response = await api.post(
            PRODUCTS_URL,
            json={"items": [{"sku": "KAN-16-PP", "цена": "100"}]},
            headers=auth_headers(),
        )

        assert response.status_code == 422

    async def test_изменение_попадает_в_аудит_как_действие_1с(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        """История товара читается одинаково, каким бы каналом его ни меняли."""
        await api.post(
            PRODUCTS_URL,
            json={"items": [{"sku": "KAN-16-PP", "brand": "Из 1С"}]},
            headers=auth_headers(),
        )

        entries = (
            (
                await committed_session.execute(
                    select(AuditLog).where(AuditLog.action == "catalog.product_updated")
                )
            )
            .scalars()
            .all()
        )
        assert entries
        assert entries[-1].actor == "1c"
        assert "brand" in entries[-1].changes


class TestPriceSync:
    async def test_ступени_заменяются_целиком_и_остаются_decimal(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        response = await api.post(
            PRICING_URL,
            json={
                "items": [
                    {
                        "sku": "KAN-16-PP",
                        "tiers": [
                            {"min_qty": "1", "max_qty": "49", "price": "3200.55"},
                            {"min_qty": "50", "price": "2900.10"},
                        ],
                    }
                ]
            },
            headers=auth_headers(),
        )

        assert response.status_code == 200
        assert response.json()["updated"] == 1

        product = await load_product(committed_session, "KAN-16-PP")
        tiers = (
            (
                await committed_session.execute(
                    select(PriceTier)
                    .where(PriceTier.product_id == product.id)
                    .order_by(PriceTier.min_qty)
                )
            )
            .scalars()
            .all()
        )
        default_tiers = [
            tier for tier in tiers if tier.price_list_id == catalog.public_price_list.id
        ]
        assert [(t.min_qty, t.max_qty, t.price) for t in default_tiers] == [
            (Decimal("1.000"), Decimal("49.000"), Decimal("3200.55")),
            (Decimal("50.000"), None, Decimal("2900.10")),
        ]
        # Ни одной копейки не потеряно на float.
        assert all(isinstance(tier.price, Decimal) for tier in default_tiers)
        assert all(tier.sync_source == "1c" for tier in default_tiers)

    async def test_пересекающиеся_ступени_отбраковываются_до_записи(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        """Иначе пакет упал бы целиком на EXCLUDE-ограничении базы."""
        response = await api.post(
            PRICING_URL,
            json={
                "items": [
                    {
                        "sku": "KAN-16-PP",
                        "tiers": [
                            {"min_qty": "1", "max_qty": "50", "price": "3000.00"},
                            {"min_qty": "40", "max_qty": "100", "price": "2800.00"},
                        ],
                    }
                ]
            },
            headers=auth_headers(),
        )

        body = response.json()
        assert body["failed"] == 1
        assert body["rows"][0]["code"] == "invalid_tiers"

    async def test_неизвестный_прайс_лист_это_ошибка_строки(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        response = await api.post(
            PRICING_URL,
            json={
                "items": [
                    {
                        "sku": "KAN-16-PP",
                        "price_list_code": "нет-такого",
                        "tiers": [{"price": "100.00"}],
                    }
                ]
            },
            headers=auth_headers(),
        )

        assert response.json()["rows"][0]["code"] == "price_list_not_found"

    async def test_дилерский_прайс_лист_обновляется_отдельно(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        await api.post(
            PRICING_URL,
            json={
                "items": [
                    {
                        "sku": "KAN-16-PP",
                        "price_list_code": "dealer",
                        "tiers": [{"price": "2500.00"}],
                    }
                ]
            },
            headers=auth_headers(),
        )

        product = await load_product(committed_session, "KAN-16-PP")
        dealer = (
            (
                await committed_session.execute(
                    select(PriceTier).where(
                        PriceTier.product_id == product.id,
                        PriceTier.price_list_id == catalog.dealer_price_list.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [tier.price for tier in dealer] == [Decimal("2500.00")]

    async def test_те_же_цены_не_считаются_изменением(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        body = {"items": [{"sku": "KAN-16-PP", "tiers": [{"price": "3333.00"}]}]}
        await api.post(PRICING_URL, json=body, headers=auth_headers())
        # Второй раз — тот же пакет, но с другой позицией, чтобы обойти
        # защиту от дубля и проверить именно сравнение значений.
        second = await api.post(
            PRICING_URL,
            json={
                "items": [
                    {"sku": "KAN-16-PP", "tiers": [{"price": "3333.00"}]},
                    {"sku": "KRP-M10", "tiers": [{"price": "120.00"}]},
                ]
            },
            headers=auth_headers(),
        )

        rows = {row["key"]: row["status"] for row in second.json()["rows"]}
        assert rows["KAN-16-PP"] == "skipped"
        assert rows["KRP-M10"] == "updated"


class TestStockSync:
    async def test_остаток_создаётся_и_обновляется(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        response = await api.post(
            INVENTORY_URL,
            json={
                "items": [
                    {
                        "sku": "KAN-16-PP",
                        "warehouse_code": "main",
                        "quantity": "120.500",
                        "reserved": "20.250",
                    }
                ]
            },
            headers=auth_headers(),
        )

        assert response.status_code == 200
        product = await load_product(committed_session, "KAN-16-PP")
        stock = await load_stock(committed_session, product.id, catalog.warehouse.id)
        assert stock is not None
        assert stock.quantity == Decimal("120.500")
        assert stock.reserved == Decimal("20.250")
        # Свободный остаток вычисляется, а не хранится.
        assert stock.quantity - stock.reserved == Decimal("100.250")
        assert stock.sync_source == "1c"
        assert stock.synced_at is not None

    async def test_склад_находится_по_внешнему_идентификатору(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        warehouse = (
            await committed_session.execute(select(Warehouse).where(Warehouse.code == "main"))
        ).scalar_one()
        warehouse.external_id = "1c-wh-0001"
        await committed_session.commit()

        response = await api.post(
            INVENTORY_URL,
            json={
                "items": [
                    {"sku": "KAN-16-PP", "warehouse_external_id": "1c-wh-0001", "quantity": "7"}
                ]
            },
            headers=auth_headers(),
        )

        assert response.json()["updated"] == 1

    async def test_неизвестный_склад_это_ошибка_строки(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        """Склад обменом не создаётся: это объект с адресом и регионом."""
        response = await api.post(
            INVENTORY_URL,
            json={"items": [{"sku": "KAN-16-PP", "warehouse_code": "нет-такого", "quantity": "1"}]},
            headers=auth_headers(),
        )

        body = response.json()
        assert body["failed"] == 1
        assert body["rows"][0]["code"] == "warehouse_not_found"

    async def test_резерв_больше_остатка_отбраковывается(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        """Свободный остаток ушёл бы в минус — это ошибка выгрузки."""
        response = await api.post(
            INVENTORY_URL,
            json={
                "items": [
                    {
                        "sku": "KAN-16-PP",
                        "warehouse_code": "main",
                        "quantity": "5",
                        "reserved": "10",
                    }
                ]
            },
            headers=auth_headers(),
        )

        assert response.json()["rows"][0]["code"] == "reserved_exceeds_quantity"

    async def test_отрицательный_остаток_отклоняется_схемой(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        response = await api.post(
            INVENTORY_URL,
            json={"items": [{"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "-1"}]},
            headers=auth_headers(),
        )

        assert response.status_code == 422

    async def test_одна_битая_строка_не_отменяет_весь_пакет(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        """Сбой на 900-й позиции не должен стоить 899 успешных."""
        response = await api.post(
            INVENTORY_URL,
            json={
                "items": [
                    {"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "10"},
                    {"sku": "KRP-M10", "warehouse_code": "нет-такого", "quantity": "5"},
                    {"sku": "SID-01", "warehouse_code": "main", "quantity": "3"},
                ]
            },
            headers=auth_headers(),
        )

        body = response.json()
        assert body["received"] == 3
        assert body["updated"] == 2
        assert body["failed"] == 1
        # Хорошие строки действительно записаны.
        product = await load_product(committed_session, "KAN-16-PP")
        stock = await load_stock(committed_session, product.id, catalog.warehouse.id)
        assert stock is not None and stock.quantity == Decimal("10.000")

    async def test_отсутствие_товара_в_пакете_не_удаляет_остаток(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        """Пустой или частичный пакет не должен обнулять склад."""
        await api.post(
            INVENTORY_URL,
            json={
                "items": [
                    {"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "10"},
                    {"sku": "KRP-M10", "warehouse_code": "main", "quantity": "20"},
                ]
            },
            headers=auth_headers(),
        )
        # Следующая выгрузка содержит только один товар.
        await api.post(
            INVENTORY_URL,
            json={"items": [{"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "11"}]},
            headers=auth_headers(),
        )

        other = await load_product(committed_session, "KRP-M10")
        stock = await load_stock(committed_session, other.id, catalog.warehouse.id)
        assert stock is not None
        assert stock.quantity == Decimal("20.000")

    async def test_повтор_пакета_идемпотентен(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        body = {"items": [{"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "42.000"}]}

        await api.post(INVENTORY_URL, json=body, headers=auth_headers())
        second = await api.post(INVENTORY_URL, json=body, headers=auth_headers())

        assert second.json()["duplicate"] is True
        product = await load_product(committed_session, "KAN-16-PP")
        stock = await load_stock(committed_session, product.id, catalog.warehouse.id)
        assert stock is not None and stock.quantity == Decimal("42.000")

    async def test_остаток_на_неактивном_складе_не_попадает_на_витрину(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        """Публичное наличие считается только по активным складам."""
        warehouse = (
            await committed_session.execute(select(Warehouse).where(Warehouse.code == "main"))
        ).scalar_one()
        warehouse.is_active = False
        await committed_session.commit()

        await api.post(
            INVENTORY_URL,
            json={"items": [{"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "999"}]},
            headers=auth_headers(),
        )

        public = await api.get("/api/v1/public/products/kanat-16-pp")
        assert public.status_code == 200
        assert public.json()["availability"] != "IN_STOCK"

    async def test_публичный_api_не_отдаёт_точный_остаток(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        await api.post(
            INVENTORY_URL,
            json={"items": [{"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "777"}]},
            headers=auth_headers(),
        )

        public = await api.get("/api/v1/public/products/kanat-16-pp")

        assert "777" not in public.text
        assert public.json()["availability"] == "IN_STOCK"


class TestSyncLog:
    async def test_каждый_обмен_попадает_в_журнал_без_содержимого_пакета(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        await api.post(
            INVENTORY_URL,
            json={"items": [{"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "5"}]},
            headers=auth_headers(),
        )

        entry = (
            (await committed_session.execute(select(SyncLog).order_by(SyncLog.id.desc())))
            .scalars()
            .first()
        )
        assert entry is not None
        assert entry.direction == "inbound"
        assert entry.entity == "stock"
        assert entry.status == "success"
        assert entry.received == 1
        assert entry.api_key_name == "1С обмен (тест)"
        # Хранится только контрольная сумма, не сам пакет.
        assert entry.payload_hash and len(entry.payload_hash) == 64
        assert "KAN-16-PP" not in (entry.payload_hash or "")

    async def test_частичный_успех_помечается_отдельно(
        self, api: AsyncClient, committed_session: AsyncSession, catalog: CatalogFixture, api_key
    ) -> None:
        await api.post(
            INVENTORY_URL,
            json={
                "items": [
                    {"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "1"},
                    {"sku": "KRP-M10", "warehouse_code": "нет", "quantity": "1"},
                ]
            },
            headers=auth_headers(),
        )

        entry = (
            (await committed_session.execute(select(SyncLog).order_by(SyncLog.id.desc())))
            .scalars()
            .first()
        )
        assert entry is not None and entry.status == "partial"

    async def test_частичный_успех_не_считается_дублем(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        """Отбракованные строки обязаны получить второй шанс."""
        body = {
            "items": [
                {"sku": "KAN-16-PP", "warehouse_code": "main", "quantity": "1"},
                {"sku": "KRP-M10", "warehouse_code": "нет", "quantity": "1"},
            ]
        }

        await api.post(INVENTORY_URL, json=body, headers=auth_headers())
        second = await api.post(INVENTORY_URL, json=body, headers=auth_headers())

        assert second.json()["duplicate"] is False


class TestRequestExport:
    async def test_заявки_отдаются_со_снапшотами_позиций(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        await api.post(
            PUBLIC_REQUESTS,
            json=request_payload(catalog, [{"sku": "KAN-16-PP", "quantity": "50"}]),
        )

        response = await api.get(REQUESTS_URL, headers=auth_headers())

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["number"].startswith("R-2026-")
        assert item["items"][0]["sku"] == "KAN-16-PP"
        assert item["items"][0]["quantity"] == "50.000"
        assert item["exported_at"] is None

    async def test_подтверждение_помечает_заявку_выгруженной(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        await api.post(
            PUBLIC_REQUESTS, json=request_payload(catalog, [{"sku": "KAN-16-PP", "quantity": "1"}])
        )
        listed = (await api.get(REQUESTS_URL, headers=auth_headers())).json()["items"][0]

        ack = await api.post(
            f"{REQUESTS_URL}/{listed['uuid']}/ack",
            json={"external_id": "1c-doc-42"},
            headers=auth_headers(),
        )

        assert ack.status_code == 200
        assert ack.json()["external_id"] == "1c-doc-42"
        # Подтверждённая заявка больше не выдаётся по умолчанию.
        assert (await api.get(REQUESTS_URL, headers=auth_headers())).json()["total"] == 0

    async def test_повторное_подтверждение_не_переписывает_номер_документа(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        await api.post(
            PUBLIC_REQUESTS, json=request_payload(catalog, [{"sku": "KAN-16-PP", "quantity": "1"}])
        )
        listed = (await api.get(REQUESTS_URL, headers=auth_headers())).json()["items"][0]
        url = f"{REQUESTS_URL}/{listed['uuid']}/ack"

        first = await api.post(url, json={"external_id": "1c-doc-42"}, headers=auth_headers())
        second = await api.post(url, json={"external_id": "1c-doc-99"}, headers=auth_headers())

        assert second.status_code == 200
        assert second.json()["external_id"] == "1c-doc-42"
        assert second.json()["exported_at"] == first.json()["exported_at"]

    async def test_подтверждение_несуществующей_заявки_это_404(
        self, api: AsyncClient, catalog: CatalogFixture, api_key
    ) -> None:
        response = await api.post(
            f"{REQUESTS_URL}/11111111-2222-3333-4444-555555555555/ack",
            json={},
            headers=auth_headers(),
        )

        assert response.status_code == 404
