"""RBAC импорта и экспорта каталога.

Используется существующая матрица прав: экспорт, шаблон, предпросмотр
и история — `catalog.read`, подтверждение — `catalog.write`. Матрица
этим этапом не расширялась: MANAGER по-прежнему без `catalog.write`.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.modules.users.enums import UserRole
from app.modules.users.permissions import (
    CATALOG_READ,
    CATALOG_WRITE,
    ROLE_PERMISSIONS,
    has_permission,
)
from tests.import_helpers import (
    EXPORT,
    IMPORTS,
    PREVIEW,
    TEMPLATE,
    build_workbook,
    commit_url,
    preview,
    product_row,
    upload,
)


@pytest.mark.parametrize(
    ("role", "read_status", "commit_status"),
    [
        (UserRole.SUPERADMIN, 200, 200),
        (UserRole.ADMIN, 200, 200),
        (UserRole.CONTENT_MANAGER, 200, 200),
        (UserRole.MANAGER, 200, 403),
        (UserRole.VIEWER, 200, 403),
    ],
)
async def test_import_permissions(
    api: AsyncClient,
    login_as,
    admin,
    catalog,
    role: UserRole,
    read_status: int,
    commit_status: int,
) -> None:
    headers = await login_as(role)
    data = build_workbook({"Products": [product_row(f"RBAC-{role.value}", categories="kanaty")]})

    assert (await api.get(EXPORT, headers=headers)).status_code == read_status
    assert (await api.get(TEMPLATE, headers=headers)).status_code == read_status
    assert (await api.get(IMPORTS, headers=headers)).status_code == read_status

    response = await upload(api, PREVIEW, headers, data)
    assert response.status_code == read_status
    job_uuid = response.json()["job"]["uuid"]
    assert (await api.get(f"{IMPORTS}/{job_uuid}", headers=headers)).status_code == read_status

    committed = await upload(api, commit_url(job_uuid), headers, data)
    assert committed.status_code == commit_status
    if commit_status == 403:
        assert committed.json()["error"]["code"] == "permission_denied"
        # Отказ в правах не портит предпросмотр: редактор может его подтвердить.
        assert (await upload(api, commit_url(job_uuid), admin, data)).status_code == 200


async def test_anonymous_access_is_rejected(api: AsyncClient) -> None:
    data = build_workbook({"Products": [product_row("ANON-1")]})
    assert (await upload(api, PREVIEW, {}, data)).status_code == 401
    assert (
        await upload(api, commit_url("00000000-0000-0000-0000-000000000000"), {}, data)
    ).status_code == 401
    assert (await api.get(IMPORTS)).status_code == 401


async def test_forbidden_commit_is_rejected_before_reading_the_file(
    api: AsyncClient, login_as, admin, catalog
) -> None:
    """Права проверяются до разбора тела: VIEWER получает 403 даже на мусоре."""
    report = await preview(api, admin, build_workbook({"Products": [product_row("V-1")]}))
    viewer = await login_as(UserRole.VIEWER)
    response = await api.post(
        commit_url(report["job"]["uuid"]),
        headers={**viewer, "Content-Type": "multipart/form-data; boundary=x"},
        content=b"not a multipart body",
    )
    assert response.status_code == 403


def test_permission_matrix_is_unchanged() -> None:
    """Этап 5E не выдаёт ролям новых прав."""
    assert not has_permission(UserRole.MANAGER, CATALOG_WRITE)
    assert not has_permission(UserRole.VIEWER, CATALOG_WRITE)
    assert has_permission(UserRole.CONTENT_MANAGER, CATALOG_WRITE)

    assert ROLE_PERMISSIONS[UserRole.MANAGER] == frozenset(
        {"catalog.read", "request.read", "request.write", "request.export"}
    )
    assert ROLE_PERMISSIONS[UserRole.CONTENT_MANAGER] == frozenset(
        {
            "catalog.read",
            "catalog.write",
            "price.write",
            "stock.write",
            "media.upload",
            "content.write",
        }
    )
    assert ROLE_PERMISSIONS[UserRole.VIEWER] == frozenset({CATALOG_READ, "request.read"})
