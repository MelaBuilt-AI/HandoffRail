"""Pytest configuration — shared fixtures for all tests."""

import os
import sys
from pathlib import Path

# Disable daily handoff limit enforcement during tests
os.environ["HR_DISABLE_DAILY_LIMIT"] = "1"

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# Add server dir to Python path so `app` module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

# Add SDK src dir to Python path so `handoffrail.sdk` module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "src"))

# Add project root so `cli` package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import _init_fts, async_session, engine
from app.main import create_app
from app.middleware.auth import generate_api_key
from app.middleware.rate_limit import daily_handoff_counter, rate_limiter_registry, sliding_window_counter
from app.models.db import ApiKey, Base, Tenant

# Create test app with very high rate limits so tests don't get throttled
_test_app = create_app(
    tier_limits={"free": 100000, "pro": 100000, "business": 100000},
    rate_limit_per_minute=100000,
    disable_rbac=True,
)

# Generated test API keys (created once per test session)
_test_api_key: str | None = None
_admin_api_key: str | None = None
_tenant2_api_key: str | None = None


async def _seed_default_tenant() -> None:
    """Ensure the default tenant exists."""
    async with async_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == "default")
        )
        if result.scalar_one_or_none() is None:
            from datetime import UTC, datetime
            tenant = Tenant(
                id="default",
                name="Default Tenant",
                tier="free",
                handoffs_per_day=10000,
                max_api_keys=25,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(tenant)
            await session.commit()


async def _ensure_test_api_key() -> str:
    """Create a test API key in the DB and return the plain key string."""
    global _test_api_key
    if _test_api_key is not None:
        async with async_session() as session:
            result = await session.execute(
                select(ApiKey).where(ApiKey.key_prefix == _test_api_key[:8])
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                return _test_api_key

    await _seed_default_tenant()

    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]
    db_key = ApiKey(
        id="test-key-id",
        name="test",
        key_hash=key_hash,
        key_prefix=key_prefix,
        tenant_id="default",
        tier="business",
    )
    async with async_session() as session:
        session.add(db_key)
        await session.commit()
    _test_api_key = plain_key
    return plain_key


async def _ensure_admin_api_key() -> str:
    """Create an admin API key in the DB and return the plain key string."""
    global _admin_api_key
    if _admin_api_key is not None:
        async with async_session() as session:
            result = await session.execute(
                select(ApiKey).where(ApiKey.key_prefix == _admin_api_key[:8])
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                return _admin_api_key

    await _seed_default_tenant()

    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]
    db_key = ApiKey(
        id="admin-key-id",
        name="admin",
        key_hash=key_hash,
        key_prefix=key_prefix,
        tenant_id="default",
        tier="business",
        admin=True,
    )
    async with async_session() as session:
        session.add(db_key)
        await session.commit()
    _admin_api_key = plain_key
    return plain_key


async def _ensure_tenant2_api_key() -> str:
    """Create a second tenant with an API key and return the plain key string."""
    global _tenant2_api_key
    if _tenant2_api_key is not None:
        async with async_session() as session:
            result = await session.execute(
                select(ApiKey).where(ApiKey.key_prefix == _tenant2_api_key[:8])
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                return _tenant2_api_key

    from datetime import UTC, datetime

    # Create tenant2 if it doesn't exist
    async with async_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == "tenant2")
        )
        if result.scalar_one_or_none() is None:
            tenant = Tenant(
                id="tenant2",
                name="Test Tenant 2",
                tier="free",
                handoffs_per_day=10000,
                max_api_keys=10,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(tenant)
            await session.commit()

    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]
    db_key = ApiKey(
        id="tenant2-key-id",
        name="tenant2-test",
        key_hash=key_hash,
        key_prefix=key_prefix,
        tenant_id="tenant2",
        tier="free",
    )
    async with async_session() as session:
        session.add(db_key)
        await session.commit()
    _tenant2_api_key = plain_key
    return plain_key


@pytest_asyncio.fixture(autouse=True)
async def setup_db(request):
    """Create tables before each test and drop them after. Also reset rate limiter.

    CLI tests (test_cli.py) are mock-based and don't need a database.
    Skip DB setup for those tests to avoid test isolation issues.
    """
    # Skip DB setup for mock-based CLI tests
    if "test_cli" in request.node.module.__name__:
        yield
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _init_fts(conn)

    # Ensure the test API key exists in the fresh DB
    await _ensure_test_api_key()

    # Reset the global rate limiter counters and daily handoff counter between tests
    rate_limiter_registry.reset()
    sliding_window_counter.reset()
    daily_handoff_counter.reset()

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """Async HTTP client wired to the test FastAPI app with generous rate limits.

    Automatically includes the test API key in the X-API-Key header.
    """
    api_key = await _ensure_test_api_key()
    transport = ASGITransport(app=_test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_client():
    """Async HTTP client with an admin API key."""
    api_key = await _ensure_admin_api_key()
    transport = ASGITransport(app=_test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def tenant2_client():
    """Async HTTP client with a second tenant's API key."""
    api_key = await _ensure_tenant2_api_key()
    transport = ASGITransport(app=_test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as ac:
        yield ac
