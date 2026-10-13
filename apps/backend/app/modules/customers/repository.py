"""Доступ к данным учётных записей клиентов и их токенов."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Update, select, update

from app.core.repository import BaseRepository
from app.modules.customers.models import Customer, CustomerActionToken, CustomerRefreshToken
from app.modules.geo.models import Region


class CustomerRepository(BaseRepository[Customer]):
    model = Customer

    async def get_by_email(self, email: str) -> Customer | None:
        """Регистр сравнивает БД: колонка CITEXT."""
        return await self.find_one_by(email=email)

    async def get_by_uuid(self, customer_uuid: uuid.UUID) -> Customer | None:
        return await self.find_one_by(uuid=customer_uuid)

    async def get_active_region(self, region_id: int) -> Region | None:
        query = select(Region).where(Region.id == region_id, Region.is_active.is_(True))
        return (await self.session.execute(query)).scalars().first()

    async def get_region(self, region_id: int | None) -> Region | None:
        if region_id is None:
            return None
        return await self.session.get(Region, region_id)


async def _rowcount(session: Any, statement: Update) -> int:
    result = await session.execute(statement)
    return cast("CursorResult[Any]", result).rowcount


class CustomerRefreshTokenRepository(BaseRepository[CustomerRefreshToken]):
    model = CustomerRefreshToken

    async def get_by_hash(
        self, token_hash: str, *, for_update: bool = False
    ) -> CustomerRefreshToken | None:
        """for_update: проверка «не отозван ли» и отзыв при ротации неделимы
        (см. AuthService.refresh в модуле users)."""
        query = select(CustomerRefreshToken).where(CustomerRefreshToken.token_hash == token_hash)
        if for_update:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        return await _rowcount(
            self.session,
            update(CustomerRefreshToken)
            .where(
                CustomerRefreshToken.family_id == family_id,
                CustomerRefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC)),
        )

    async def revoke_all_for_customer(self, customer_id: int) -> int:
        return await _rowcount(
            self.session,
            update(CustomerRefreshToken)
            .where(
                CustomerRefreshToken.customer_id == customer_id,
                CustomerRefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC)),
        )


class CustomerActionTokenRepository(BaseRepository[CustomerActionToken]):
    model = CustomerActionToken

    async def get_by_hash_for_update(self, token_hash: str) -> CustomerActionToken | None:
        """Блокировка строки: два одновременных предъявления одной ссылки
        не должны оба пройти проверку `used_at IS NULL`."""
        query = (
            select(CustomerActionToken)
            .where(CustomerActionToken.token_hash == token_hash)
            .with_for_update()
        )
        return (await self.session.execute(query)).scalar_one_or_none()

    async def invalidate_pending(self, customer_id: int, purpose: str) -> int:
        """Гасит неиспользованные токены назначения перед выпуском нового:
        действует только ссылка из последнего письма."""
        return await _rowcount(
            self.session,
            update(CustomerActionToken)
            .where(
                CustomerActionToken.customer_id == customer_id,
                CustomerActionToken.purpose == purpose,
                CustomerActionToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC)),
        )
