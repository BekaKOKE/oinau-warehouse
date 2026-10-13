"""Бизнес-правила Admin API справочника цветов и цветов товара.

Остаток цвета — ручная разбивка, общий остаток товара по складам он не
меняет (см. app/modules/colors/models.py). Поэтому ответ несёт обе
суммы: админка показывает расхождение, а не исправляет его молча.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.integrity import guard_unique
from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.catalog.models import Product
from app.modules.catalog.mutability import ensure_mutable
from app.modules.colors.exceptions import ColorInactiveError, ColorInUseError
from app.modules.colors.integrity import COLOR_CONSTRAINT_ERRORS
from app.modules.colors.models import Color, ProductColor
from app.modules.colors.repository import ColorRepository
from app.modules.colors.schemas_admin import (
    ColorCreate,
    ColorRead,
    ColorUpdate,
    ProductColorRead,
    ProductColorsRead,
    ProductColorsUpdate,
)
from app.modules.inventory.availability import resolve_availability
from app.modules.inventory.repository_admin import AdminStockRepository
from app.modules.inventory.service_admin import AdminStockService
from app.modules.users.models import User

COLOR_ENTITY = "color"
PRODUCT_COLORS_ENTITY = "product_colors"


class ColorAuditAction:
    CREATED = "color.created"
    UPDATED = "color.updated"
    DELETED = "color.deleted"
    PRODUCT_COLORS_UPDATED = "product.colors_updated"


def _audit_entry(code: str, quantity: Decimal, price_delta: Decimal) -> dict[str, str]:
    # Точность колонок: иначе «10» из запроса и «10.000» из базы
    # выглядели бы изменением.
    return {
        "color": code,
        "quantity": str(quantity.quantize(Decimal("0.001"))),
        "price_delta": str(price_delta.quantize(Decimal("0.01"))),
    }


class AdminColorService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = ColorRepository(session)
        self.audit = AuditService(session)

    async def list_colors(self, *, is_active: bool | None = None) -> list[ColorRead]:
        colors = await self.repository.list_colors(is_active=is_active)
        counts = await self.repository.usage_counts([color.id for color in colors])
        return [self._to_read(color, counts.get(color.id, 0)) for color in colors]

    @guard_unique(COLOR_CONSTRAINT_ERRORS)
    async def create_color(self, payload: ColorCreate, actor: User) -> ColorRead:
        color = Color(**payload.model_dump())
        self.session.add(color)
        await self.session.flush()
        self.audit.record(
            action=ColorAuditAction.CREATED,
            entity_type=COLOR_ENTITY,
            entity_id=color.id,
            user_id=actor.id,
            changes=payload.model_dump(),
        )
        await self.commit()
        return self._to_read(color, 0)

    async def update_color(self, color_id: int, payload: ColorUpdate, actor: User) -> ColorRead:
        color = await self._require(color_id)
        changes: dict[str, Any] = {}
        for field, value in payload.model_dump(exclude_unset=True).items():
            if value is None or getattr(color, field) == value:
                continue
            changes[field] = {"old": getattr(color, field), "new": value}
            setattr(color, field, value)
        if changes:
            await self.session.flush()
            self.audit.record(
                action=ColorAuditAction.UPDATED,
                entity_type=COLOR_ENTITY,
                entity_id=color.id,
                user_id=actor.id,
                changes=changes,
            )
        await self.commit()
        counts = await self.repository.usage_counts([color.id])
        return self._to_read(color, counts.get(color.id, 0))

    async def delete_color(self, color_id: int, actor: User) -> None:
        color = await self._require(color_id)
        counts = await self.repository.usage_counts([color.id])
        if counts.get(color.id):
            # Проверка в сервисе даёт понятный ответ; внешний ключ
            # RESTRICT страхует от гонки.
            raise ColorInUseError(details={"products_count": counts[color.id]})
        await self.session.delete(color)
        self.audit.record(
            action=ColorAuditAction.DELETED,
            entity_type=COLOR_ENTITY,
            entity_id=color.id,
            user_id=actor.id,
            changes={"code": color.code, "name": color.name},
        )
        await self.commit()

    async def _require(self, color_id: int) -> Color:
        color = await self.repository.get_color(color_id)
        if color is None:
            raise NotFoundError("Цвет не найден")
        return color

    def _to_read(self, color: Color, products_count: int) -> ColorRead:
        return ColorRead(
            id=color.id,
            code=color.code,
            name=color.name,
            hex=color.hex,
            sort_order=color.sort_order,
            is_active=color.is_active,
            products_count=products_count,
        )


class AdminProductColorService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repository = ColorRepository(session)
        self.stock = AdminStockRepository(session)
        self.audit = AuditService(session)

    async def get_product_colors(self, product_id: int) -> ProductColorsRead:
        product = await self._require_product(product_id)
        items = await self.repository.product_colors(product.id)
        return await self._to_read(product, items)

    @guard_unique(COLOR_CONSTRAINT_ERRORS)
    async def set_product_colors(
        self, product_id: int, payload: ProductColorsUpdate, actor: User
    ) -> ProductColorsRead:
        """Полная замена набора цветов товара.

        Отключённый цвет нельзя добавить заново, но уже привязанный
        сохраняется при повторной отправке: иначе отключение цвета
        в справочнике мешало бы править остальные цвета товара.
        """
        product = ensure_mutable(await self._require_product(product_id))
        # Сериализует параллельные сохранения цветов одного товара.
        await self.stock.lock_product(product.id)

        current = await self.repository.product_colors(product.id)
        attached = {item.color_id for item in current}
        colors = await self.repository.get_colors_by_ids([item.color_id for item in payload.items])
        for item in payload.items:
            color = colors.get(item.color_id)
            if color is None:
                raise NotFoundError(f"Цвет {item.color_id} не найден")
            if not color.is_active and color.id not in attached:
                raise ColorInactiveError(details={"color_id": color.id})

        old = [_audit_entry(item.color.code, item.quantity, item.price_delta) for item in current]
        new = [
            _audit_entry(colors[item.color_id].code, item.quantity, item.price_delta)
            for item in payload.items
        ]

        await self.repository.delete_product_colors(product.id)
        for index, item in enumerate(payload.items):
            self.session.add(
                ProductColor(
                    product_id=product.id,
                    color_id=item.color_id,
                    quantity=item.quantity,
                    price_delta=item.price_delta,
                    sort_order=index,
                )
            )
        await self.session.flush()
        if old != new:
            self.audit.record(
                action=ColorAuditAction.PRODUCT_COLORS_UPDATED,
                entity_type=PRODUCT_COLORS_ENTITY,
                entity_id=product.id,
                user_id=actor.id,
                changes={"old": old, "new": new},
            )
        await self.commit()
        # Удалённые строки ещё лежат в identity map сессии. Идентификатор
        # берётся из аргумента: атрибуты истёкшего товара читать нельзя.
        self.session.expire_all()
        return await self.get_product_colors(product_id)

    async def _require_product(self, product_id: int) -> Product:
        product = await self.stock.get_product(product_id)
        if product is None:
            raise NotFoundError("Товар не найден")
        return product

    async def _to_read(self, product: Product, items: list[ProductColor]) -> ProductColorsRead:
        stock = await AdminStockService(self.session).get_product_stock(product.id)
        return ProductColorsRead(
            product_id=product.id,
            sku=product.sku,
            unit=product.unit,
            items=[
                ProductColorRead(
                    color_id=item.color_id,
                    code=item.color.code,
                    name=item.color.name,
                    hex=item.color.hex,
                    color_is_active=item.color.is_active,
                    quantity=item.quantity,
                    price_delta=item.price_delta,
                    # Тот же resolver, что у витрины, — по остатку цвета.
                    public_availability=resolve_availability(
                        pricing_type=product.pricing_type,
                        stock_display_override=product.stock_display_override,
                        available_quantity=item.quantity,
                    ),
                )
                for item in items
            ],
            colors_total=sum((item.quantity for item in items), Decimal(0)),
            stock_total=stock.total_available,
        )
