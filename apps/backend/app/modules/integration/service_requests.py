"""Выгрузка заявок в учётную систему (сайт → 1С).

Поток односторонний: заявки создаёт сайт, 1С их забирает и
подтверждает приём. Обратно статусы не приходят — ими управляют
менеджеры в админке.

Подтверждение (`ack`) идемпотентно: повторное подтверждение уже
выгруженной заявки возвращает прежние `external_id` и `exported_at`,
а не переписывает их. Иначе повтор из-за таймаута сети затирал бы
номер документа 1С.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.geo.models import Region
from app.modules.integration.audit import INTEGRATION_ACTOR, IntegrationAuditAction
from app.modules.integration.models import ApiKey
from app.modules.integration.schemas import (
    AckResult,
    IntegrationRequest,
    IntegrationRequestItem,
    IntegrationRequestPage,
)
from app.modules.requests.models import Request

# Заявок за один запрос. 1С забирает их пачками по расписанию.
MAX_REQUESTS_PER_PULL = 200


class RequestNotFoundError(NotFoundError):
    code = "request_not_found"
    message = "Заявка не найдена"


class IntegrationRequestService(BaseService):
    def __init__(self, session: AsyncSession, api_key: ApiKey | None = None) -> None:
        super().__init__(session)
        self.api_key = api_key
        self.audit = AuditService(session)

    async def list_requests(
        self,
        *,
        status: str | None = None,
        since: datetime | None = None,
        only_pending_export: bool = True,
        limit: int = MAX_REQUESTS_PER_PULL,
    ) -> IntegrationRequestPage:
        """Заявки для выгрузки.

        По умолчанию отдаются только невыгруженные: 1С забирает их,
        подтверждает и больше не видит. Полная выборка нужна лишь
        для разбора инцидентов, поэтому включается явно.
        """
        conditions: list[ColumnElement[bool]] = [Request.deleted_at.is_(None)]
        if only_pending_export:
            conditions.append(Request.exported_at.is_(None))
        if status:
            conditions.append(Request.status == status)
        if since is not None:
            conditions.append(Request.created_at >= since)

        total = (
            await self.session.execute(
                select(func.count()).select_from(select(Request.id).where(*conditions).subquery())
            )
        ).scalar_one()

        # Название региона берётся джойном: связи `region` у заявки нет,
        # а ленивая подгрузка в асинхронной сессии — прямая ошибка.
        rows = (
            await self.session.execute(
                select(Request, Region.name)
                .outerjoin(Region, Region.id == Request.region_id)
                .where(*conditions)
                .options(selectinload(Request.items))
                .order_by(Request.created_at)
                .limit(min(limit, MAX_REQUESTS_PER_PULL))
            )
        ).all()
        return IntegrationRequestPage(
            items=[self._to_schema(request, region) for request, region in rows], total=total
        )

    async def acknowledge(self, request_uuid: UUID, external_id: str | None) -> AckResult:
        request = (
            await self.session.execute(
                select(Request).where(Request.uuid == request_uuid, Request.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if request is None:
            raise RequestNotFoundError

        if request.exported_at is not None:
            # Уже подтверждена: повтор ничего не меняет.
            return AckResult(
                uuid=str(request.uuid),
                external_id=request.external_id,
                exported_at=request.exported_at.isoformat(),
            )

        now = datetime.now(UTC)
        request.exported_at = now
        if external_id:
            request.external_id = external_id
        self.audit.record(
            action=IntegrationAuditAction.REQUEST_EXPORTED,
            entity_type="request",
            entity_id=request.id,
            actor=INTEGRATION_ACTOR,
            changes={"external_id": external_id, "exported_at": now.isoformat()},
        )
        await self.commit()
        return AckResult(
            uuid=str(request.uuid), external_id=request.external_id, exported_at=now.isoformat()
        )

    @staticmethod
    def _to_schema(request: Request, region_name: str | None) -> IntegrationRequest:
        items = sorted(request.items, key=lambda item: (item.sort_order, item.id or 0))
        return IntegrationRequest(
            uuid=str(request.uuid),
            number=request.number,
            status=request.status,
            created_at=request.created_at.isoformat(),
            customer_name=request.customer_name,
            company=request.company,
            phone=request.phone,
            email=request.email,
            region=region_name,
            comment=request.comment,
            currency=request.currency,
            total_estimate=request.total_estimate,
            items=[
                IntegrationRequestItem(
                    sku=item.sku_snapshot,
                    name=item.name_snapshot,
                    unit=item.unit_snapshot,
                    quantity=item.quantity,
                    unit_price=item.unit_price_snapshot,
                    line_total=item.line_total_snapshot,
                    color=item.color_code_snapshot,
                    color_name=item.color_name_snapshot,
                )
                for item in items
            ],
            exported_at=request.exported_at.isoformat() if request.exported_at else None,
        )
