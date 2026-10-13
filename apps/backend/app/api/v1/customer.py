"""Кабинет клиента — /api/v1/customer.

Отдельная поверхность, как admin и integration: токен клиента с
аудиторией кабинета, данные только текущего клиента. Регистрация
и вход — в публичной поверхности (/api/v1/public/auth).
"""

from app.modules.customers.router_customer import router

__all__ = ["router"]
