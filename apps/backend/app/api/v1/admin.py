"""Admin API — /api/v1/admin.

JWT + RBAC на каждом эндпоинте, аудит мутаций, без кэширования.
"""

from fastapi import APIRouter

from app.modules.audit.router_admin import router as audit_router
from app.modules.catalog.router_admin import attributes_router, categories_router
from app.modules.catalog.router_admin_products import router as products_router
from app.modules.catalog.router_admin_summary import router as catalog_summary_router
from app.modules.colors.router_admin import colors_router, product_colors_router
from app.modules.content.router_admin import router as content_router
from app.modules.imports.router_admin import router as catalog_excel_router
from app.modules.imports.router_bundle import router as catalog_bundle_router
from app.modules.integration.router_admin import router as integration_status_router
from app.modules.inventory.router_admin import (
    product_stock_router,
    stock_router,
    warehouses_router,
)
from app.modules.media.router_admin import media_router, product_images_router
from app.modules.pricing.router_admin import pricing_router, product_pricing_router
from app.modules.requests.router_admin import router as requests_router
from app.modules.users.router_admin import router as auth_router
from app.modules.users.router_admin import users_router

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(categories_router)
router.include_router(attributes_router)
router.include_router(products_router)
router.include_router(product_pricing_router)
router.include_router(pricing_router)
router.include_router(product_stock_router)
router.include_router(colors_router)
router.include_router(product_colors_router)
router.include_router(warehouses_router)
router.include_router(stock_router)
router.include_router(media_router)
router.include_router(product_images_router)
router.include_router(requests_router)
router.include_router(content_router)
router.include_router(catalog_bundle_router)
router.include_router(catalog_excel_router)
router.include_router(catalog_summary_router)
router.include_router(audit_router)
router.include_router(integration_status_router)
