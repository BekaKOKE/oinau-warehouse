"""Публичный API — /api/v1/public.

Без авторизации, read-only кроме создания заявок и входа в кабинет клиента
(регистрация, подтверждение email, вход, восстановление пароля).
"""

from fastapi import APIRouter

from app.modules.catalog.router_public import router as catalog_router
from app.modules.content.router_public import router as content_router
from app.modules.customers.router_auth import router as customer_auth_router
from app.modules.geo.router_public import router as geo_router
from app.modules.requests.router_public import router as requests_router

router = APIRouter(prefix="/public", tags=["public"])
router.include_router(catalog_router)
router.include_router(requests_router)
router.include_router(content_router)
router.include_router(geo_router)
router.include_router(customer_auth_router)
