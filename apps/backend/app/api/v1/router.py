"""Сборка API v1 из изолированных поверхностей: public, customer, admin, integration."""

from fastapi import APIRouter

from app.api.v1 import admin, customer, integration, public

api_router = APIRouter()
api_router.include_router(public.router)
api_router.include_router(customer.router)
api_router.include_router(admin.router)
api_router.include_router(integration.router)
