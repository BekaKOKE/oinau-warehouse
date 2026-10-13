"""Аутентификация клиентов B2B-кабинета.

Правила повторяют админку там, где они про безопасность (argon2id,
выравнивание времени ответа, блокировка после серии неудач, ротация
refresh-токенов с отзывом всей цепочки при переиспользовании), и
отличаются там, где у клиента другой жизненный цикл: самостоятельная
регистрация, подтверждение email, сброс пароля по ссылке.

Ни один ответ не раскрывает, заведён ли адрес: регистрация, повторная
отправка подтверждения и запрос сброса отвечают одинаково.

Письма уходят ПОСЛЕ коммита: ссылка на токен, который откатился вместе
с транзакцией, была бы нерабочей.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    JWT_CUSTOMER_AUDIENCE,
    create_access_token,
    generate_action_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.core.service import BaseService
from app.modules.audit.service import AuditService
from app.modules.customers.audit import CUSTOMER_ACTOR, CUSTOMER_ENTITY, CustomerAuditAction
from app.modules.customers.enums import CustomerTokenPurpose
from app.modules.customers.exceptions import (
    CustomerAccountLockedError,
    CustomerEmailNotVerifiedError,
    CustomerInvalidActionTokenError,
    CustomerInvalidCredentialsError,
    CustomerInvalidRefreshTokenError,
    CustomerRegionNotFoundError,
)
from app.modules.customers.mailer import AccountMailer
from app.modules.customers.models import Customer, CustomerActionToken, CustomerRefreshToken
from app.modules.customers.repository import (
    CustomerActionTokenRepository,
    CustomerRefreshTokenRepository,
    CustomerRepository,
)
from app.modules.customers.schemas_auth import CustomerRegister
from app.modules.users.service import RequestContext

logger = get_logger(__name__)

# Роль в токене: одна на всех клиентов. Права клиента определяются
# не ролью, а владением объектом (заявка, проект, уведомление).
CUSTOMER_ROLE = "CUSTOMER"


@dataclass(frozen=True)
class CustomerTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def password_version(customer: Customer) -> int:
    """Версия пароля для access-токена: момент смены в микросекундах.

    Сравнивать `iat` (целые секунды) с моментом смены пароля нельзя:
    токен, выданный в ту же секунду до сброса, прошёл бы проверку, а
    выданный сразу после — нет. Точное совпадение версии в токене и в
    БД такой неоднозначности не имеет.
    """
    if customer.password_changed_at is None:
        return 0
    return int(customer.password_changed_at.timestamp() * 1_000_000)


class CustomerAuthService(BaseService):
    def __init__(self, session: AsyncSession, mailer: AccountMailer) -> None:
        super().__init__(session)
        self.customers = CustomerRepository(session)
        self.refresh_tokens = CustomerRefreshTokenRepository(session)
        self.action_tokens = CustomerActionTokenRepository(session)
        self.audit = AuditService(session)
        self.mailer = mailer

    # --------------------------------------------------------- регистрация
    async def register(self, payload: CustomerRegister, context: RequestContext) -> None:
        """Регистрирует клиента или молча ничего не делает.

        Для уже заведённого адреса ответ тот же, что для нового: иначе
        форма регистрации стала бы способом проверить, работает ли
        компания с OINAU PRO. Если аккаунт существует, но не подтверждён,
        письмо с подтверждением отправляется заново — это и есть то,
        что нужно человеку, забывшему о первой регистрации.
        """
        region_id: int | None = None
        if payload.region_id is not None:
            region = await self.customers.get_active_region(payload.region_id)
            if region is None:
                raise CustomerRegionNotFoundError(details={"region_id": payload.region_id})
            region_id = region.id

        # Хеш считается всегда, в том числе для существующего адреса:
        # argon2 занимает ~100 мс, и его отсутствие выдало бы ответ по времени.
        password_hash = hash_password(payload.password)

        existing = await self.customers.get_by_email(payload.email)
        if existing is not None:
            await self._resend_verification_for(existing, context)
            return

        customer = Customer(
            email=payload.email,
            password_hash=password_hash,
            contact_name=payload.contact_name,
            company_name=payload.company_name,
            phone=payload.phone,
            region_id=region_id,
        )
        self.customers.add(customer)
        try:
            await self.session.flush()
        except IntegrityError:
            # Параллельная регистрация того же адреса успела первой.
            await self.session.rollback()
            return

        token = await self._issue_action_token(
            customer,
            CustomerTokenPurpose.EMAIL_VERIFICATION,
            timedelta(hours=settings.CUSTOMER_EMAIL_VERIFICATION_TTL_HOURS),
            context,
        )
        self._record(CustomerAuditAction.REGISTERED, customer, context)
        await self.commit()
        await self.mailer.send_email_verification(email=customer.email, token=token)
        logger.info("customer_registered", customer_id=customer.id)

    async def resend_verification(self, email: str, context: RequestContext) -> None:
        customer = await self.customers.get_by_email(email)
        if customer is not None:
            await self._resend_verification_for(customer, context)

    async def _resend_verification_for(self, customer: Customer, context: RequestContext) -> None:
        if not customer.is_active or customer.email_verified_at is not None:
            return
        token = await self._issue_action_token(
            customer,
            CustomerTokenPurpose.EMAIL_VERIFICATION,
            timedelta(hours=settings.CUSTOMER_EMAIL_VERIFICATION_TTL_HOURS),
            context,
        )
        await self.commit()
        await self.mailer.send_email_verification(email=customer.email, token=token)

    async def verify_email(self, raw_token: str, context: RequestContext) -> None:
        stored, customer = await self._consume_action_token(
            raw_token, CustomerTokenPurpose.EMAIL_VERIFICATION
        )
        if customer.email_verified_at is None:
            customer.email_verified_at = _now()
            self._record(CustomerAuditAction.EMAIL_VERIFIED, customer, context)
        stored.used_at = _now()
        await self.action_tokens.invalidate_pending(
            customer.id, CustomerTokenPurpose.EMAIL_VERIFICATION.value
        )
        await self.commit()

    # ---------------------------------------------------------------- вход
    async def authenticate(
        self, email: str, password: str, context: RequestContext
    ) -> CustomerTokens:
        customer = await self.customers.get_by_email(email)
        # Проверка пароля выполняется и для несуществующего адреса —
        # выравнивание времени ответа (см. verify_password).
        password_ok = verify_password(password, customer.password_hash if customer else None)

        if customer is not None and self._is_locked(customer):
            self._record(CustomerAuditAction.LOGIN_BLOCKED, customer, context)
            await self.commit()
            # О блокировке узнаёт только знающий пароль (как в админке).
            if password_ok and customer.is_active:
                raise CustomerAccountLockedError
            raise CustomerInvalidCredentialsError

        if customer is None or not password_ok or not customer.is_active:
            if customer is not None:
                self._register_failed_attempt(customer, context)
            await self.commit()
            raise CustomerInvalidCredentialsError

        if customer.email_verified_at is None:
            # Пароль верный — подсказка безопасна и нужна: без неё клиент
            # не поймёт, почему не может войти.
            raise CustomerEmailNotVerifiedError

        if password_needs_rehash(customer.password_hash):
            customer.password_hash = hash_password(password)

        customer.failed_login_count = 0
        customer.locked_until = None
        customer.last_login_at = _now()
        tokens = await self._create_token_pair(customer, family_id=uuid.uuid4(), context=context)
        self._record(CustomerAuditAction.LOGIN_SUCCESS, customer, context)
        await self.commit()
        return tokens

    def _is_locked(self, customer: Customer) -> bool:
        return customer.locked_until is not None and customer.locked_until > _now()

    def _register_failed_attempt(self, customer: Customer, context: RequestContext) -> None:
        customer.failed_login_count += 1
        if customer.failed_login_count >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
            customer.locked_until = _now() + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
            customer.failed_login_count = 0
        self._record(CustomerAuditAction.LOGIN_FAILED, customer, context)

    async def _create_token_pair(
        self, customer: Customer, *, family_id: uuid.UUID, context: RequestContext
    ) -> CustomerTokens:
        access_token, expires_in = create_access_token(
            subject=customer.uuid,
            role=CUSTOMER_ROLE,
            audience=JWT_CUSTOMER_AUDIENCE,
            extra_claims={"pwv": password_version(customer)},
        )
        refresh_raw = generate_refresh_token()
        expires_at = _now() + timedelta(days=settings.CUSTOMER_REFRESH_TOKEN_TTL_DAYS)
        self.refresh_tokens.add(
            CustomerRefreshToken(
                customer_id=customer.id,
                token_hash=hash_refresh_token(refresh_raw),
                family_id=family_id,
                expires_at=expires_at,
                user_agent=context.user_agent,
                ip_hash=context.ip_hash,
            )
        )
        await self.session.flush()
        return CustomerTokens(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=refresh_raw,
            refresh_expires_at=expires_at,
        )

    # --------------------------------------------------------- обновление
    async def refresh(self, raw_token: str, context: RequestContext) -> CustomerTokens:
        """Ротация с обнаружением переиспользования (как в админке).

        Отозванный токен, предъявленный повторно, означает, что у кого-то
        есть его копия: отзывается вся цепочка, клиент входит заново.
        """
        if not raw_token:
            raise CustomerInvalidRefreshTokenError
        stored = await self.refresh_tokens.get_by_hash(
            hash_refresh_token(raw_token), for_update=True
        )
        if stored is None:
            raise CustomerInvalidRefreshTokenError

        if stored.revoked_at is not None:
            revoked = await self.refresh_tokens.revoke_family(stored.family_id)
            self.audit.record(
                action=CustomerAuditAction.TOKEN_REUSE_DETECTED,
                entity_type=CUSTOMER_ENTITY,
                entity_id=stored.customer_id,
                actor=CUSTOMER_ACTOR,
                changes={"revoked_tokens": revoked},
                ip_hash=context.ip_hash,
                request_id=context.request_id,
            )
            await self.commit()
            logger.warning("customer_refresh_token_reuse", customer_id=stored.customer_id)
            raise CustomerInvalidRefreshTokenError

        if stored.expires_at <= _now():
            raise CustomerInvalidRefreshTokenError

        customer = await self.customers.get(stored.customer_id)
        if customer is None or not customer.is_active or customer.email_verified_at is None:
            raise CustomerInvalidRefreshTokenError

        stored.revoked_at = _now()
        tokens = await self._create_token_pair(
            customer, family_id=stored.family_id, context=context
        )
        self._record(CustomerAuditAction.TOKEN_REFRESHED, customer, context)
        await self.commit()
        return tokens

    async def logout(self, raw_token: str | None, context: RequestContext) -> None:
        """Отзывает цепочку текущей сессии. Выход из недействительной
        сессии — не ошибка."""
        if not raw_token:
            return
        stored = await self.refresh_tokens.get_by_hash(hash_refresh_token(raw_token))
        if stored is None:
            return
        await self.refresh_tokens.revoke_family(stored.family_id)
        self.audit.record(
            action=CustomerAuditAction.LOGOUT,
            entity_type=CUSTOMER_ENTITY,
            entity_id=stored.customer_id,
            actor=CUSTOMER_ACTOR,
            ip_hash=context.ip_hash,
            request_id=context.request_id,
        )
        await self.commit()

    # ------------------------------------------------------ сброс пароля
    async def request_password_reset(self, email: str, context: RequestContext) -> None:
        """Выпускает ссылку сброса, если аккаунт есть и активен.

        Для неизвестного адреса ответ тот же — существование аккаунта
        не раскрывается.
        """
        customer = await self.customers.get_by_email(email)
        if customer is None or not customer.is_active:
            return
        token = await self._issue_action_token(
            customer,
            CustomerTokenPurpose.PASSWORD_RESET,
            timedelta(minutes=settings.CUSTOMER_PASSWORD_RESET_TTL_MINUTES),
            context,
        )
        self._record(CustomerAuditAction.PASSWORD_RESET_REQUESTED, customer, context)
        await self.commit()
        await self.mailer.send_password_reset(email=customer.email, token=token)

    async def confirm_password_reset(
        self, raw_token: str, new_password: str, context: RequestContext
    ) -> None:
        """Меняет пароль по ссылке и завершает все сессии клиента.

        Сброс пароля почти всегда означает подозрение на компрометацию:
        живые refresh-токены отзываются, выданные ранее access-токены
        перестают приниматься (`password_changed_at`). Переход по ссылке
        из письма заодно доказывает владение адресом — неподтверждённый
        аккаунт становится подтверждённым.
        """
        stored, customer = await self._consume_action_token(
            raw_token, CustomerTokenPurpose.PASSWORD_RESET
        )
        now = _now()
        customer.password_hash = hash_password(new_password)
        customer.password_changed_at = now
        customer.failed_login_count = 0
        customer.locked_until = None
        if customer.email_verified_at is None:
            customer.email_verified_at = now
        stored.used_at = now
        await self.action_tokens.invalidate_pending(
            customer.id, CustomerTokenPurpose.PASSWORD_RESET.value
        )
        revoked = await self.refresh_tokens.revoke_all_for_customer(customer.id)
        self.audit.record(
            action=CustomerAuditAction.PASSWORD_RESET,
            entity_type=CUSTOMER_ENTITY,
            entity_id=customer.id,
            actor=CUSTOMER_ACTOR,
            changes={"revoked_sessions": revoked},
            ip_hash=context.ip_hash,
            request_id=context.request_id,
        )
        await self.commit()

    # --------------------------------------------------------- внутреннее
    async def _issue_action_token(
        self,
        customer: Customer,
        purpose: CustomerTokenPurpose,
        lifetime: timedelta,
        context: RequestContext,
    ) -> str:
        await self.action_tokens.invalidate_pending(customer.id, purpose.value)
        raw = generate_action_token()
        self.action_tokens.add(
            CustomerActionToken(
                customer_id=customer.id,
                purpose=purpose.value,
                token_hash=hash_refresh_token(raw),
                expires_at=_now() + lifetime,
                ip_hash=context.ip_hash,
            )
        )
        await self.session.flush()
        return raw

    async def _consume_action_token(
        self, raw_token: str, purpose: CustomerTokenPurpose
    ) -> tuple[CustomerActionToken, Customer]:
        """Проверяет одноразовый токен. Любая проблема — одна ошибка."""
        stored = await self.action_tokens.get_by_hash_for_update(hash_refresh_token(raw_token))
        if (
            stored is None
            or stored.purpose != purpose.value
            or stored.used_at is not None
            or stored.expires_at <= _now()
        ):
            raise CustomerInvalidActionTokenError
        customer = await self.customers.get(stored.customer_id)
        if customer is None or not customer.is_active:
            raise CustomerInvalidActionTokenError
        return stored, customer

    def _record(self, action: str, customer: Customer, context: RequestContext) -> None:
        self.audit.record(
            action=action,
            entity_type=CUSTOMER_ENTITY,
            entity_id=customer.id,
            actor=CUSTOMER_ACTOR,
            ip_hash=context.ip_hash,
            request_id=context.request_id,
        )
