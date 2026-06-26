"""Tests for SSRF protection on webhook URLs."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from app.database import engine, async_session
from app.main import create_app
from app.middleware.auth import generate_api_key
from app.middleware.rate_limit import rate_limiter_registry
from app.models.db import ApiKey, Base

_test_app = create_app(tier_limits={"free": 100000, "pro": 100000, "business": 100000})
_test_api_key: str | None = None


async def _ensure_test_api_key() -> str:
    global _test_api_key
    if _test_api_key is not None:
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
        id="test-ssrf-key-id",
        name="test-ssrf",
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_test_api_key()
    rate_limiter_registry.reset()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    api_key = await _ensure_test_api_key()
    transport = ASGITransport(app=_test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as ac:
        yield ac


class TestWebhookSSRFProtection:
    """Test that SSRF protection blocks internal/metadata URLs."""

    @pytest.mark.asyncio
    async def test_localhost_blocked(self, client: AsyncClient):
        """Webhook URL pointing to localhost is rejected."""
        resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "http://localhost:9000/webhook",
                "events": ["packet.created"],
                "secret": "my_super_secret_key_16ch",
            },
        )
        assert resp.status_code == 422
        assert "blocked" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_private_ip_blocked(self, client: AsyncClient):
        """Webhook URL pointing to private IP range is rejected."""
        resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "http://192.168.1.1:9000/webhook",
                "events": ["packet.created"],
                "secret": "my_super_secret_key_16ch",
            },
        )
        assert resp.status_code == 422
        assert "blocked" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_cloud_metadata_blocked(self, client: AsyncClient):
        """Webhook URL pointing to cloud metadata endpoint is rejected."""
        resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "http://169.254.169.254/latest/meta-data/",
                "events": ["packet.created"],
                "secret": "my_super_secret_key_16ch",
            },
        )
        assert resp.status_code == 422
        assert "blocked" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_loopback_ip_blocked(self, client: AsyncClient):
        """Webhook URL pointing to 127.0.0.1 is rejected."""
        resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "http://127.0.0.1:8080/webhook",
                "events": ["packet.created"],
                "secret": "my_super_secret_key_16ch",
            },
        )
        assert resp.status_code == 422
        assert "blocked" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_public_url_allowed(self, client: AsyncClient):
        """Webhook URL pointing to a public domain is allowed."""
        resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["packet.created"],
                "secret": "my_super_secret_key_16ch",
            },
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_secret_max_length_enforced(self, client: AsyncClient):
        """Webhook secret longer than 256 chars is rejected."""
        resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["packet.created"],
                "secret": "x" * 300,
            },
        )
        assert resp.status_code == 422

    def test_ssrf_unit_localhost(self):
        """Unit test: is_url_safe blocks localhost."""
        from app.services.ssrf import is_url_safe
        safe, reason = is_url_safe("http://localhost:8080/hook")
        assert not safe

    def test_ssrf_unit_private_ip(self):
        """Unit test: is_url_safe blocks 10.x.x.x."""
        from app.services.ssrf import is_url_safe
        safe, reason = is_url_safe("http://10.0.0.1:8080/hook")
        assert not safe

    def test_ssrf_unit_metadata(self):
        """Unit test: is_url_safe blocks 169.254.x.x."""
        from app.services.ssrf import is_url_safe
        safe, reason = is_url_safe("http://169.254.169.254/meta")
        assert not safe

    def test_ssrf_unit_public(self):
        """Unit test: is_url_safe allows public domains."""
        from app.services.ssrf import is_url_safe
        safe, reason = is_url_safe("https://example.com/hook")
        assert safe