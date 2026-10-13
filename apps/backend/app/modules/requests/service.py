"""Приём заявок с сайта.

Порядок фиксирован: проверка → расчёт цен → заявка → позиции со
снапшотами → запись истории → аудит → коммит. Всё — одна транзакция:
ошибка на любом шаге откатывает её целиком, и частично созданной
заявки в базе не бывает.

Заявка ничего не резервирует и остатков не касается: резервирование
появится вместе с 1С.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.integrity import extract_constraint_name
from app.core.logging import get_logger
from app.core.service import BaseService
from app.db.types import MONEY_PRECISION, MONEY_SCALE, QTY_SCALE
from app.modules.audit.service import AuditService
from app.modules.catalog.repository import CatalogRepository
from app.modules.colors.models import ProductColor
from app.modules.colors.pricing import shift_tiers
from app.modules.colors.repository import ColorRepository
from app.modules.notifications.events import NotificationEvents
from app.modules.notifications.queue import (
    NotificationQueue,
    NullNotificationQueue,
    wake_worker,
)
from app.modules.pricing.enums import PricingType
from app.modules.pricing.resolver import MONEY_EXPONENT, TierLike, resolve_price
from app.modules.requests.audit import PUBLIC_ACTOR, REQUEST_ENTITY, RequestAuditAction
from app.modules.requests.enums import RequestKind, RequestSource, RequestStatus
from app.modules.requests.exceptions import (
    IdempotencyKeyConflictError,
    RequestColorUnavailableError,
    RequestProductUnavailableError,
    RequestQuantityBelowMinimumError,
    RequestRegionNotFoundError,
    RequestTotalTooLargeError,
)
from app.modules.requests.models import Request, RequestItem, RequestStatusHistory
from app.modules.requests.repository import OrderableProduct, RequestRepository
from app.modules.requests.schemas_public import (
    PublicRequestCreate,
    PublicRequestCreated,
    PublicRequestItemRead,
)
from app.modules.users.service import RequestContext

logger = get_logger(__name__)

# Наибольшее значение, которое помещается в NUMERIC(14,2).
MAX_MONEY = Decimal(10) ** (MONEY_PRECISION - MONEY_SCALE) - MONEY_EXPONENT
QTY_EXPONENT = Decimal(1).scaleb(-QTY_SCALE)

IDEMPOTENCY_CONSTRAINT = "uq_requests_idempotency_key"


def build_request_number(request_id: int, moment: datetime) -> str:
    """Человекочитаемый номер вида R-2026-000142 (docs/architecture.md, 6.7)."""
    return f"R-{moment.year}-{request_id:06d}"


class RequestSubmissionService(BaseService):
    def __init__(
        self, session: AsyncSession, notifications: NotificationQueue | None = None
    ) -> None:
        super().__init__(session)
        self.repository = RequestRepository(session)
        self.catalog = CatalogRepository(session)
        self.colors = ColorRepository(session)
        self.audit = AuditService(session)
        self.events = NotificationEvents(session)
        # Очередь только будит воркер. Её отсутствие ничего не ломает:
        # событие уже лежит в notification_outbox.
        self.notifications = notifications or NullNotificationQueue()

    async def submit(
        self,
        payload: PublicRequestCreate,
        context: RequestContext,
        idempotency_key: str | None = None,
        *,
        customer_id: int | None = None,
        project_id: int | None = None,
    ) -> PublicRequestCreated:
        """Создаёт заявку и возвращает подтверждение.

        Повтор с тем же `Idempotency-Key` (двойной клик, ретрай
        мобильной сети) возвращает уже созданную заявку, а не дубль,
        из-за которого менеджер позвонил бы клиенту дважды.

        `customer_id` и `project_id` передаёт кабинет клиента (владение
        проектом проверено там). Анонимная форма их не задаёт.
        """
        if idempotency_key is not None:
            existing = await self.repository.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return self._replay(existing, customer_id)

        # ---------------------------------------------------- проверка
        region = None
        if payload.region_id is not None:
            region = await self.repository.get_active_region(payload.region_id)
            if region is None:
                raise RequestRegionNotFoundError(details={"region_id": payload.region_id})

        skus = [item.sku for item in payload.items]
        products = await self.repository.get_orderable_products(skus)
        unavailable = [sku for sku in skus if sku not in products]
        if unavailable:
            # Одна недоступная позиция отклоняет всю заявку: клиент
            # должен увидеть, что состав не принят, а не получить
            # молча урезанную заявку.
            raise RequestProductUnavailableError(details={"skus": unavailable})

        # Минимальная партия — то же поле, что витрина показывает
        # в карточке. Сравнение Decimal с Decimal: 2.50 и 2.500 равны,
        # дробные минимумы (метры каната) сравниваются точно.
        below_minimum = [
            {
                "sku": line.sku,
                "quantity": str(line.quantity),
                "min_order_qty": str(products[line.sku].product.min_order_qty),
            }
            for line in payload.items
            if line.quantity < products[line.sku].product.min_order_qty
        ]
        if below_minimum:
            raise RequestQuantityBelowMinimumError(details={"items": below_minimum})

        colors = await self.resolve_colors(
            [(products[line.sku], line.color) for line in payload.items]
        )

        # ----------------------------------------------- расчёт цен
        items, currency = await self._priced_items(
            [(products[line.sku], line.quantity) for line in payload.items], colors
        )
        total_estimate = self._total(items)

        # ------------------------------------------ заявка и позиции
        request_id = await self.repository.next_request_id()
        number = build_request_number(request_id, datetime.now(UTC))
        request = Request(
            id=request_id,
            number=number,
            kind=RequestKind.CART.value,
            status=RequestStatus.NEW.value,
            source=RequestSource.CATALOG_CART.value,
            customer_name=payload.name,
            phone=payload.phone,
            email=payload.email,
            company=payload.company,
            region_id=region.id if region is not None else None,
            comment=payload.comment,
            ip_hash=context.ip_hash,
            user_agent=context.user_agent,
            idempotency_key=idempotency_key,
            customer_id=customer_id,
            project_id=project_id,
            total_estimate=total_estimate,
            currency=currency,
            items=items,
            # История начинается с создания: карточка заявки показывает
            # полный путь, включая исходный статус.
            status_history=[
                RequestStatusHistory(from_status=None, to_status=RequestStatus.NEW.value)
            ],
        )
        existing = await self._insert(request, idempotency_key)
        if existing is not None:
            return self._replay(existing, customer_id)

        # --------------------------------------------------------- аудит
        # Только служебные сведения: имя, телефон и email в журнал
        # не копируются — они уже есть в самой заявке.
        self.audit.record(
            action=RequestAuditAction.CREATED,
            entity_type=REQUEST_ENTITY,
            entity_id=request.id,
            actor=PUBLIC_ACTOR,
            changes={
                "number": number,
                "status": {"old": None, "new": RequestStatus.NEW.value},
                "region_id": region.id if region is not None else None,
                "items_count": len(items),
                "total_estimate": str(total_estimate) if total_estimate is not None else None,
            },
            ip_hash=context.ip_hash,
            request_id=context.request_id,
        )

        # ------------------------------------------------- уведомления
        # Запись в outbox, а не отправка: внешний вызов внутри
        # транзакции держал бы блокировки на время сетевого таймаута,
        # а откат транзакции уже не отменил бы отправленное письмо.
        outbox = self.events.request_created(
            request, region_name=region.name if region is not None else None
        )
        outbox_ids = await self.events.outbox.identify(outbox)

        await self.commit()

        # Побудка воркера — строго ПОСЛЕ коммита и вне транзакции.
        # Неудача здесь не влияет на заявку: она уже создана, а событие
        # заберёт периодический проход.
        await wake_worker(self.notifications, outbox_ids)

        logger.info(
            "request_created",
            request_id=request.id,
            number=number,
            items=len(items),
            notifications=len(outbox_ids),
        )
        return self._to_created(request)

    async def resolve_colors(
        self, lines: Sequence[tuple[OrderableProduct, str | None]]
    ) -> list[ProductColor | None]:
        """Цвет каждой позиции — одним запросом на всю заявку.

        Цвет, которого нет у товара или который отключён в справочнике,
        отклоняет заявку целиком — как и недоступный товар. Позиция без
        цвета принимается и у товара с цветами: цвет уточнит менеджер
        (так приходят списки артикулов и старые сохранённые корзины).
        """
        wanted = [entry.product.id for entry, color in lines if color is not None]
        available = await self.colors.colors_for_products(wanted)
        result: list[ProductColor | None] = []
        missing: list[dict[str, str]] = []
        for entry, code in lines:
            if code is None:
                result.append(None)
                continue
            match = next(
                (item for item in available.get(entry.product.id, []) if item.color.code == code),
                None,
            )
            if match is None:
                missing.append({"sku": entry.product.sku, "color": code})
            result.append(match)
        if missing:
            raise RequestColorUnavailableError(details={"items": missing})
        return result

    # ---------------------------------------------------------- внутреннее
    async def _priced_items(
        self,
        lines: Sequence[tuple[OrderableProduct, Decimal]],
        colors: Sequence[ProductColor | None] | None = None,
    ) -> tuple[list[RequestItem], str]:
        """Позиции со снапшотами цен публичного прайс-листа и валюта.

        Ступени цен — одним запросом на всю заявку, сколько бы позиций
        в ней ни было. Надбавка цвета прибавляется к каждой ступени —
        так же, как её показывает карточка товара.
        """
        price_list = await self.catalog.get_public_price_list()
        tiers = (
            await self.repository.get_price_tiers(
                [entry.product.id for entry, _ in lines], price_list.id
            )
            if price_list is not None and lines
            else {}
        )
        currency = price_list.currency if price_list is not None else settings.DEFAULT_CURRENCY

        items: list[RequestItem] = []
        for index, (entry, raw_quantity) in enumerate(lines):
            product = entry.product
            # Точность колонки: иначе первый ответ вернул бы «10», а
            # повтор по Idempotency-Key — «10.000» из базы.
            quantity = raw_quantity.quantize(QTY_EXPONENT)
            color = colors[index] if colors is not None else None
            product_tiers: Sequence[TierLike] = tiers.get(product.id, [])
            if color is not None:
                product_tiers = shift_tiers(product_tiers, color.price_delta)
            price = resolve_price(product.pricing_type, product_tiers, quantity)
            if price.line_total is not None and price.line_total > MAX_MONEY:
                raise RequestTotalTooLargeError(details={"sku": product.sku})

            # Снапшот: всё, что видел клиент, копируется из товара и
            # расчёта. Последующая правка товара на заявку не влияет.
            items.append(
                RequestItem(
                    product_id=product.id,
                    sku_snapshot=product.sku,
                    name_snapshot=entry.name,
                    unit_snapshot=product.unit,
                    pricing_type_snapshot=price.pricing_type.value,
                    color_code_snapshot=color.color.code if color is not None else None,
                    color_name_snapshot=color.color.name if color is not None else None,
                    quantity=quantity,
                    unit_price_snapshot=price.unit_price,
                    line_total_snapshot=price.line_total,
                    sort_order=index,
                )
            )
        return items, currency

    async def _insert(self, request: Request, idempotency_key: str | None) -> Request | None:
        """Вставляет заявку. Возвращает уже существующую, если параллельный
        повтор с тем же ключом успел вставить её первым."""
        self.repository.add(request)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            if (
                idempotency_key is not None
                and extract_constraint_name(exc) == IDEMPOTENCY_CONSTRAINT
            ):
                existing = await self.repository.find_by_idempotency_key(idempotency_key)
                if existing is not None:
                    return existing
            raise
        return None

    def _replay(self, existing: Request, customer_id: int | None) -> PublicRequestCreated:
        """Повтор по ключу отдаёт заявку только тому же отправителю.

        Иначе ключ заявки клиента, предъявленный другим клиентом или
        анонимной формой, раскрыл бы состав чужой заявки.
        """
        if existing.customer_id != customer_id:
            raise IdempotencyKeyConflictError
        return self._to_created(existing)

    def _total(self, items: list[RequestItem]) -> Decimal | None:
        """Оценка суммы — только если известны цены всех позиций.

        Сумма без позиций «по запросу» выглядела бы окончательной,
        хотя таковой не является.
        """
        totals = [item.line_total_snapshot for item in items]
        if any(value is None for value in totals):
            return None
        total = sum((value for value in totals if value is not None), Decimal(0))
        if total > MAX_MONEY:
            raise RequestTotalTooLargeError
        return total

    def _to_created(self, request: Request) -> PublicRequestCreated:
        items = sorted(request.items, key=lambda item: (item.sort_order, item.id or 0))
        return PublicRequestCreated(
            number=request.number,
            created_at=request.created_at,
            currency=request.currency,
            total_estimate=request.total_estimate,
            items=[
                PublicRequestItemRead(
                    sku=item.sku_snapshot,
                    name=item.name_snapshot,
                    unit=item.unit_snapshot,
                    quantity=item.quantity,
                    pricing_type=PricingType(item.pricing_type_snapshot),
                    unit_price=item.unit_price_snapshot,
                    line_total=item.line_total_snapshot,
                    color=item.color_code_snapshot,
                    color_name=item.color_name_snapshot,
                )
                for item in items
            ],
        )
