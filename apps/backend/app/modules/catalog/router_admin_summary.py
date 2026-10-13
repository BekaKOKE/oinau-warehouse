"""Сводка каталога — /api/v1/admin/catalog/summary.

Право — существующее `catalog.read`: те же данные уже доступны этой
роли через списки товаров и остатков, сводка лишь считает их в базе.
Точных количеств на складе здесь нет, только число товаров.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import SessionDep, require_permissions
from app.modules.catalog.schemas_admin_summary import CatalogSummaryRead
from app.modules.catalog.service_admin_summary import AdminCatalogSummaryService
from app.modules.users.models import User
from app.modules.users.permissions import CATALOG_READ

CatalogReader = Annotated[User, Depends(require_permissions(CATALOG_READ))]

router = APIRouter(prefix="/catalog", tags=["admin:catalog"])


@router.get("/summary", response_model=CatalogSummaryRead, summary="Сводка каталога")
async def get_catalog_summary(session: SessionDep, _: CatalogReader) -> CatalogSummaryRead:
    """Счётчики для главного экрана: товары, незаполненные карточки,
    наличие, категории. Считается одним запросом к базе."""
    return await AdminCatalogSummaryService(session).get_summary()
