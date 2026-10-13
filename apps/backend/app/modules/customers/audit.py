"""События журнала аудита для клиентского кабинета.

Журнал общий (`audit_log`), но `user_id` там ссылается на сотрудников.
Действия клиента записываются с `actor="customer"` и `entity_type="customer"`:
по id сущности видно, чей это аккаунт. Email, телефон и пароли в журнал
не попадают.
"""

from __future__ import annotations

CUSTOMER_ACTOR = "customer"
CUSTOMER_ENTITY = "customer"


class CustomerAuditAction:
    REGISTERED = "customer.registered"
    EMAIL_VERIFIED = "customer.email_verified"
    LOGIN_SUCCESS = "customer.login_success"
    LOGIN_FAILED = "customer.login_failed"
    LOGIN_BLOCKED = "customer.login_blocked"
    LOGOUT = "customer.logout"
    TOKEN_REFRESHED = "customer.token_refreshed"  # noqa: S105
    TOKEN_REUSE_DETECTED = "customer.token_reuse_detected"  # noqa: S105
    PASSWORD_RESET_REQUESTED = "customer.password_reset_requested"  # noqa: S105
    PASSWORD_RESET = "customer.password_reset"  # noqa: S105
    PROFILE_UPDATED = "customer.profile_updated"
