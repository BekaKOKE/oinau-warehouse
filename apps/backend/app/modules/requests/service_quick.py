"""Приём заявок из окна «Быстрый заказ».

Три вкладки окна — три способа описать потребность, но заявка одна и
та же: те же контакты, статусы, уведомления и карточка в админке.
Отличаются только источник (`source`) и состав:

    CALLBACK  — без позиций; с артикулом товара — «заказ в 1 клик»
                с одной позицией и строгими правилами корзины;
    SKU_LIST  — позиции из вставленного списка. Правила мягче, чем
                у корзины: нераспознанная строка или количество ниже
                минимальной партии заявку не отклоняют, а попадают
                менеджеру в комментарий, клиенту — в ответ;
    QUOTE     — без позиций, со спецификацией файлом и/или описанием.

Расчёт цен, номер, идемпотентность и уведомления — общие с корзиной
(RequestSubmissionService).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.core.logging import get_logger
from app.modules.colors.models import ProductColor
from app.modules.notifications.queue import wake_worker
from app.modules.requests.audit import PUBLIC_ACTOR, REQUEST_ENTITY, RequestAuditAction
from app.modules.requests.enums import (
    QuickRequestMode,
    RequestKind,
    RequestSource,
    RequestStatus,
)
from app.modules.requests.exceptions import (
    IdempotencyKeyConflictError,
    QuickRequestEmptyError,
    QuickRequestFormError,
    RequestProductUnavailableError,
    RequestQuantityBelowMinimumError,
    RequestTooManyItemsError,
)
from app.modules.requests.models import Request, RequestAttachment, RequestStatusHistory
from app.modules.requests.repository import OrderableProduct
from app.modules.requests.schemas_public import (
    MAX_COMMENT_LENGTH,
    MAX_REQUEST_ITEMS,
    PublicAttachmentRead,
    PublicQuickRequestCreate,
    PublicQuickRequestCreated,
    QuickRequestBelowMinimum,
)
from app.modules.requests.service import RequestSubmissionService, build_request_number
from app.modules.requests.sku_list import parse_sku_list
from app.modules.requests.upload import AttachmentUpload
from app.modules.users.service import RequestContext

logger = get_logger(__name__)

_MODE_BY_SOURCE: dict[str, QuickRequestMode] = {
    RequestSource.QUICK_CALLBACK.value: QuickRequestMode.CALLBACK,
    RequestSource.ONE_CLICK.value: QuickRequestMode.CALLBACK,
    RequestSource.SKU_LIST.value: QuickRequestMode.SKU_LIST,
    RequestSource.QUOTE_REQUEST.value: QuickRequestMode.QUOTE,
}

# Нераспознанных строк в комментарии заявки. Полный исходный список
# клиент может прислать и файлом; сотня строк мусора менеджеру не нужна.
MAX_NOTED_LINES = 50


def _format_quantity(value: Decimal) -> str:
    """10.000 → «10», 12.500 → «12,5» — как пишет человек."""
    text = format(value.normalize(), "f")
    return text.replace(".", ",")


class _Resolved:
    """Результат разбора списка артикулов."""

    def __init__(self) -> None:
        self.lines: dict[str, tuple[OrderableProduct, Decimal]] = {}
        # Цвет позиции заказа в 1 клик; у списка артикулов цвета нет.
        self.colors: dict[str, ProductColor] = {}
        self.unrecognized: list[str] = []
        self.below_minimum: list[QuickRequestBelowMinimum] = []


class QuickRequestService(RequestSubmissionService):
    async def submit_quick(
        self,
        payload: PublicQuickRequestCreate,
        attachment: AttachmentUpload | None,
        context: RequestContext,
        idempotency_key: str | None = None,
        *,
        customer_id: int | None = None,
    ) -> PublicQuickRequestCreated:
        if idempotency_key is not None:
            existing = await self.repository.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return self._replay_quick(existing, customer_id)

        if attachment is not None and payload.mode is not QuickRequestMode.QUOTE:
            # Файл принимается только к запросу КП: у звонка и списка
            # артикулов в карточке для него нет места.
            raise QuickRequestFormError("Файл прикладывается только к запросу КП")

        # --------------------------------------------------- состав
        resolved = _Resolved()
        if payload.mode is QuickRequestMode.CALLBACK and payload.product_sku:
            source = RequestSource.ONE_CLICK
            await self._resolve_one_click(payload, resolved)
        elif payload.mode is QuickRequestMode.CALLBACK:
            source = RequestSource.QUICK_CALLBACK
        elif payload.mode is QuickRequestMode.SKU_LIST:
            source = RequestSource.SKU_LIST
            await self._resolve_sku_list(payload.sku_list or "", resolved)
        else:
            source = RequestSource.QUOTE_REQUEST
            if attachment is None and not payload.comment:
                raise QuickRequestEmptyError

        items, currency = await self._priced_items(
            list(resolved.lines.values()), [resolved.colors.get(sku) for sku in resolved.lines]
        )
        total_estimate = self._total(items) if items else None

        # --------------------------------------------------- заявка
        request_id = await self.repository.next_request_id()
        number = build_request_number(request_id, datetime.now(UTC))
        request = Request(
            id=request_id,
            number=number,
            kind=(RequestKind.CART if items else RequestKind.GENERAL).value,
            status=RequestStatus.NEW.value,
            source=source.value,
            customer_name=payload.name,
            phone=payload.phone,
            email=payload.email,
            company=payload.company,
            bin=payload.bin,
            comment=self._comment(payload.comment, resolved),
            page_url=payload.page_url,
            ip_hash=context.ip_hash,
            user_agent=context.user_agent,
            idempotency_key=idempotency_key,
            customer_id=customer_id,
            total_estimate=total_estimate,
            currency=currency,
            items=items,
            attachments=(
                [
                    RequestAttachment(
                        filename=attachment.filename,
                        content_type=attachment.content_type,
                        size_bytes=attachment.size,
                        sha256=attachment.sha256,
                        data=attachment.data,
                    )
                ]
                if attachment is not None
                else []
            ),
            status_history=[
                RequestStatusHistory(from_status=None, to_status=RequestStatus.NEW.value)
            ],
        )
        existing = await self._insert(request, idempotency_key)
        if existing is not None:
            return self._replay_quick(existing, customer_id)

        # ---------------------------------------------------- аудит
        # Как и у корзины: без имени, телефона и текста комментария.
        self.audit.record(
            action=RequestAuditAction.CREATED,
            entity_type=REQUEST_ENTITY,
            entity_id=request.id,
            actor=PUBLIC_ACTOR,
            changes={
                "number": number,
                "status": {"old": None, "new": RequestStatus.NEW.value},
                "source": source.value,
                "items_count": len(items),
                "unrecognized_count": len(resolved.unrecognized),
                "attachments_count": 1 if attachment is not None else 0,
                "total_estimate": str(total_estimate) if total_estimate is not None else None,
            },
            ip_hash=context.ip_hash,
            request_id=context.request_id,
        )

        outbox = self.events.request_created(
            request, attachments=[attachment.filename] if attachment is not None else []
        )
        outbox_ids = await self.events.outbox.identify(outbox)
        await self.commit()
        # Побудка воркера — после коммита, как и у корзины.
        await wake_worker(self.notifications, outbox_ids)

        logger.info(
            "quick_request_created",
            request_id=request.id,
            number=number,
            source=source.value,
            items=len(items),
            unrecognized=len(resolved.unrecognized),
            attachment=attachment is not None,
        )
        created = self._to_created(request)
        return PublicQuickRequestCreated(
            **created.model_dump(),
            mode=payload.mode,
            unrecognized=resolved.unrecognized,
            below_minimum=resolved.below_minimum,
            attachment=(
                PublicAttachmentRead(filename=attachment.filename, size_bytes=attachment.size)
                if attachment is not None
                else None
            ),
        )

    # ------------------------------------------------------------ состав
    async def _resolve_one_click(
        self, payload: PublicQuickRequestCreate, resolved: _Resolved
    ) -> None:
        """Заказ в 1 клик — одна позиция по правилам корзины.

        Артикул приходит из карточки товара на витрине, поэтому
        неизвестный товар или количество ниже минимума — ошибка, как
        в корзине, а не пометка для менеджера.
        """
        sku = payload.product_sku or ""
        products = await self.repository.get_orderable_products([sku])
        entry = products.get(sku)
        if entry is None:
            raise RequestProductUnavailableError(details={"skus": [sku]})
        minimum = entry.product.min_order_qty
        # Без количества — минимальная партия (у штучного товара — одна штука).
        quantity = payload.quantity or (minimum if minimum > 0 else Decimal(1))
        if quantity < minimum:
            raise RequestQuantityBelowMinimumError(
                details={
                    "items": [
                        {"sku": sku, "quantity": str(quantity), "min_order_qty": str(minimum)}
                    ]
                }
            )
        resolved.lines[sku] = (entry, quantity)
        if payload.product_color is not None:
            [color] = await self.resolve_colors([(entry, payload.product_color)])
            if color is not None:
                resolved.colors[sku] = color

    async def _resolve_sku_list(self, text: str, resolved: _Resolved) -> None:
        entries = parse_sku_list(text)
        if not entries:
            raise QuickRequestEmptyError
        if len(entries) > MAX_REQUEST_ITEMS:
            raise RequestTooManyItemsError(details={"max_items": MAX_REQUEST_ITEMS})

        candidates = [sku for entry in entries for sku, _ in entry.candidates]
        products = await self.repository.find_orderable_products_ci(candidates)

        for entry in entries:
            match = next(
                (
                    (products[sku.upper()], quantity)
                    for sku, quantity in entry.candidates
                    if sku.upper() in products
                ),
                None,
            )
            if match is None:
                resolved.unrecognized.append(entry.raw)
                continue
            product_entry, quantity = match
            product = product_entry.product
            # Без количества — минимальная партия: меньше заказать нельзя,
            # а больше клиент не просил.
            if quantity is None:
                quantity = product.min_order_qty if product.min_order_qty > 0 else Decimal(1)
            # Один артикул в нескольких строках — одна позиция: иначе
            # непонятно, какое количество определяет ступень цены.
            if product.sku in resolved.lines:
                previous = resolved.lines[product.sku][1]
                quantity = previous + quantity
            resolved.lines[product.sku] = (product_entry, quantity)

        if len(resolved.lines) > MAX_REQUEST_ITEMS:
            raise RequestTooManyItemsError(details={"max_items": MAX_REQUEST_ITEMS})

        for product_entry, quantity in resolved.lines.values():
            minimum = product_entry.product.min_order_qty
            if quantity < minimum:
                resolved.below_minimum.append(
                    QuickRequestBelowMinimum(
                        sku=product_entry.product.sku,
                        quantity=quantity,
                        min_order_qty=minimum,
                    )
                )

    # -------------------------------------------------------- внутреннее
    def _comment(self, comment: str | None, resolved: _Resolved) -> str | None:
        """Комментарий клиента и заметки разбора для менеджера.

        Нераспознанные строки дописываются как есть: менеджер должен
        видеть то, что написал клиент, а не нашу интерпретацию.
        """
        parts: list[str] = []
        if comment:
            parts.append(comment)
        if resolved.unrecognized:
            lines = resolved.unrecognized[:MAX_NOTED_LINES]
            hidden = len(resolved.unrecognized) - len(lines)
            block = "Не найдено в каталоге:\n" + "\n".join(lines)
            if hidden > 0:
                block += f"\n… и ещё {hidden}"
            parts.append(block)
        if resolved.below_minimum:
            parts.append(
                "Меньше минимальной партии:\n"
                + "\n".join(
                    f"{item.sku}: {_format_quantity(item.quantity)} "
                    f"(минимум {_format_quantity(item.min_order_qty)})"
                    for item in resolved.below_minimum
                )
            )
        if not parts:
            return None
        # Колонка — TEXT, но форма ограничивает комментарий; заметки
        # разбора не должны раздувать заявку сверх разумного.
        return "\n\n".join(parts)[: MAX_COMMENT_LENGTH * 3]

    def _replay_quick(
        self, existing: Request, customer_id: int | None
    ) -> PublicQuickRequestCreated:
        if existing.customer_id != customer_id:
            raise IdempotencyKeyConflictError
        mode = _MODE_BY_SOURCE.get(existing.source)
        if mode is None:
            # Ключ уже использован обычной заявкой из корзины.
            raise IdempotencyKeyConflictError
        attachment = existing.attachments[0] if existing.attachments else None
        return PublicQuickRequestCreated(
            **self._to_created(existing).model_dump(),
            mode=mode,
            attachment=(
                PublicAttachmentRead(filename=attachment.filename, size_bytes=attachment.size_bytes)
                if attachment is not None
                else None
            ),
        )
