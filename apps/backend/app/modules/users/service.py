"""Сервис аутентификации.

Все правила входа собраны здесь: блокировка после серии неудач, ротация
refresh-токенов, обнаружение переиспользования, запись в аудит.
Роутер только валидирует вход и раскладывает результат по HTTP.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.core.service import BaseService
from app.modules.audit.service import AuditAction, AuditService
from app.modules.users.exceptions import (
    AccountLockedError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from app.modules.users.models import RefreshToken, User
from app.modules.users.repository import RefreshTokenRepository, UserRepository

logger = get_logger(__name__)


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime


@dataclass(frozen=True)
class RequestContext:
    """Метаданные HTTP-запроса, нужные для аудита и антифрода."""

    ip_hash: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


class AuthService(BaseService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------- вход
    async def authenticate(
        self, email: str, password: str, context: RequestContext
    ) -> tuple[User, IssuedTokens]:
        user = await self.users.get_by_email(email)

        # Проверка выполняется даже при отсутствии пользователя: иначе
        # разница во времени ответа выдаёт, какие email существуют.
        password_ok = verify_password(password, user.password_hash if user else None)

        if user is not None and self._is_locked(user):
            self.audit.record(
                action=AuditAction.LOGIN_BLOCKED,
                entity_type="user",
                entity_id=user.id,
                user_id=user.id,
                ip_hash=context.ip_hash,
                request_id=context.request_id,
            )
            await self.commit()
            # О блокировке сообщаем только тому, кто предъявил верный
            # пароль. Иначе форма входа превращается в детектор
            # существующих учётных записей: достаточно пять раз ошибиться
            # и посмотреть, сменился ли ответ с 401 на 403.
            # Счётчик неудач при этом не увеличивается — иначе перебор
            # продлевал бы блокировку легитимному сотруднику бесконечно.
            if password_ok and user.is_active:
                raise AccountLockedError
            raise InvalidCredentialsError

        if user is None or not password_ok or not user.is_active:
            if user is not None:
                await self._register_failed_attempt(user, context)
            await self.commit()
            raise InvalidCredentialsError

        return user, await self._issue_session(user, context)

    def _is_locked(self, user: User) -> bool:
        return user.locked_until is not None and user.locked_until > datetime.now(UTC)

    async def _register_failed_attempt(self, user: User, context: RequestContext) -> None:
        user.failed_login_count += 1
        if user.failed_login_count >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
            user.locked_until = datetime.now(UTC) + timedelta(
                minutes=settings.LOGIN_LOCKOUT_MINUTES
            )
            user.failed_login_count = 0
        self.audit.record(
            action=AuditAction.LOGIN_FAILED,
            entity_type="user",
            entity_id=user.id,
            user_id=user.id,
            ip_hash=context.ip_hash,
            request_id=context.request_id,
        )

    async def _issue_session(self, user: User, context: RequestContext) -> IssuedTokens:
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = datetime.now(UTC)

        tokens = await self._create_token_pair(user, family_id=uuid.uuid4(), context=context)
        self.audit.record(
            action=AuditAction.LOGIN_SUCCESS,
            entity_type="user",
            entity_id=user.id,
            user_id=user.id,
            ip_hash=context.ip_hash,
            request_id=context.request_id,
        )
        await self.commit()
        return tokens

    async def _create_token_pair(
        self, user: User, *, family_id: uuid.UUID, context: RequestContext
    ) -> IssuedTokens:
        access_token, expires_in = create_access_token(subject=user.uuid, role=user.role)

        refresh_raw = generate_refresh_token()
        expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)
        self.tokens.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_refresh_token(refresh_raw),
                family_id=family_id,
                expires_at=expires_at,
                user_agent=context.user_agent,
                ip_hash=context.ip_hash,
            )
        )
        await self.session.flush()

        return IssuedTokens(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=refresh_raw,
            refresh_expires_at=expires_at,
        )

    # ---------------------------------------------------------- обновление
    async def refresh(self, raw_token: str, context: RequestContext) -> tuple[User, IssuedTokens]:
        """Ротация refresh-токена с обнаружением переиспользования.

        Каждое обновление выдаёт новый refresh и отзывает старый. Если
        приходит уже отозванный токен — значит, его копия у кого-то ещё,
        и вся цепочка (family) отзывается целиком. Легитимный
        пользователь будет вынужден войти заново; это цена того, что
        украденный токен перестаёт работать сразу.

        Строка токена блокируется на время транзакции: проверка
        "не отозван ли" и сам отзыв обязаны быть неделимы, иначе два
        параллельных запроса с одним токеном оба пройдут проверку
        и получат по действующей паре.
        """
        stored = await self.tokens.get_by_hash(hash_refresh_token(raw_token), for_update=True)
        if stored is None:
            raise InvalidRefreshTokenError

        if stored.revoked_at is not None:
            revoked = await self.tokens.revoke_family(stored.family_id)
            self.audit.record(
                action=AuditAction.TOKEN_REUSE_DETECTED,
                entity_type="user",
                entity_id=stored.user_id,
                user_id=stored.user_id,
                changes={"revoked_tokens": revoked},
                ip_hash=context.ip_hash,
                request_id=context.request_id,
            )
            await self.commit()
            logger.warning("refresh_token_reuse", user_id=stored.user_id)
            raise InvalidRefreshTokenError

        if stored.expires_at <= datetime.now(UTC):
            raise InvalidRefreshTokenError

        user = await self.users.get(stored.user_id)
        if user is None or not user.is_active:
            raise InvalidRefreshTokenError

        stored.revoked_at = datetime.now(UTC)
        tokens = await self._create_token_pair(user, family_id=stored.family_id, context=context)
        self.audit.record(
            action=AuditAction.TOKEN_REFRESHED,
            entity_type="user",
            entity_id=user.id,
            user_id=user.id,
            ip_hash=context.ip_hash,
            request_id=context.request_id,
        )
        await self.commit()
        return user, tokens

    # ---------------------------------------------------------------- выход
    async def logout(self, raw_token: str | None, context: RequestContext) -> None:
        """Отзывает всю цепочку текущей сессии.

        Ошибку не возвращает: выход из уже недействительной сессии —
        нормальный сценарий, а не проблема пользователя.
        """
        if not raw_token:
            return
        stored = await self.tokens.get_by_hash(hash_refresh_token(raw_token))
        if stored is None:
            return
        await self.tokens.revoke_family(stored.family_id)
        self.audit.record(
            action=AuditAction.LOGOUT,
            entity_type="user",
            entity_id=stored.user_id,
            user_id=stored.user_id,
            ip_hash=context.ip_hash,
            request_id=context.request_id,
        )
        await self.commit()

    # --------------------------------------------------------- смена пароля
    async def change_password(
        self, user: User, current_password: str, new_password: str, context: RequestContext
    ) -> None:
        """Смена пароля отзывает все сессии, кроме текущей... точнее — все.

        Отзываются все refresh-токены пользователя: смена пароля почти
        всегда следует за подозрением на компрометацию, и оставлять
        живые сессии в этот момент — противоречить самому смыслу
        операции. Пользователь войдёт заново.
        """
        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError

        user.password_hash = hash_password(new_password)
        user.password_changed_at = datetime.now(UTC)
        revoked = await self.tokens.revoke_all_for_user(user.id)

        self.audit.record(
            action=AuditAction.PASSWORD_CHANGED,
            entity_type="user",
            entity_id=user.id,
            user_id=user.id,
            changes={"revoked_sessions": revoked},
            ip_hash=context.ip_hash,
            request_id=context.request_id,
        )
        await self.commit()

    async def upgrade_password_hash_if_needed(self, user: User, password: str) -> None:
        """Прозрачно переписывает хеш при усилении параметров argon2."""
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
            await self.commit()
