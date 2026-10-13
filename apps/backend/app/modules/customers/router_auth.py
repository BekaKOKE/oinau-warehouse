"""Аутентификация клиентов B2B-кабинета — /api/v1/public/auth.

Публичная поверхность: регистрация, подтверждение email, вход, обновление
сессии, выход, восстановление пароля. Всё, что требует входа, живёт
в отдельной поверхности /api/v1/customer.

Refresh-токен — только в httpOnly cookie с путём, суженным до этих
эндпоинтов: к остальному API браузер его не отправляет.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status

from app.api.deps import ContextDep, RateLimiterDep, SessionDep, rate_limit
from app.core.config import settings
from app.core.exceptions import RateLimitError
from app.modules.customers.mailer import AccountMailer, get_account_mailer
from app.modules.customers.schemas_auth import (
    AcceptedResponse,
    CustomerLogin,
    CustomerRegister,
    CustomerTokenResponse,
    EmailOnly,
    PasswordResetConfirm,
    TokenOnly,
)
from app.modules.customers.service_auth import CustomerAuthService, CustomerTokens

router = APIRouter(prefix="/auth", tags=["customer-auth"])

CUSTOMER_REFRESH_COOKIE_PATH = f"{settings.API_V1_PREFIX}/public/auth"

MailerDep = Annotated[AccountMailer, Depends(get_account_mailer)]

REGISTER_ACCEPTED = (
    "Если адрес ещё не зарегистрирован, на него отправлено письмо для подтверждения. "
    "Проверьте почту."
)
RESEND_ACCEPTED = "Если аккаунт существует и не подтверждён, письмо отправлено повторно."
RESET_ACCEPTED = "Если аккаунт с таким адресом существует, на него отправлена ссылка для сброса."


def _set_refresh_cookie(response: Response, tokens: CustomerTokens) -> None:
    response.set_cookie(
        key=settings.CUSTOMER_REFRESH_COOKIE_NAME,
        value=tokens.refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path=CUSTOMER_REFRESH_COOKIE_PATH,
        expires=tokens.refresh_expires_at,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.CUSTOMER_REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path=CUSTOMER_REFRESH_COOKIE_PATH,
    )


async def _limit_per_address(limiter: RateLimiterDep, scope: str, email: str) -> None:
    """Ограничение писем на один адрес — поверх ограничения по IP.

    Без него форму можно использовать для рассылки писем на чужой ящик
    с разных адресов. В ключе — хеш адреса, а не сам адрес: в Redis
    не остаются персональные данные.
    """
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    allowed, _ = await limiter.hit(
        f"{scope}:{digest}", settings.RATE_LIMIT_CUSTOMER_EMAIL_PER_ADDRESS
    )
    if not allowed:
        raise RateLimitError


RefreshCookie = Annotated[str | None, Cookie(alias=settings.CUSTOMER_REFRESH_COOKIE_NAME)]


@router.post(
    "/register",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Регистрация клиента",
    dependencies=[Depends(rate_limit("customer_register", "RATE_LIMIT_CUSTOMER_REGISTER"))],
)
async def register(
    payload: CustomerRegister,
    session: SessionDep,
    context: ContextDep,
    mailer: MailerDep,
    limiter: RateLimiterDep,
) -> AcceptedResponse:
    """Ответ одинаков для нового и уже зарегистрированного адреса."""
    await _limit_per_address(limiter, "customer_email_addr", payload.email)
    await CustomerAuthService(session, mailer).register(payload, context)
    return AcceptedResponse(detail=REGISTER_ACCEPTED)


@router.post(
    "/verify-email",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Подтверждение email по ссылке из письма",
    dependencies=[Depends(rate_limit("customer_token", "RATE_LIMIT_CUSTOMER_TOKEN"))],
)
async def verify_email(
    payload: TokenOnly, session: SessionDep, context: ContextDep, mailer: MailerDep
) -> None:
    await CustomerAuthService(session, mailer).verify_email(payload.token, context)


@router.post(
    "/verify-email/resend",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Повторная отправка письма подтверждения",
    dependencies=[Depends(rate_limit("customer_email", "RATE_LIMIT_CUSTOMER_EMAIL"))],
)
async def resend_verification(
    payload: EmailOnly,
    session: SessionDep,
    context: ContextDep,
    mailer: MailerDep,
    limiter: RateLimiterDep,
) -> AcceptedResponse:
    await _limit_per_address(limiter, "customer_email_addr", payload.email)
    await CustomerAuthService(session, mailer).resend_verification(payload.email, context)
    return AcceptedResponse(detail=RESEND_ACCEPTED)


@router.post(
    "/login",
    response_model=CustomerTokenResponse,
    summary="Вход в кабинет",
    dependencies=[Depends(rate_limit("customer_login", "RATE_LIMIT_CUSTOMER_LOGIN"))],
)
async def login(
    payload: CustomerLogin,
    response: Response,
    session: SessionDep,
    context: ContextDep,
    mailer: MailerDep,
) -> CustomerTokenResponse:
    """Access-токен — в теле (хранится в памяти приложения), refresh — в cookie."""
    tokens = await CustomerAuthService(session, mailer).authenticate(
        payload.email, payload.password, context
    )
    _set_refresh_cookie(response, tokens)
    return CustomerTokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post(
    "/refresh",
    response_model=CustomerTokenResponse,
    summary="Обновление сессии",
    dependencies=[Depends(rate_limit("customer_refresh", "RATE_LIMIT_CUSTOMER_LOGIN"))],
)
async def refresh(
    response: Response,
    session: SessionDep,
    context: ContextDep,
    mailer: MailerDep,
    refresh_token: RefreshCookie = None,
) -> CustomerTokenResponse:
    tokens = await CustomerAuthService(session, mailer).refresh(refresh_token or "", context)
    _set_refresh_cookie(response, tokens)
    return CustomerTokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Выход из кабинета")
async def logout(
    response: Response,
    session: SessionDep,
    context: ContextDep,
    mailer: MailerDep,
    refresh_token: RefreshCookie = None,
) -> None:
    await CustomerAuthService(session, mailer).logout(refresh_token, context)
    _clear_refresh_cookie(response)


@router.post(
    "/password-reset",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запрос ссылки для сброса пароля",
    dependencies=[Depends(rate_limit("customer_email", "RATE_LIMIT_CUSTOMER_EMAIL"))],
)
async def request_password_reset(
    payload: EmailOnly,
    session: SessionDep,
    context: ContextDep,
    mailer: MailerDep,
    limiter: RateLimiterDep,
) -> AcceptedResponse:
    await _limit_per_address(limiter, "customer_reset_addr", payload.email)
    await CustomerAuthService(session, mailer).request_password_reset(payload.email, context)
    return AcceptedResponse(detail=RESET_ACCEPTED)


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Новый пароль по ссылке из письма",
    dependencies=[Depends(rate_limit("customer_token", "RATE_LIMIT_CUSTOMER_TOKEN"))],
)
async def confirm_password_reset(
    payload: PasswordResetConfirm,
    response: Response,
    session: SessionDep,
    context: ContextDep,
    mailer: MailerDep,
) -> None:
    await CustomerAuthService(session, mailer).confirm_password_reset(
        payload.token, payload.new_password, context
    )
    # Все сессии отозваны — cookie текущего браузера тоже больше не нужна.
    _clear_refresh_cookie(response)
