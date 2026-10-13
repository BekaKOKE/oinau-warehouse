"""Integration API — /api/v1/integration.

Точка подключения внешних систем (в первую очередь 1С).
Аутентификация — ключ из таблицы `api_keys` в заголовке `X-API-Key`
плюс allowlist по IP. Не JWT сотрудника и не сессия.

СТАТУС КОНТРАКТА. Реальная спецификация обмена от заказчика ещё не
получена. Реализован нейтральный контракт сайта (docs/architecture.md,
7.3): он полностью рабочий и покрыт тестами, но перед включением
боевого обмена (`ONE_C_INTEGRATION_ENABLED=true`) должен быть сверен
с выгрузкой конкретной конфигурации 1С. Формат 1С в схемы не
протекает намеренно — преобразование делается на стороне 1С или
тонким адаптером.

Что обмен НЕ делает:
  * не создаёт товары и склады — только обновляет существующие;
  * не удаляет ничего по отсутствию в пакете;
  * не трогает описания, SEO, изображения и характеристики сайта.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.logging import request_id_ctx
from app.modules.integration.deps import (
    ApiKeyDep,
    guard_body_size,
    integration_rate_limit,
    require_scope,
)
from app.modules.integration.exceptions import BatchTooLargeError
from app.modules.integration.models import ApiKey
from app.modules.integration.schemas import (
    AckResult,
    IntegrationHealth,
    IntegrationRequestPage,
    PriceBatch,
    ProductBatch,
    StockBatch,
    SyncResult,
)
from app.modules.integration.security import IntegrationScope
from app.modules.integration.service_requests import IntegrationRequestService
from app.modules.integration.service_sync import (
    PriceSyncService,
    ProductSyncService,
    StockSyncService,
)

router = APIRouter(prefix="/integration", tags=["integration"])

# Порядок зависимостей: размер тела проверяется до его разбора,
# норма частоты — после аутентификации (лимит считается на ключ).
COMMON = [Depends(guard_body_size), Depends(integration_rate_limit)]

CatalogWriter = Annotated[ApiKey, Depends(require_scope(IntegrationScope.CATALOG_WRITE))]
PricingWriter = Annotated[ApiKey, Depends(require_scope(IntegrationScope.PRICING_WRITE))]
InventoryWriter = Annotated[ApiKey, Depends(require_scope(IntegrationScope.INVENTORY_WRITE))]
RequestsReader = Annotated[ApiKey, Depends(require_scope(IntegrationScope.REQUESTS_READ))]


def payload_hash(payload: object) -> str:
    """SHA-256 канонизированного пакета — ключ защиты от повтора.

    Канонизация (sort_keys, фиксированные разделители) нужна, чтобы
    один и тот же пакет с переставленными ключами JSON давал тот же
    хеш. Само тело нигде не сохраняется — только эта сумма.
    """
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def ensure_batch_size(count: int) -> None:
    if count > settings.INTEGRATION_MAX_BATCH_ITEMS:
        raise BatchTooLargeError(
            details={"limit": settings.INTEGRATION_MAX_BATCH_ITEMS, "received": count}
        )


@router.get("/health", response_model=IntegrationHealth, summary="Проверка связи")
async def health(key: ApiKeyDep) -> IntegrationHealth:
    """Подтверждает, что ключ принят. Реквизитов наружу не отдаёт."""
    return IntegrationHealth(
        status="ok",
        enabled=settings.ONE_C_INTEGRATION_ENABLED,
        key_name=key.name,
        scopes=list(key.scopes),
        server_time=datetime.now(UTC).isoformat(),
    )


@router.post(
    "/catalog/products/bulk-upsert",
    response_model=SyncResult,
    dependencies=COMMON,
    summary="Обновить товары",
)
async def upsert_products(
    session: SessionDep,
    key: CatalogWriter,
    batch: Annotated[ProductBatch, Body()],
) -> SyncResult:
    """Обновляет существующие товары. Новых не заводит, старых не удаляет.

    Сопоставление: `external_id`, при его отсутствии — `sku`.
    Поля, которых нет в схеме (описание, SEO, изображения), обмен
    затронуть не может.
    """
    ensure_batch_size(len(batch.items))
    return await ProductSyncService(session, key).apply(
        batch.items,
        payload_hash=payload_hash(batch.model_dump(mode="json")),
        request_id=request_id_ctx.get(),
    )


@router.post(
    "/pricing/bulk-upsert",
    response_model=SyncResult,
    dependencies=COMMON,
    summary="Обновить цены",
)
async def upsert_pricing(
    session: SessionDep,
    key: PricingWriter,
    batch: Annotated[PriceBatch, Body()],
) -> SyncResult:
    """Заменяет набор ценовых ступеней товара в указанном прайс-листе."""
    ensure_batch_size(len(batch.items))
    return await PriceSyncService(session, key).apply(
        batch.items,
        payload_hash=payload_hash(batch.model_dump(mode="json")),
        request_id=request_id_ctx.get(),
    )


@router.post(
    "/inventory/bulk-upsert",
    response_model=SyncResult,
    dependencies=COMMON,
    summary="Обновить остатки",
)
async def upsert_inventory(
    session: SessionDep,
    key: InventoryWriter,
    batch: Annotated[StockBatch, Body()],
) -> SyncResult:
    """Остаток по паре «товар × склад».

    Свободный остаток (`quantity - reserved`) не хранится, а
    вычисляется. Публичный статус наличия считается по активным
    складам; точные количества посетителю сайта не отдаются.
    """
    ensure_batch_size(len(batch.items))
    return await StockSyncService(session, key).apply(
        batch.items,
        payload_hash=payload_hash(batch.model_dump(mode="json")),
        request_id=request_id_ctx.get(),
    )


@router.get(
    "/requests",
    response_model=IntegrationRequestPage,
    dependencies=[Depends(integration_rate_limit)],
    summary="Заявки для выгрузки",
)
async def list_requests(
    session: SessionDep,
    _: RequestsReader,
    status: Annotated[str | None, Query(max_length=32)] = None,
    since: Annotated[datetime | None, Query(description="Созданные не раньше")] = None,
    include_exported: Annotated[bool, Query(description="Включая уже подтверждённые")] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
) -> IntegrationRequestPage:
    """По умолчанию — только те, что ещё не подтверждены учётной системой."""
    return await IntegrationRequestService(session).list_requests(
        status=status,
        since=since,
        only_pending_export=not include_exported,
        limit=limit,
    )


@router.post(
    "/requests/{request_uuid}/ack",
    response_model=AckResult,
    dependencies=COMMON,
    summary="Подтвердить приём заявки",
)
async def acknowledge_request(
    session: SessionDep,
    key: RequestsReader,
    request_uuid: Annotated[UUID, Path()],
    external_id: Annotated[str | None, Body(embed=True, max_length=64)] = None,
) -> AckResult:
    """Помечает заявку выгруженной. Повтор возвращает прежний результат."""
    return await IntegrationRequestService(session, key).acknowledge(request_uuid, external_id)


__all__ = ["router"]
