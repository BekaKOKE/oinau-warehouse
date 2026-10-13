"""Схемы регистрации, входа и восстановления доступа клиента.

`extra="forbid"` везде: лишнее поле (например, `email_verified_at`
или `is_active` при регистрации) — 422, а не молчаливое игнорирование.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.db.types import LEN_EMAIL, LEN_SHORT_NAME
from app.modules.requests.schemas_public import normalize_phone
from app.modules.users.schemas import validate_password_strength

# Токен из ссылки: base64url от 32 байт — 43 символа. Верхняя граница
# с запасом отсекает мусор до обращения к БД.
TokenField = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _check_email_length(value: str) -> str:
    if len(value) > LEN_EMAIL:
        raise ValueError(f"Email длиннее {LEN_EMAIL} символов")
    return value


class CustomerRegister(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(max_length=512)
    contact_name: str = Field(min_length=1, max_length=LEN_SHORT_NAME)
    company_name: str | None = Field(default=None, max_length=LEN_SHORT_NAME)
    phone: str = Field(min_length=1, max_length=64)
    # Регион необязателен: на форме регистрации его нет, менеджер
    # уточняет его при первом контакте. Если значение всё-таки пришло
    # (импорт, API), оно проверяется по справочнику.
    region_id: int | None = Field(default=None, ge=1)

    @field_validator("company_name", mode="before")
    @classmethod
    def _blank_company(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("email")
    @classmethod
    def _email_length(cls, value: str) -> str:
        return _check_email_length(value)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        return validate_password_strength(value)


class CustomerLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=512)


class EmailOnly(BaseModel):
    """Повторная отправка подтверждения и запрос сброса пароля."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class TokenOnly(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = TokenField


class PasswordResetConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = TokenField
    new_password: str = Field(max_length=512)

    @field_validator("new_password")
    @classmethod
    def _password(cls, value: str) -> str:
        return validate_password_strength(value)


class AcceptedResponse(BaseModel):
    """Одинаковый ответ для существующего и несуществующего адреса."""

    detail: str


class CustomerTokenResponse(BaseModel):
    """Refresh-токена в теле нет — он уходит только в httpOnly cookie."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int
