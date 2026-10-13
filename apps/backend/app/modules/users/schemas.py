"""Pydantic-схемы домена пользователей."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.config import settings
from app.core.text import clean_plain_text
from app.db.types import LEN_PHONE, LEN_SHORT_NAME
from app.modules.users.enums import UserRole


def validate_password_strength(value: str) -> str:
    """Минимальная осмысленная политика.

    Требования к составу символов (цифра, спецсимвол, регистр) намеренно
    не вводятся: они дают предсказуемые пароли вида Password1! и, по
    современным рекомендациям NIST, снижают реальную стойкость.
    Длина работает лучше.
    """
    if len(value) < settings.PASSWORD_MIN_LENGTH:
        raise ValueError(f"Пароль короче {settings.PASSWORD_MIN_LENGTH} символов")
    if value.strip() != value:
        raise ValueError("Пароль не должен начинаться или заканчиваться пробелом")
    return value


def clean_full_name(value: str) -> str:
    """Имя сотрудника — одна строка без HTML и управляющих символов."""
    cleaned = clean_plain_text(value, max_length=LEN_SHORT_NAME, multiline=False)
    if not cleaned:
        raise ValueError("Имя не может быть пустым")
    return cleaned


def clean_optional_text(value: str | None, *, max_length: int) -> str | None:
    """Пустая строка в необязательном поле означает «значения нет»."""
    if value is None:
        return None
    cleaned = clean_plain_text(value, max_length=max_length, multiline=False)
    return cleaned or None


class LoginRequest(BaseModel):
    email: EmailStr
    # Пароль не ограничиваем сверху по длине: обрезка молча ломает
    # менеджеры паролей. argon2 принимает строку любой длины.
    password: str = Field(min_length=1, max_length=512)


class TokenResponse(BaseModel):
    """Refresh-токена в теле НЕТ — он уходит только в httpOnly cookie."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int


class UserRead(BaseModel):
    """Карточка сотрудника. Ни хеша пароля, ни внутреннего id здесь нет."""

    model_config = ConfigDict(from_attributes=True)

    uuid: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CurrentUserRead(UserRead):
    """Профиль плюс развёрнутый список прав.

    Админка использует его, чтобы не показывать кнопки, которые всё
    равно вернут 403. Это удобство интерфейса, а не защита: решение
    всегда принимает backend.
    """

    permissions: list[str]


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(max_length=512)

    @field_validator("new_password")
    @classmethod
    def _check_strength(cls, value: str) -> str:
        return validate_password_strength(value)


class UserCreate(BaseModel):
    """Заведение сотрудника администратором.

    Пароль принимается, но наружу не возвращается никогда: ответ —
    обычный `UserRead`. Хеширование — argon2id, общий `hash_password`.
    """

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(max_length=512)
    role: UserRole
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("password")
    @classmethod
    def _check_strength(cls, value: str) -> str:
        return validate_password_strength(value)

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return clean_full_name(value)

    @field_validator("phone")
    @classmethod
    def _clean_phone(cls, value: str | None) -> str | None:
        return clean_optional_text(value, max_length=LEN_PHONE)


class UserUpdate(BaseModel):
    """Частичное изменение: незаданные поля не трогаются.

    Email не меняется — он служит логином и ссылкой на сотрудника в
    журнале аудита. Новый адрес = новая учётная запись.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    role: UserRole | None = None
    is_active: bool | None = None
    # Задать новый пароль сотруднику может администратор: все сессии
    # этого сотрудника при этом отзываются.
    password: str | None = Field(default=None, max_length=512)

    @field_validator("password")
    @classmethod
    def _check_strength(cls, value: str | None) -> str | None:
        return None if value is None else validate_password_strength(value)

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        return None if value is None else clean_full_name(value)

    @field_validator("phone")
    @classmethod
    def _clean_phone(cls, value: str | None) -> str | None:
        return clean_optional_text(value, max_length=LEN_PHONE)


class RolePermissionsRead(BaseModel):
    """Права роли — те же константы, что проверяет backend.

    Отдаются, чтобы админка объясняла сотруднику состав роли, не храня
    собственную копию матрицы: копия неизбежно разошлась бы с кодом.
    """

    role: UserRole
    permissions: list[str]
