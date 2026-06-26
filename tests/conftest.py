"""Pytest configuration — shared fixtures for all tests."""

import sys
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Add server dir to Python path so `app` module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

# Add SDK src dir to Python path so `handoffrail.sdk` module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "src"))

# Add project root so `cli` package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import engine
from app.main import create_app
from app.middleware.rate_limit import rate_limiter_registry
from app.models.db import Base

# Create test app with very high rate limits so tests don't get throttled
_test_app = create_app(tier_limits={"free": 100000, "pro": 100000, "business": 100000})


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create tables before each test and drop them after. Also reset rate limiter."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Reset the global rate limiter counters between tests
    rate_limiter_registry.reset()

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """Async HTTP client wired to the test FastAPI app with generous rate limits."""
    transport = ASGITransport(app=_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
