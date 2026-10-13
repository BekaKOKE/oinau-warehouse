"""Создание первого администратора.

Нужен, чтобы вообще войти в систему: регистрации в админке нет
и не будет — учётные записи заводит существующий администратор.

Запуск:
    docker compose exec backend python -m app.scripts.create_superuser
    make superuser
"""

from __future__ import annotations

import asyncio
import getpass
import os
import sys

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionFactory, dispose_engine
from app.modules.users.enums import UserRole
from app.modules.users.models import User
from app.modules.users.repository import UserRepository


async def create_superuser(email: str, full_name: str, password: str, role: str) -> int:
    # Движок закрывается в том же цикле событий, в котором открыт:
    # иначе asyncpg на выходе ругается на чужой event loop.
    try:
        return await _create(email, full_name, password, role)
    finally:
        await dispose_engine()


async def _create(email: str, full_name: str, password: str, role: str) -> int:
    async with SessionFactory() as session:
        repository = UserRepository(session)
        if await repository.get_by_email(email) is not None:
            print(f"Пользователь {email} уже существует", file=sys.stderr)
            return 1

        repository.add(
            User(
                email=email,
                full_name=full_name,
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        await session.commit()
    print(f"Создан пользователь {email} с ролью {role}")
    return 0


def main() -> int:
    # Значения можно передать через окружение — так удобнее для
    # автоматического развёртывания, где интерактивный ввод недоступен.
    email = os.environ.get("SUPERUSER_EMAIL") or input("Email: ").strip()
    full_name = os.environ.get("SUPERUSER_NAME") or input("Имя: ").strip()
    role = os.environ.get("SUPERUSER_ROLE") or UserRole.SUPERADMIN.value

    password = os.environ.get("SUPERUSER_PASSWORD")
    if not password:
        password = getpass.getpass("Пароль: ")
        if password != getpass.getpass("Повторите пароль: "):
            print("Пароли не совпадают", file=sys.stderr)
            return 1

    if len(password) < settings.PASSWORD_MIN_LENGTH:
        print(f"Пароль короче {settings.PASSWORD_MIN_LENGTH} символов", file=sys.stderr)
        return 1
    if role not in {member.value for member in UserRole}:
        print(f"Неизвестная роль: {role}", file=sys.stderr)
        return 1

    return asyncio.run(create_superuser(email, full_name, password, role))


if __name__ == "__main__":
    raise SystemExit(main())
