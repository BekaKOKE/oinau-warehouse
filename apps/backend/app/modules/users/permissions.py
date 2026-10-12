"""Права доступа для RBAC.

Права описаны константами в коде, а не таблицами в БД.

Отдельные таблицы roles/permissions дают гибкость, которая на проекте
с пятью ролями и одной компанией никогда не понадобится, но которую
придётся поддерживать: миграции при добавлении права, UI редактирования
ролей, риск конфигурации, в которой не остаётся ни одного суперадмина.

В коде проверяется право, а не роль: require("product.update"), а не
if user.role == "ADMIN". Это позволяет менять состав прав роли, не трогая
эндпоинты. Применение прав — этап 4.
"""

from __future__ import annotations

from app.modules.users.enums import UserRole

# ---------------------------------------------------------------- каталог
CATALOG_READ = "catalog.read"
CATALOG_WRITE = "catalog.write"
PRICE_WRITE = "price.write"
STOCK_WRITE = "stock.write"
MEDIA_UPLOAD = "media.upload"

# ---------------------------------------------------------------- заявки
REQUEST_READ = "request.read"
REQUEST_WRITE = "request.write"
REQUEST_EXPORT = "request.export"

# ---------------------------------------------------------------- контент
CONTENT_WRITE = "content.write"

# ------------------------------------------------------------ администрирование
USER_MANAGE = "user.manage"
SETTINGS_WRITE = "settings.write"
API_KEY_MANAGE = "api_key.manage"
AUDIT_READ = "audit.read"

_CONTENT_MANAGER: frozenset[str] = frozenset(
    {CATALOG_READ, CATALOG_WRITE, PRICE_WRITE, STOCK_WRITE, MEDIA_UPLOAD, CONTENT_WRITE}
)

_MANAGER: frozenset[str] = frozenset({CATALOG_READ, REQUEST_READ, REQUEST_WRITE, REQUEST_EXPORT})

_ADMIN: frozenset[str] = (
    _CONTENT_MANAGER | _MANAGER | frozenset({USER_MANAGE, SETTINGS_WRITE, AUDIT_READ})
)

_SUPERADMIN: frozenset[str] = _ADMIN | frozenset({API_KEY_MANAGE})

ROLE_PERMISSIONS: dict[UserRole, frozenset[str]] = {
    UserRole.SUPERADMIN: _SUPERADMIN,
    UserRole.ADMIN: _ADMIN,
    UserRole.MANAGER: _MANAGER,
    UserRole.CONTENT_MANAGER: _CONTENT_MANAGER,
    UserRole.VIEWER: frozenset({CATALOG_READ, REQUEST_READ}),
    # Роль уже есть, прав пока нет: права упаковки выдаются отдельной
    # задачей. Пустой набор записан явно, чтобы матрица перечисляла
    # все роли.
    UserRole.WAREHOUSE: frozenset(),
}


def has_permission(role: UserRole, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
