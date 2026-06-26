"""Pytest configuration — shared fixtures for all tests."""

import sys
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# Add server dir to Python path so `app` module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

# Add SDK src dir to Python path so `handoffrail.sdk` module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "src"))

# Add project root so `cli` package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import engine, async_session
from app.main import create_app
from app.middleware.auth import generate_api_key
from app.middleware.rate_limit import rate_limiter_registry
from app.models.db import ApiKey, Base

# Create test app with very high rate limits so tests don't get throttled
_test_app = create_app(tier_limits={"free": 100000, "pro": 100000, "business": 100000})

# Generated test API key (created once per test session)
_test_api_key: str | None = None


async def _ensure_test_api_key() -> str:
    """Create a test API key in the DB and return the plain key string."""
    global _test_api_key
    if _test_api_key is not None:
        # Make sure it still exists in the DB (tables may have been dropped)
        async with async_session() as session:
            result = await session.execute(
                select(ApiKey).where(ApiKey.key_prefix == _test_api_key[:8])
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                return _test_api_key

    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]
    db_key = ApiKey(
        id="test-key-id",
        name="test",
        key_hash=key_hash,
        key_prefix=key_prefix,
        tenant_id="default",
        tier="free",
    )
    async with async_session() as session:
        session.add(db_key)
        await session.commit()
    _test_api_key = plain_key
    return plain_key


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create tables before each test and drop them after. Also reset rate limiter."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Ensure the test API key exists in the fresh DB
    await _ensure_test_api_key()

    # Reset the global rate limiter counters between tests
    rate_limiter_registry.reset()

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