"""Доступ к данным домена пользователей."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Select, Update, func, or_, select, update

from app.core.pagination import PageParams
from app.core.repository import BaseRepository
from app.modules.users.enums import UserRole
from app.modules.users.models import RefreshToken, User

# Длиннее значения в колонках не бывает — фильтр сверх этого заведомо пуст.
MAX_SEARCH_LENGTH = 255


@dataclass(frozen=True)
class UserFilters:
    search: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        """Поиск по email.

        Регистр не нормализуется в коде: колонка объявлена как CITEXT,
        и сравнение выполняет сама БД. Дублирование этой логики
        в приложении рано или поздно разойдётся с индексом.
        """
        return await self.find_one_by(email=email)

    async def get_by_uuid(self, user_uuid: uuid.UUID) -> User | None:
        return await self.find_one_by(uuid=user_uuid)

    def _filtered(self, filters: UserFilters) -> Select[tuple[User]]:
        # Удалённые сотрудники скрыты базовым запросом: они остаются
        # авторами комментариев и записей аудита, но в списке не нужны.
        query = self._base_query()
        if filters.search:
            pattern = f"%{filters.search}%"
            query = query.where(or_(User.full_name.ilike(pattern), User.email.ilike(pattern)))
        if filters.role is not None:
            query = query.where(User.role == filters.role.value)
        if filters.is_active is not None:
            query = query.where(User.is_active.is_(filters.is_active))
        return query

    async def list_users(
        self, *, filters: UserFilters, params: PageParams
    ) -> tuple[Sequence[User], int]:
        query = self._filtered(filters)
        total = (
            await self.session.execute(
                select(func.count()).select_from(query.with_only_columns(User.id).subquery())
            )
        ).scalar_one()
        rows = await self.session.execute(
            # Отключённые уходят вниз, дальше — по имени: список читают
            # глазами, и работающие сотрудники нужны первыми.
            query.order_by(User.is_active.desc(), User.full_name, User.id)
            .limit(params.limit)
            .offset(params.offset)
        )
        return rows.scalars().all(), total


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_hash(
        self, token_hash: str, *, for_update: bool = False
    ) -> RefreshToken | None:
        """Поиск токена по хешу.

        for_update=True берёт блокировку строки (SELECT ... FOR UPDATE).
        Нужна при ротации: без неё два одновременных запроса с одним
        токеном оба видят revoked_at IS NULL и оба выдают новую пару.
        С блокировкой второй ждёт коммита первого и в режиме READ
        COMMITTED перечитывает уже отозванную строку — то есть попадает
        в штатную ветку обнаружения переиспользования.
        """
        query = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        if for_update:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def _revoke(self, statement: Update) -> int:
        result = await self.session.execute(statement)
        return cast("CursorResult[Any]", result).rowcount

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        """Отзывает всю цепочку ротации.

        Вызывается при обнаружении повторного использования токена:
        раз старый токен всплыл, цепочка скомпрометирована целиком,
        и отзывать только его бессмысленно.
        """
        return await self._revoke(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )

    async def revoke_all_for_user(self, user_id: int) -> int:
        return await self._revoke(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
