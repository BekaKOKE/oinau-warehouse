"""Выдача ключа интеграции внешней системе (1С).

Операция уровня развёртывания, а не повседневной работы: ключ даёт
право писать в каталог и остатки, поэтому выдаётся из консоли, а не
кнопкой в админке. В интерфейсе видно только число действующих ключей.

Ключ показывается ОДИН РАЗ — в базе остаётся лишь SHA-256. Забытый ключ
не восстанавливается, а перевыпускается.

Запуск:
    docker compose exec backend python -m app.scripts.create_api_key
    API_KEY_NAME="1С обмен" API_KEY_SCOPES=inventory:write \\
        python -m app.scripts.create_api_key
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta

from app.db.session import SessionFactory, dispose_engine
from app.modules.integration.models import ApiKey
from app.modules.integration.security import (
    IntegrationScope,
    generate_api_key,
    hash_api_key,
    key_prefix,
)


async def create_api_key(name: str, scopes: list[str], days: int | None) -> int:
    try:
        return await _create(name, scopes, days)
    finally:
        await dispose_engine()


async def _create(name: str, scopes: list[str], days: int | None) -> int:
    key = generate_api_key()
    expires_at = datetime.now(UTC) + timedelta(days=days) if days else None

    async with SessionFactory() as session:
        session.add(
            ApiKey(
                name=name,
                key_hash=hash_api_key(key),
                key_prefix=key_prefix(key),
                scopes=sorted(scopes),
                is_active=True,
                expires_at=expires_at,
            )
        )
        await session.commit()

    print(f"Ключ «{name}» создан.")
    print(f"  права:      {', '.join(sorted(scopes))}")
    print(f"  действует:  {'бессрочно' if days is None else f'до {expires_at:%d.%m.%Y}'}")
    print(f"  опознание:  {key_prefix(key)}…")
    print()
    print("Ключ (сохраните сейчас, второй раз он не покажется):")
    print(f"  {key}")
    print()
    print("Передавать в заголовке:  X-API-Key: <ключ>")
    print("Не забудьте ONE_C_INTEGRATION_ENABLED=true и INTEGRATION_IP_ALLOWLIST.")
    return 0


def main() -> int:
    name = os.environ.get("API_KEY_NAME") or input("Название (кому выдан): ").strip()
    if not name:
        print("Название обязательно: по нему ключ опознают в журнале", file=sys.stderr)
        return 1

    raw_scopes = os.environ.get("API_KEY_SCOPES")
    if raw_scopes is None:
        print(f"Доступные права: {', '.join(sorted(IntegrationScope.ALL))}")
        raw_scopes = input("Права через запятую (пусто = все): ").strip()
    scopes = [item.strip() for item in raw_scopes.split(",") if item.strip()] or sorted(
        IntegrationScope.ALL
    )

    unknown = sorted(set(scopes) - IntegrationScope.ALL)
    if unknown:
        print(f"Неизвестные права: {', '.join(unknown)}", file=sys.stderr)
        return 1

    raw_days = os.environ.get("API_KEY_DAYS", "").strip()
    days = int(raw_days) if raw_days.isdigit() and int(raw_days) > 0 else None

    return asyncio.run(create_api_key(name, scopes, days))


if __name__ == "__main__":
    raise SystemExit(main())
