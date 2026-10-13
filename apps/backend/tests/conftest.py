from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.modules.users.enums import UserRole

os.environ.setdefault("ENV", "ci")
# Ограничение частоты выключено по умолчанию: тесты входа делают десятки
# попыток с одного адреса. Тест самого ограничения включает его точечно.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
# Полноразмерный ключ: с коротким PyJWT справедливо ругается на стойкость
os.environ.setdefault("SECRET_KEY", "0" * 64)

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Пароль длиннее минимальной политики (12 символов)
DEFAULT_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Разворачивает схему через Alembic, а не через metadata.create_all.

    Это принципиально: create_all собрал бы схему напрямую из моделей и
    не заметил бы, что миграция сломана или отстала. Тесты должны идти
    по тому же пути, что и продакшен.
    """
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
    )


@pytest.fixture
async def db(migrated_database: None) -> AsyncIterator[AsyncSession]:
    """Сессия в транзакции, которая всегда откатывается.

    Тесты не оставляют следов в базе и не зависят от порядка выполнения.
    """
    from app.core.config import settings

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()
            if transaction.is_active:
                await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def test_engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    """Отдельный движок на каждый тест.

    Глобальный движок приложения переиспользовать нельзя: пул asyncpg
    привязан к событийному циклу, а pytest-asyncio даёт каждому тесту
    свой. Отсюда же берут соединение и HTTP-клиент, и сессия теста —
    иначе они не увидят данные друг друга.
    """
    from app.core.config import settings

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        # Чистятся ВСЕ таблицы, кроме alembic_version. Перечислять их
        # руками нельзя: список уже дважды отставал от схемы, а забытая
        # таблица означает, что тесты начинают видеть данные друг друга.
        async with engine.begin() as connection:
            tables = (
                (
                    await connection.execute(
                        text(
                            "SELECT tablename FROM pg_tables "
                            "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            if tables:
                await connection.execute(
                    text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
                )
        await engine.dispose()


@pytest.fixture
async def committed_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Сессия с реальными коммитами.

    Нужна там, где проверяется поведение сервиса целиком: он сам
    управляет транзакцией, и подменять её откатом означало бы тестировать
    не тот код, который работает в проде.
    """
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest.fixture
def object_storage():
    """Объектное хранилище в памяти вместо R2/MinIO."""
    from tests.media_helpers import InMemoryObjectStorage

    return InMemoryObjectStorage()


@pytest.fixture
def media_queue():
    """Очередь, которая только запоминает задачи обработки."""
    from tests.media_helpers import FakeMediaQueue

    return FakeMediaQueue()


@pytest.fixture
def bundle_queue():
    """Очередь пакетного импорта: запоминает задачи, воркер вызывают тесты."""
    from tests.bundle_helpers import FakeBundleQueue

    return FakeBundleQueue()


@pytest.fixture
def account_mailer():
    """Письма кабинета клиента перехватываются, а не отправляются."""
    from tests.customer_helpers import CapturingMailer

    return CapturingMailer()


@pytest.fixture
def notification_queue():
    """Очередь уведомлений только запоминает, кого разбудили."""
    from tests.integration_helpers import FakeNotificationQueue

    return FakeNotificationQueue()


@pytest.fixture
def providers():
    """Каналы доставки подменены: ни SMTP, ни Telegram не вызываются."""
    from tests.integration_helpers import FakeRegistry

    return FakeRegistry()


@pytest.fixture
async def api(
    test_engine: AsyncEngine,
    object_storage,
    media_queue,
    bundle_queue,
    account_mailer,
    notification_queue,
) -> AsyncIterator[AsyncClient]:
    """HTTP-клиент приложения, подключённый к тестовым движку и Redis.

    Хранилище и очередь медиатеки подменены всегда: ни один тест
    не должен случайно обратиться к настоящему бакету.
    """
    from redis.asyncio import from_url

    from app.core.config import settings
    from app.db.redis import get_redis
    from app.db.session import get_session
    from app.infrastructure.storage.s3 import get_object_storage
    from app.main import create_app
    from app.modules.customers.mailer import get_account_mailer
    from app.modules.imports.bundle_service import get_bundle_queue
    from app.modules.media.queue import get_media_queue
    from app.modules.notifications.queue import get_notification_queue

    app = create_app()
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def _session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    redis = from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_object_storage] = lambda: object_storage
    app.dependency_overrides[get_media_queue] = lambda: media_queue
    app.dependency_overrides[get_bundle_queue] = lambda: bundle_queue
    app.dependency_overrides[get_account_mailer] = lambda: account_mailer
    # Очередь уведомлений подменена всегда: ни один тест не должен
    # постучаться в Redis ради побудки воркера.
    app.dependency_overrides[get_notification_queue] = lambda: notification_queue

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await redis.aclose()


@pytest.fixture
def make_user(committed_session: AsyncSession):
    """Фабрика сотрудников с уже захешированным паролем."""
    from app.core.security import hash_password
    from app.modules.users.enums import UserRole
    from app.modules.users.models import User

    async def _make(
        *,
        email: str | None = None,
        password: str = DEFAULT_PASSWORD,
        role: UserRole = UserRole.ADMIN,
        is_active: bool = True,
        full_name: str = "Тестовый Сотрудник",
    ) -> User:
        user = User(
            email=email or f"user-{uuid.uuid4().hex[:8]}@oinau-pro.kz",
            password_hash=hash_password(password),
            full_name=full_name,
            role=role.value,
            is_active=is_active,
        )
        committed_session.add(user)
        await committed_session.commit()
        await committed_session.refresh(user)
        return user

    return _make


@pytest.fixture
async def catalog(committed_session: AsyncSession):
    """Наполненный каталог: категории, товары, цены, остатки, атрибуты."""
    from tests.catalog_fixtures import build_catalog

    return await build_catalog(committed_session)


Headers = dict[str, str]


@pytest.fixture
def login_as(api: AsyncClient, make_user):
    """Возвращает заголовок Authorization для сотрудника с нужной ролью."""

    async def _login(role: UserRole = UserRole.ADMIN) -> Headers:
        user = await make_user(role=role)
        response = await api.post(
            "/api/v1/admin/auth/login",
            json={"email": user.email, "password": DEFAULT_PASSWORD},
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login


@pytest.fixture
async def admin(login_as) -> Headers:
    return await login_as(UserRole.ADMIN)


async def _customer_with_request(
    session: AsyncSession, catalog, *, verified: bool
) -> tuple[int, str]:
    """Клиент кабинета и его заявка. Возвращает (id заявки, email)."""
    from datetime import UTC, datetime

    from app.core.security import hash_password
    from app.modules.customers.models import Customer
    from app.modules.requests.models import Request, RequestItem

    email = f"client-{uuid.uuid4().hex[:8]}@example.kz"
    customer = Customer(
        email=email,
        password_hash=hash_password(DEFAULT_PASSWORD),
        contact_name="Асель Нуржанова",
        phone="+7 701 000 00 11",
        region_id=catalog.region.id,
        email_verified_at=datetime.now(UTC) if verified else None,
    )
    session.add(customer)
    await session.flush()

    request = Request(
        number="R-2026-009001",
        kind="CART",
        status="NEW",
        source="CATALOG_CART",
        customer_id=customer.id,
        customer_name=customer.contact_name,
        phone=customer.phone,
        email=customer.email,
        region_id=catalog.region.id,
        currency="KZT",
        items=[
            RequestItem(
                sku_snapshot="KAN-16-PP",
                name_snapshot="Канат 16 мм",
                unit_snapshot="m",
                quantity=Decimal("10.000"),
                pricing_type_snapshot="FIXED",
            )
        ],
    )
    session.add(request)
    await session.commit()
    await session.refresh(request)
    return request.id, email


@pytest.fixture
async def verified_customer_request(committed_session: AsyncSession, catalog):
    """Заявка клиента с подтверждённым адресом — письма ему можно слать."""
    return await _customer_with_request(committed_session, catalog, verified=True)


@pytest.fixture
async def unverified_customer_request(committed_session: AsyncSession, catalog) -> int:
    """Заявка клиента, не подтвердившего адрес — письма ему слать нельзя."""
    request_id, _ = await _customer_with_request(committed_session, catalog, verified=False)
    return request_id


@pytest.fixture
def make_customer(committed_session: AsyncSession):
    """Фабрика клиентов кабинета: по умолчанию подтверждённых и активных."""
    from datetime import UTC, datetime

    from app.core.security import hash_password
    from app.modules.customers.models import Customer
    from tests.customer_helpers import CUSTOMER_PASSWORD

    async def _make(
        *,
        email: str | None = None,
        password: str = CUSTOMER_PASSWORD,
        verified: bool = True,
        is_active: bool = True,
        region_id: int | None = None,
    ) -> Customer:
        customer = Customer(
            email=email or f"customer-{uuid.uuid4().hex[:8]}@example.kz",
            password_hash=hash_password(password),
            contact_name="Тестовый Клиент",
            company_name="ТОО Тест",
            phone="+77015554433",
            region_id=region_id,
            is_active=is_active,
            email_verified_at=datetime.now(UTC) if verified else None,
        )
        committed_session.add(customer)
        await committed_session.commit()
        await committed_session.refresh(customer)
        return customer

    return _make


@pytest.fixture
def customer_headers(api: AsyncClient, make_customer):
    """Создаёт подтверждённого клиента и возвращает (клиент, заголовок Authorization)."""
    from tests.customer_helpers import bearer, login_customer

    async def _login(**kwargs):
        customer = await make_customer(**kwargs)
        body = await login_customer(api, customer.email)
        return customer, bearer(body["access_token"])

    return _login
