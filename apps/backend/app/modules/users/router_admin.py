"""Аутентификация и профиль (/api/v1/admin/auth) и сотрудники (/api/v1/admin/users)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Query, Response, status

from app.api.deps import (
    ContextDep,
    CurrentUserDep,
    SessionDep,
    get_permissions,
    rate_limit,
    require_permissions,
)
from app.core.config import settings
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PageParams
from app.modules.users.enums import UserRole
from app.modules.users.models import User
from app.modules.users.permissions import USER_MANAGE
from app.modules.users.repository import MAX_SEARCH_LENGTH, UserFilters
from app.modules.users.schemas import (
    ChangePasswordRequest,
    CurrentUserRead,
    LoginRequest,
    RolePermissionsRead,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.modules.users.service import AuthService, IssuedTokens
from app.modules.users.service_admin import AdminUserService

router = APIRouter(prefix="/auth", tags=["auth"])

# Путь cookie сужен до эндпоинтов аутентификации: браузер не станет
# отправлять refresh-токен вместе с обычными запросами к API, значит
# он не попадёт в логи прокси и не утечёт через постороннюю уязвимость.
REFRESH_COOKIE_PATH = f"{settings.API_V1_PREFIX}/admin/auth"


def _set_refresh_cookie(response: Response, tokens: IssuedTokens) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=tokens.refresh_token,
        httponly=True,  # JS не имеет доступа: XSS не угонит долгий доступ
        secure=settings.cookie_secure,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path=REFRESH_COOKIE_PATH,
        expires=tokens.refresh_expires_at,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path=REFRESH_COOKIE_PATH,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Вход в админку",
    dependencies=[Depends(rate_limit("login", "RATE_LIMIT_LOGIN"))],
)
async def login(
    payload: LoginRequest,
    response: Response,
    session: SessionDep,
    context: ContextDep,
) -> TokenResponse:
    """Возвращает access-токен в теле, refresh — в httpOnly cookie.

    Access-токен намеренно не кладётся в cookie: он должен храниться
    в памяти приложения и уходить в заголовке Authorization. Такое
    разделение отключает CSRF для всех прикладных эндпоинтов.
    """
    service = AuthService(session)
    _, tokens = await service.authenticate(payload.email, payload.password, context)
    _set_refresh_cookie(response, tokens)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/refresh", response_model=TokenResponse, summary="Обновление access-токена")
async def refresh_tokens(
    response: Response,
    session: SessionDep,
    context: ContextDep,
    refresh_token: Annotated[str | None, Cookie(alias=settings.REFRESH_COOKIE_NAME)] = None,
) -> TokenResponse:
    service = AuthService(session)
    _, tokens = await service.refresh(refresh_token or "", context)
    _set_refresh_cookie(response, tokens)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Выход")
async def logout(
    response: Response,
    session: SessionDep,
    context: ContextDep,
    refresh_token: Annotated[str | None, Cookie(alias=settings.REFRESH_COOKIE_NAME)] = None,
) -> None:
    await AuthService(session).logout(refresh_token, context)
    _clear_refresh_cookie(response)


@router.get("/me", response_model=CurrentUserRead, summary="Текущий пользователь")
async def read_me(user: CurrentUserDep) -> CurrentUserRead:
    return CurrentUserRead(
        **UserRead.model_validate(user).model_dump(),
        permissions=sorted(get_permissions(user)),
    )


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Смена собственного пароля",
)
async def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    user: CurrentUserDep,
    session: SessionDep,
    context: ContextDep,
) -> None:
    await AuthService(session).change_password(
        user, payload.current_password, payload.new_password, context
    )
    # Все сессии отозваны, включая текущую — cookie тоже убираем.
    _clear_refresh_cookie(response)


# ---------------------------------------------------------------------------
# Сотрудники: список, карточка, заведение и изменение.
#
# Всё закрыто существующим правом `user.manage` (ADMIN, SUPERADMIN).
# Остальные правила — в сервисе: они касаются безопасности, а не HTTP.
# ---------------------------------------------------------------------------
users_router = APIRouter(prefix="/users", tags=["admin:users"])

UserManager = Annotated[User, Depends(require_permissions(USER_MANAGE))]


@users_router.get("", response_model=Page[UserRead], summary="Список сотрудников")
async def list_users(
    session: SessionDep,
    _: UserManager,
    search: Annotated[
        str | None, Query(max_length=MAX_SEARCH_LENGTH, description="Имя или email")
    ] = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[UserRead]:
    """Действующие сотрудники: отключённые в конце списка, дальше по имени."""
    return await AdminUserService(session).list_users(
        filters=UserFilters(search=search or None, role=role, is_active=is_active),
        params=PageParams(page=page, page_size=page_size),
    )


@users_router.get("/roles", response_model=list[RolePermissionsRead], summary="Роли и их права")
async def list_roles(_: UserManager) -> list[RolePermissionsRead]:
    """Матрица RBAC в том виде, в каком её проверяет backend."""
    return AdminUserService.roles()


@users_router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Завести сотрудника",
)
async def create_user(
    payload: UserCreate,
    session: SessionDep,
    actor: UserManager,
    context: ContextDep,
) -> UserRead:
    """Пароль задаётся администратором и в ответе не возвращается."""
    return await AdminUserService(session).create_user(payload, actor, context)


@users_router.get("/{user_uuid}", response_model=UserRead, summary="Карточка сотрудника")
async def get_user(user_uuid: UUID, session: SessionDep, _: UserManager) -> UserRead:
    return await AdminUserService(session).get_user(user_uuid)


@users_router.patch("/{user_uuid}", response_model=UserRead, summary="Изменить сотрудника")
async def update_user(
    user_uuid: UUID,
    payload: UserUpdate,
    session: SessionDep,
    actor: UserManager,
    context: ContextDep,
) -> UserRead:
    """Роль, имя, телефон, доступ и пароль. Email неизменяем.

    Отключение и смена пароля отзывают все сессии сотрудника.
    """
    return await AdminUserService(session).update_user(user_uuid, payload, actor, context)
