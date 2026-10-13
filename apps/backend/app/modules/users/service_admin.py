"""Управление сотрудниками из админки — /api/v1/admin/users.

Право одно и существующее: `user.manage` (ADMIN и SUPERADMIN). Новых
прав и новой модели ролей не вводится — состав ролей по-прежнему задан
константами в `permissions.py`.

Что здесь принципиально:

* Пароль не покидает сервер ни в каком виде: на вход принимается,
  сохраняется только argon2id-хеш (общий `hash_password`), в ответах и
  в журнале аудита его нет.
* Отключение сотрудника действует немедленно: `get_current_user`
  читает пользователя из БД на каждый запрос, а все refresh-токены
  отзываются здесь же. Повторный вход и обновление сессии невозможны.
* Администратор не может ни отключить себя, ни сменить себе роль:
  иначе единственный администратор одним действием теряет доступ.
* Учётными записями SUPERADMIN управляет только SUPERADMIN. Без этого
  правила роль ADMIN (у неё есть `user.manage`) поднимала бы себе права
  до недоступных ей — достаточно завести второго суперадминистратора.

Удаления сотрудника здесь нет: увольнение — это отключение (is_active),
запись остаётся автором комментариев и аудита. Мягкое удаление
поддержано моделью, но через API не выполняется.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.integrity import guard_unique
from app.core.pagination import Page, PageParams
from app.core.security import hash_password
from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.users.enums import UserRole
from app.modules.users.exceptions import (
    EmailAlreadyExistsError,
    SelfDeactivationError,
    SelfRoleChangeError,
    SuperadminRequiredError,
    UserNotFoundError,
)
from app.modules.users.integrity import USER_UNIQUE_ERRORS
from app.modules.users.models import User
from app.modules.users.permissions import ROLE_PERMISSIONS
from app.modules.users.repository import RefreshTokenRepository, UserFilters, UserRepository
from app.modules.users.schemas import (
    RolePermissionsRead,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.modules.users.service import RequestContext

USER_ENTITY = "user"


class UserAdminAction:
    CREATED = "user.created"
    UPDATED = "user.updated"
    PASSWORD_RESET = "user.password_reset"  # noqa: S105


class AdminUserService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------- чтение
    async def list_users(self, *, filters: UserFilters, params: PageParams) -> Page[UserRead]:
        rows, total = await self.users.list_users(filters=filters, params=params)
        return Page.create([UserRead.model_validate(row) for row in rows], total, params)

    async def get_user(self, user_uuid: uuid.UUID) -> UserRead:
        return UserRead.model_validate(await self._require(user_uuid))

    @staticmethod
    def roles() -> list[RolePermissionsRead]:
        """Матрица «роль → права» в порядке объявления ролей."""
        return [
            RolePermissionsRead(role=role, permissions=sorted(ROLE_PERMISSIONS.get(role, ())))
            for role in UserRole
        ]

    # -------------------------------------------------------------- запись
    @guard_unique(USER_UNIQUE_ERRORS)
    async def create_user(
        self, payload: UserCreate, actor: User, context: RequestContext
    ) -> UserRead:
        self._ensure_may_assign(actor, payload.role)
        if await self.users.get_by_email(payload.email) is not None:
            raise EmailAlreadyExistsError

        user = User(
            email=payload.email,
            password_hash=hash_password(payload.password),
            full_name=payload.full_name,
            phone=payload.phone,
            role=payload.role.value,
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()

        self.audit.record(
            action=UserAdminAction.CREATED,
            entity_type=USER_ENTITY,
            entity_id=user.id,
            user_id=actor.id,
            changes={
                "email": {"old": None, "new": user.email},
                "full_name": {"old": None, "new": user.full_name},
                "role": {"old": None, "new": user.role},
            },
            ip_hash=context.ip_hash,
            request_id=context.request_id,
        )
        await self.commit()
        return UserRead.model_validate(user)

    async def update_user(
        self, user_uuid: uuid.UUID, payload: UserUpdate, actor: User, context: RequestContext
    ) -> UserRead:
        user = await self._require(user_uuid)
        self._ensure_may_manage(actor, user)

        fields = payload.model_dump(exclude_unset=True)
        changes: dict[str, Any] = {}

        if "role" in fields and fields["role"].value != user.role:
            if user.id == actor.id:
                raise SelfRoleChangeError
            self._ensure_may_assign(actor, fields["role"])
            changes["role"] = {"old": user.role, "new": fields["role"].value}
            user.role = fields["role"].value

        for field in ("full_name", "phone"):
            if field in fields and fields[field] != getattr(user, field):
                changes[field] = {"old": getattr(user, field), "new": fields[field]}
                setattr(user, field, fields[field])

        if "is_active" in fields and fields["is_active"] != user.is_active:
            if not fields["is_active"] and user.id == actor.id:
                raise SelfDeactivationError
            changes["is_active"] = {"old": user.is_active, "new": fields["is_active"]}
            user.is_active = fields["is_active"]
            if not user.is_active:
                # Отключение обрывает и выданные сессии: без этого
                # сотрудник продолжал бы обновлять токен до конца суток.
                changes["revoked_sessions"] = await self.tokens.revoke_all_for_user(user.id)

        if changes:
            self.audit.record(
                action=UserAdminAction.UPDATED,
                entity_type=USER_ENTITY,
                entity_id=user.id,
                user_id=actor.id,
                changes=changes,
                ip_hash=context.ip_hash,
                request_id=context.request_id,
            )

        if fields.get("password") is not None:
            await self._reset_password(user, fields["password"], actor, context)

        await self.commit()
        await self.session.refresh(user)
        return UserRead.model_validate(user)

    async def _reset_password(
        self, user: User, password: str, actor: User, context: RequestContext
    ) -> None:
        """Пароль, назначенный администратором.

        Тот же эффект, что у самостоятельной смены пароля: хеш argon2id,
        отметка `password_changed_at` (она обесценивает уже выданные
        access-токены немедленно) и отзыв всех refresh-токенов.
        """
        user.password_hash = hash_password(password)
        user.password_changed_at = datetime.now(UTC)
        revoked = await self.tokens.revoke_all_for_user(user.id)
        self.audit.record(
            action=UserAdminAction.PASSWORD_RESET,
            entity_type=USER_ENTITY,
            entity_id=user.id,
            user_id=actor.id,
            changes={"revoked_sessions": revoked},
            ip_hash=context.ip_hash,
            request_id=context.request_id,
        )

    # ------------------------------------------------------------ правила
    async def _require(self, user_uuid: uuid.UUID) -> User:
        user = await self.users.get_by_uuid(user_uuid)
        if user is None:
            raise UserNotFoundError
        return user

    @staticmethod
    def _ensure_may_assign(actor: User, role: UserRole) -> None:
        if role is UserRole.SUPERADMIN and actor.role != UserRole.SUPERADMIN.value:
            raise SuperadminRequiredError

    @staticmethod
    def _ensure_may_manage(actor: User, target: User) -> None:
        if target.role == UserRole.SUPERADMIN.value and actor.role != UserRole.SUPERADMIN.value:
            raise SuperadminRequiredError
