"""Приём пакетов от учётной системы: товары, цены, остатки.

ОБЩИЕ ПРАВИЛА, одинаковые для всех трёх обменов.

*Upsert, а не замена.* Отсутствие товара в пакете НЕ означает, что его
удалили в 1С: обмен может быть инкрементальным, обработка — упасть на
середине, а сеть — оборвать выгрузку. Удаление по отсутствию однажды
обнулило бы каталог из-за пустого пакета. Полная замена появится
только если настоящий контракт явно её опишет.

*Сопоставление по стабильным идентификаторам.* external_id, при его
отсутствии — sku. Никогда по названию.

*Валидация до мутации.* Строка проверяется целиком, и только затем
применяется. Битая строка попадает в отчёт и не трогает свой объект.

*Частичный успех.* Одна плохая строка не отменяет пакет: транзакция
одна, но проблемная строка откатывается точечно через SAVEPOINT
(`session.begin_nested`). Иначе сбой на 900-й позиции стоил бы 899
успешных обновлений.

*Идемпотентность.* Повторная отправка того же пакета не создаёт дублей:
upsert по стабильному ключу сам по себе идемпотентен, а полностью
одинаковый пакет узнаётся по SHA-256 и вообще не применяется повторно.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.catalog.models import Product
from app.modules.integration.audit import (
    INTEGRATION_ACTOR,
    SYNC_SOURCE_1C,
    IntegrationAuditAction,
)
from app.modules.integration.models import ApiKey
from app.modules.integration.repository import SyncLogRepository
from app.modules.integration.schemas import (
    PriceUpsert,
    ProductRef,
    ProductUpsert,
    RowOutcome,
    StockUpsertItem,
    SyncResult,
)
from app.modules.inventory.models import Stock, Warehouse
from app.modules.pricing.models import PriceList, PriceTier

logger = get_logger(__name__)

# Сущности обмена — они же значения sync_log.entity.
ENTITY_PRODUCT = "product"
ENTITY_PRICE = "price"
ENTITY_STOCK = "stock"

# Исходы строки пакета — те же значения, что в RowOutcome.status.
RowStatus = Literal["created", "updated", "skipped", "failed"]


def _now() -> datetime:
    return datetime.now(UTC)


class SyncOutcome:
    """Накопитель построчных результатов и счётчиков."""

    def __init__(self) -> None:
        self.rows: list[RowOutcome] = []
        self.counters: dict[str, int] = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
        }

    def record(
        self, key: str, status: str, code: str | None = None, message: str | None = None
    ) -> None:
        # status приходит из наших же вызовов; Literal сужается здесь.
        self.rows.append(
            RowOutcome(key=key, status=cast("RowStatus", status), code=code, message=message)
        )
        self.counters[status] = self.counters.get(status, 0) + 1

    def status(self) -> str:
        if self.counters["failed"] == 0:
            return "success"
        changed = self.counters["created"] + self.counters["updated"] + self.counters["skipped"]
        return "partial" if changed else "failed"


class BaseSyncService(BaseService):
    """Общая обвязка: журнал обмена, защита от повтора, отчёт."""

    entity: str = ""

    def __init__(self, session: AsyncSession, api_key: ApiKey | None = None) -> None:
        super().__init__(session)
        self.api_key = api_key
        self.audit = AuditService(session)
        self.sync_log = SyncLogRepository(session)

    # ------------------------------------------------------- инфраструктура

    async def _duplicate(self, payload_hash: str) -> SyncResult | None:
        """Тот же пакет уже применён — возвращаем прежний итог.

        Защищает от повторной отправки при таймауте на стороне 1С:
        обработка не знает, дошёл ли пакет, и шлёт его заново.
        Upsert и так идемпотентен, но повтор без изменений не должен
        ни засорять журнал, ни переставлять synced_at.
        """
        previous = await self.sync_log.find_successful(self.entity, payload_hash)
        if previous is None:
            return None
        return SyncResult(
            sync_uuid=str(previous.uuid),
            received=previous.received,
            created=previous.created,
            updated=previous.updated,
            skipped=previous.skipped,
            failed=previous.failed,
            duration_ms=previous.duration_ms,
            duplicate=True,
        )

    async def _finish(
        self,
        *,
        endpoint: str,
        outcome: SyncOutcome,
        received: int,
        started: float,
        payload_hash: str,
        request_id: str | None,
    ) -> SyncResult:
        duration_ms = int((time.monotonic() - started) * 1000)
        entry = self.sync_log.record(
            direction="inbound",
            entity=self.entity,
            endpoint=endpoint,
            status=outcome.status(),
            api_key_name=self.api_key.name if self.api_key else None,
            received=received,
            created=outcome.counters["created"],
            updated=outcome.counters["updated"],
            skipped=outcome.counters["skipped"],
            failed=outcome.counters["failed"],
            duration_ms=duration_ms,
            payload_hash=payload_hash,
            request_id=request_id,
        )
        await self.session.flush()
        await self.commit()

        logger.info(
            "integration_sync",
            entity=self.entity,
            endpoint=endpoint,
            status=entry.status,
            received=received,
            duration_ms=duration_ms,
            # Имя ключа, не сам ключ и не его хеш.
            key=self.api_key.key_prefix if self.api_key else None,
            **outcome.counters,
        )
        return SyncResult(
            sync_uuid=str(entry.uuid),
            received=received,
            duration_ms=duration_ms,
            rows=outcome.rows,
            **outcome.counters,
        )

    # ------------------------------------------------------- сопоставление

    async def _match_products(self, refs: list[ProductRef]) -> dict[str, Product]:
        """Товары пакета одним запросом: по external_id и по sku.

        Запрос на строку превратил бы пакет в тысячу round-trip'ов.
        Удалённые товары не подбираются: обмен не воскрешает то,
        что убрали на сайте осознанно.
        """
        external_ids = {ref.external_id for ref in refs if ref.external_id}
        skus = {ref.sku for ref in refs if ref.sku}
        if not external_ids and not skus:
            return {}

        conditions = []
        if external_ids:
            conditions.append(Product.external_id.in_(external_ids))
        if skus:
            conditions.append(Product.sku.in_(skus))
        from sqlalchemy import or_

        rows = (
            await self.session.execute(
                select(Product).where(Product.deleted_at.is_(None), or_(*conditions))
            )
        ).scalars()

        index: dict[str, Product] = {}
        for product in rows:
            if product.external_id:
                index[f"ext:{product.external_id}"] = product
            index[f"sku:{product.sku}"] = product
        return index

    @staticmethod
    def _lookup(index: dict[str, Product], ref: ProductRef) -> Product | None:
        """external_id важнее sku: GUID стабилен, артикул переименовывают."""
        if ref.external_id:
            found = index.get(f"ext:{ref.external_id}")
            if found is not None:
                return found
        if ref.sku:
            return index.get(f"sku:{ref.sku}")
        return None


class ProductSyncService(BaseSyncService):
    """Товары: только поля, которыми владеет учётная система."""

    entity = ENTITY_PRODUCT

    async def apply(
        self,
        items: list[ProductUpsert],
        *,
        payload_hash: str,
        request_id: str | None = None,
        endpoint: str = "/catalog/products/bulk-upsert",
    ) -> SyncResult:
        started = time.monotonic()
        duplicate = await self._duplicate(payload_hash)
        if duplicate is not None:
            return duplicate

        outcome = SyncOutcome()
        index = await self._match_products(list(items))
        now = _now()

        for item in items:
            product = self._lookup(index, item)
            if product is None:
                # Товар не заводится обменом: у него нет slug, описания,
                # категории и картинок, а витрина без них показывает
                # пустую карточку. Заведение — задача админки и Excel.
                outcome.record(
                    item.key(),
                    "skipped",
                    "product_not_found",
                    "Товар не найден: заведите его на сайте, обмен только обновляет",
                )
                continue
            try:
                async with self.session.begin_nested():
                    changed = self._apply_product(product, item, now)
            except SQLAlchemyError as exc:
                outcome.record(item.key(), "failed", "db_error", _short(exc))
                continue
            outcome.record(item.key(), "updated" if changed else "skipped")

        return await self._finish(
            endpoint=endpoint,
            outcome=outcome,
            received=len(items),
            started=started,
            payload_hash=payload_hash,
            request_id=request_id,
        )

    def _apply_product(self, product: Product, item: ProductUpsert, now: datetime) -> bool:
        changes: dict[str, Any] = {}
        # Проставляем GUID при первом сопоставлении по артикулу: дальше
        # товар будет находиться по стабильному идентификатору.
        if item.external_id and product.external_id != item.external_id:
            changes["external_id"] = {"old": product.external_id, "new": item.external_id}
            product.external_id = item.external_id

        for field in ("name", "unit", "is_active", "min_order_qty", "brand"):
            value = getattr(item, field, None)
            if value is None:
                continue  # None = «не менять», см. схему
            if field == "name":
                # Название товара живёт в переводах, а не в products:
                # менять его обменом нельзя, не решив, какой язык мастер.
                # До появления контракта название только сверяется.
                continue
            current = getattr(product, field)
            if current != value:
                changes[field] = {"old": _plain(current), "new": _plain(value)}
                setattr(product, field, value)

        if not changes:
            return False

        product.sync_source = SYNC_SOURCE_1C
        product.synced_at = now
        self.audit.record(
            action=IntegrationAuditAction.PRODUCT_UPDATED,
            entity_type="product",
            entity_id=product.id,
            actor=INTEGRATION_ACTOR,
            changes=changes,
        )
        return True


class PriceSyncService(BaseSyncService):
    """Цены: набор ступеней товара заменяется целиком."""

    entity = ENTITY_PRICE

    async def apply(
        self,
        items: list[PriceUpsert],
        *,
        payload_hash: str,
        request_id: str | None = None,
        endpoint: str = "/pricing/bulk-upsert",
    ) -> SyncResult:
        started = time.monotonic()
        duplicate = await self._duplicate(payload_hash)
        if duplicate is not None:
            return duplicate

        outcome = SyncOutcome()
        index = await self._match_products(list(items))
        price_lists = await self._price_lists()
        now = _now()

        for item in items:
            product = self._lookup(index, item)
            if product is None:
                outcome.record(item.key(), "skipped", "product_not_found", "Товар не найден")
                continue

            price_list = self._resolve_price_list(price_lists, item.price_list_code)
            if price_list is None:
                outcome.record(
                    item.key(),
                    "failed",
                    "price_list_not_found",
                    f"Прайс-лист {item.price_list_code or 'по умолчанию'} не найден",
                )
                continue

            invalid = _validate_tiers(item)
            if invalid is not None:
                # Проверка ДО мутации: пересекающиеся диапазоны уронили
                # бы весь пакет на EXCLUDE-ограничении базы.
                outcome.record(item.key(), "failed", "invalid_tiers", invalid)
                continue

            try:
                async with self.session.begin_nested():
                    changed = await self._apply_price(product, price_list, item, now)
            except SQLAlchemyError as exc:
                outcome.record(item.key(), "failed", "db_error", _short(exc))
                continue
            outcome.record(item.key(), "updated" if changed else "skipped")

        return await self._finish(
            endpoint=endpoint,
            outcome=outcome,
            received=len(items),
            started=started,
            payload_hash=payload_hash,
            request_id=request_id,
        )

    async def _price_lists(self) -> dict[str, PriceList]:
        rows = (
            await self.session.execute(select(PriceList).where(PriceList.is_active.is_(True)))
        ).scalars()
        index: dict[str, PriceList] = {}
        for price_list in rows:
            index[price_list.code] = price_list
            if price_list.is_default:
                index["__default__"] = price_list
        return index

    @staticmethod
    def _resolve_price_list(index: dict[str, PriceList], code: str | None) -> PriceList | None:
        return index.get(code) if code else index.get("__default__")

    async def _apply_price(
        self, product: Product, price_list: PriceList, item: PriceUpsert, now: datetime
    ) -> bool:
        existing = list(
            (
                await self.session.execute(
                    select(PriceTier).where(
                        PriceTier.product_id == product.id,
                        PriceTier.price_list_id == price_list.id,
                    )
                )
            ).scalars()
        )
        before = sorted((tier.min_qty, tier.max_qty, tier.price) for tier in existing)
        after = sorted((tier.min_qty, tier.max_qty, tier.price) for tier in item.tiers)
        if before == after:
            return False

        # Полная замена набора: частичное обновление ступеней оставило бы
        # старую ступень рядом с новой и дало две цены на одно количество.
        for tier in existing:
            await self.session.delete(tier)
        await self.session.flush()

        for incoming in item.tiers:
            self.session.add(
                PriceTier(
                    product_id=product.id,
                    price_list_id=price_list.id,
                    min_qty=incoming.min_qty,
                    max_qty=incoming.max_qty,
                    price=incoming.price,
                    sync_source=SYNC_SOURCE_1C,
                    synced_at=now,
                )
            )
        await self.session.flush()

        self.audit.record(
            action=IntegrationAuditAction.PRICING_UPDATED,
            entity_type="product_pricing",
            entity_id=product.id,
            actor=INTEGRATION_ACTOR,
            changes={
                "price_list": price_list.code,
                "tiers": {
                    "old": [_tier_repr(t) for t in before],
                    "new": [_tier_repr(t) for t in after],
                },
            },
        )
        return True


class StockSyncService(BaseSyncService):
    """Остатки: самый частый обмен.

    Свободный остаток вычисляется как `quantity - reserved` и в базе
    не хранится — иначе он рассинхронизировался бы с любым из слагаемых.
    Публичный статус наличия считается на лету по активным складам,
    точные количества наружу не отдаются никогда.
    """

    entity = ENTITY_STOCK

    async def apply(
        self,
        items: list[StockUpsertItem],
        *,
        payload_hash: str,
        request_id: str | None = None,
        endpoint: str = "/inventory/bulk-upsert",
    ) -> SyncResult:
        started = time.monotonic()
        duplicate = await self._duplicate(payload_hash)
        if duplicate is not None:
            return duplicate

        outcome = SyncOutcome()
        index = await self._match_products(list(items))
        warehouses = await self._warehouses()
        now = _now()

        for item in items:
            product = self._lookup(index, item)
            if product is None:
                outcome.record(item.key(), "skipped", "product_not_found", "Товар не найден")
                continue

            warehouse = self._lookup_warehouse(warehouses, item)
            if warehouse is None:
                # Склад обменом не создаётся: см. комментарий в схеме.
                outcome.record(
                    item.key(),
                    "failed",
                    "warehouse_not_found",
                    "Склад не найден: заведите его в админке",
                )
                continue

            reserved = item.reserved if item.reserved is not None else None
            if reserved is not None and reserved > item.quantity:
                # Резерв больше остатка — ошибка выгрузки: свободный
                # остаток ушёл бы в минус, а CHECK базы отверг бы строку.
                outcome.record(
                    item.key(),
                    "failed",
                    "reserved_exceeds_quantity",
                    "Резерв больше остатка",
                )
                continue

            try:
                async with self.session.begin_nested():
                    changed = await self._apply_stock(product, warehouse, item, reserved, now)
            except SQLAlchemyError as exc:
                outcome.record(item.key(), "failed", "db_error", _short(exc))
                continue
            outcome.record(item.key(), "updated" if changed else "skipped")

        return await self._finish(
            endpoint=endpoint,
            outcome=outcome,
            received=len(items),
            started=started,
            payload_hash=payload_hash,
            request_id=request_id,
        )

    async def _warehouses(self) -> dict[str, Warehouse]:
        rows = (await self.session.execute(select(Warehouse))).scalars()
        index: dict[str, Warehouse] = {}
        for warehouse in rows:
            if warehouse.external_id:
                index[f"ext:{warehouse.external_id}"] = warehouse
            index[f"code:{warehouse.code}"] = warehouse
        return index

    @staticmethod
    def _lookup_warehouse(index: dict[str, Warehouse], item: StockUpsertItem) -> Warehouse | None:
        if item.warehouse_external_id:
            found = index.get(f"ext:{item.warehouse_external_id}")
            if found is not None:
                return found
        if item.warehouse_code:
            return index.get(f"code:{item.warehouse_code}")
        return None

    async def _apply_stock(
        self,
        product: Product,
        warehouse: Warehouse,
        item: StockUpsertItem,
        reserved: Decimal | None,
        now: datetime,
    ) -> bool:
        stock = (
            await self.session.execute(
                select(Stock).where(
                    Stock.product_id == product.id, Stock.warehouse_id == warehouse.id
                )
            )
        ).scalar_one_or_none()

        new_reserved = (
            reserved if reserved is not None else (stock.reserved if stock else Decimal(0))
        )
        if stock is None:
            stock = Stock(
                product_id=product.id,
                warehouse_id=warehouse.id,
                quantity=item.quantity,
                reserved=new_reserved,
                sync_source=SYNC_SOURCE_1C,
                synced_at=now,
                external_id=item.warehouse_external_id,
            )
            self.session.add(stock)
            await self.session.flush()
            self.audit.record(
                action=IntegrationAuditAction.STOCK_UPDATED,
                entity_type="product_stock",
                entity_id=product.id,
                actor=INTEGRATION_ACTOR,
                changes={
                    "warehouse": warehouse.code,
                    "quantity": {"old": None, "new": str(item.quantity)},
                    "reserved": {"old": None, "new": str(new_reserved)},
                },
            )
            return True

        if stock.quantity == item.quantity and stock.reserved == new_reserved:
            # Ничего не изменилось: synced_at не трогаем, чтобы поле
            # отвечало на вопрос «когда данные реально менялись».
            return False

        changes = {
            "warehouse": warehouse.code,
            "quantity": {"old": str(stock.quantity), "new": str(item.quantity)},
            "reserved": {"old": str(stock.reserved), "new": str(new_reserved)},
        }
        stock.quantity = item.quantity
        stock.reserved = new_reserved
        stock.sync_source = SYNC_SOURCE_1C
        stock.synced_at = now
        stock.updated_at = now
        await self.session.flush()
        self.audit.record(
            action=IntegrationAuditAction.STOCK_UPDATED,
            entity_type="product_stock",
            entity_id=product.id,
            actor=INTEGRATION_ACTOR,
            changes=changes,
        )
        return True


# ---------------------------------------------------------------- помощники


def _validate_tiers(item: PriceUpsert) -> str | None:
    """Ступени не должны пересекаться и должны быть осмысленны.

    База защищена EXCLUDE-ограничением, но упасть на нём — значит
    потерять весь пакет: проверяем заранее и отвергаем одну строку.
    """
    ranges: list[tuple[Decimal, Decimal | None]] = []
    for tier in item.tiers:
        if tier.max_qty is not None and tier.max_qty < tier.min_qty:
            return f"Ступень {tier.min_qty}–{tier.max_qty}: верхняя граница ниже нижней"
        ranges.append((tier.min_qty, tier.max_qty))

    ordered = sorted(ranges, key=lambda pair: pair[0])
    for (low, high), (next_low, _) in pairwise(ordered):
        if high is None or high >= next_low:
            return f"Ступени {low}–{high} и {next_low}–… пересекаются"
    return None


def _tier_repr(tier: tuple[Decimal, Decimal | None, Decimal]) -> str:
    low, high, price = tier
    return f"{low}-{high if high is not None else '∞'}:{price}"


def _plain(value: object) -> Any:
    """Decimal в JSON-совместимую строку: аудит хранит JSONB."""
    return str(value) if isinstance(value, Decimal) else value


def _short(exc: Exception) -> str:
    """Текст ошибки БД без SQL и параметров: в них бывают данные клиента."""
    return type(exc).__name__


def new_sync_uuid() -> str:
    return str(uuid.uuid4())
