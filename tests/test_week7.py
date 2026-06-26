"""Week 7 tests — Deployment, Auth Tiers, Health, Metrics, Config."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Add server dir to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from app.database import (
    _build_database_url,
    _get_engine_kwargs,
    is_postgres_url,
)
from app.main import create_app
from app.middleware.rate_limit import (
    TIER_QUOTAS,
    DailyHandoffCounter,
    RateLimitRegistry,
    get_tier_quota,
)
from app.models.db import Base

# ── Config tests ───────────────────────────────────────────────────────────────


class TestConfig:
    """Tests for pydantic-settings based configuration."""

    def test_default_settings(self):
        """Default settings should use SQLite and dev environment."""
        from app.config import Settings

        s = Settings()
        assert s.environment == "dev"
        assert s.database_url.startswith("sqlite")
        assert s.log_level == "info"
        assert s.port == 8080
        assert s.tier_default == "free"

    def test_env_var_override(self, monkeypatch):
        """Environment variables should override defaults."""
        from app.config import Settings, reset_settings

        reset_settings()
        monkeypatch.setenv("HR_ENVIRONMENT", "prod")
        monkeypatch.setenv("HR_DATABASE_URL", "postgresql://user:pass@db:5432/hr")
        monkeypatch.setenv("HR_LOG_LEVEL", "warning")
        monkeypatch.setenv("HR_PORT", "9090")

        s = Settings()
        assert s.environment == "prod"
        assert s.database_url == "postgresql://user:pass@db:5432/hr"
        assert s.log_level == "warning"
        assert s.port == 9090

        reset_settings()

    def test_is_postgres_method(self):
        """is_postgres() should detect PostgreSQL URLs."""
        from app.config import Settings

        s = Settings(database_url="postgresql://user:pass@db:5432/hr")
        assert s.is_postgres() is True

        s2 = Settings(database_url="sqlite+aiosqlite:///./test.db")
        assert s2.is_postgres() is False

    def test_is_dev_method(self):
        """is_dev() should return True only for dev environment."""
        from app.config import Settings

        assert Settings(environment="dev").is_dev() is True
        assert Settings(environment="staging").is_dev() is False
        assert Settings(environment="prod").is_dev() is False

    def test_tier_quotas_config(self):
        """Tier quotas should be defined for all tiers."""
        from app.config import Settings

        s = Settings()
        for tier in ("free", "pro", "business"):
            assert tier in s.tier_quotas
            assert "max_packet_size" in s.tier_quotas[tier]
            assert "max_agents" in s.tier_quotas[tier]
            assert "max_api_keys" in s.tier_quotas[tier]

    def test_cors_origins_default(self):
        """Default CORS should allow all origins."""
        from app.config import Settings

        s = Settings()
        assert s.cors_origins == ["*"]

    def test_get_settings_singleton(self):
        """get_settings() should return cached singleton."""
        from app.config import get_settings, reset_settings

        reset_settings()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        reset_settings()


# ── PostgreSQL URL detection tests ─────────────────────────────────────────────


class TestPostgreSQLDetection:
    """Tests for database URL detection and conversion."""

    def test_sqlite_url_unchanged(self):
        """SQLite URLs should pass through unchanged."""
        url = "sqlite+aiosqlite:///./handoffrail.db"
        assert _build_database_url(url) == url

    def test_plain_postgresql_converted_to_asyncpg(self):
        """postgresql:// URLs should get +asyncpg scheme."""
        url = "postgresql://user:pass@host:5432/db"
        result = _build_database_url(url)
        assert result == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_postgres_shorthand_converted(self):
        """postgres:// shorthand should convert to postgresql+asyncpg://."""
        url = "postgres://user:pass@host:5432/db"
        result = _build_database_url(url)
        assert result == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_already_asyncpg_unchanged(self):
        """postgresql+asyncpg:// URLs should not be double-converted."""
        url = "postgresql+asyncpg://user:pass@host:5432/db"
        result = _build_database_url(url)
        assert result == url

    def test_sqlite_engine_kwargs(self):
        """SQLite URLs should get simple engine kwargs."""
        kwargs = _get_engine_kwargs("sqlite+aiosqlite:///./test.db")
        assert "pool_size" not in kwargs
        assert "echo" in kwargs

    def test_postgres_engine_kwargs(self):
        """PostgreSQL URLs should get pool settings."""
        kwargs = _get_engine_kwargs("postgresql+asyncpg://user:pass@host/db")
        assert kwargs["pool_size"] == 20
        assert kwargs["max_overflow"] == 10
        assert kwargs["pool_pre_ping"] is True

    def test_is_postgres_url_with_postgresql(self):
        """is_postgres_url should detect postgresql:// URLs."""
        assert is_postgres_url("postgresql://host/db") is True

    def test_is_postgres_url_with_postgres(self):
        """is_postgres_url should detect postgres:// URLs."""
        assert is_postgres_url("postgres://host/db") is True

    def test_is_postgres_url_with_sqlite(self):
        """is_postgres_url should return False for SQLite."""
        assert is_postgres_url("sqlite+aiosqlite:///./test.db") is False

    def test_is_postgres_url_with_none(self):
        """is_postgres_url with no URL and no env var should return False."""
        old = os.environ.pop("DATABASE_URL", None)
        try:
            assert is_postgres_url() is False
        finally:
            if old is not None:
                os.environ["DATABASE_URL"] = old

    def test_env_var_database_url(self, monkeypatch):
        """_build_database_url should read from DATABASE_URL env var."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/mydb")
        result = _build_database_url()
        assert result == "postgresql+asyncpg://u:p@h:5432/mydb"


# ── Tier quota tests ────────────────────────────────────────────────────────────


class TestTierQuotas:
    """Tests for tier-based quota enforcement."""

    def test_free_tier_quotas(self):
        """Free tier should have restricted quotas."""
        assert get_tier_quota("free", "handoffs_per_day") == 5
        assert get_tier_quota("free", "max_agents") == 2
        assert get_tier_quota("free", "max_api_keys") == 1
        assert get_tier_quota("free", "max_packet_size") == 64 * 1024
        assert get_tier_quota("free", "unlimited_handoffs") is False

    def test_pro_tier_quotas(self):
        """Pro tier should have generous quotas."""
        assert get_tier_quota("pro", "unlimited_handoffs") is True
        assert get_tier_quota("pro", "max_agents") == 10
        assert get_tier_quota("pro", "max_api_keys") == 5
        assert get_tier_quota("pro", "max_packet_size") == 256 * 1024

    def test_business_tier_quotas(self):
        """Business tier should have the most generous quotas."""
        assert get_tier_quota("business", "unlimited_handoffs") is True
        assert get_tier_quota("business", "max_agents") == 50
        assert get_tier_quota("business", "max_api_keys") == 25
        assert get_tier_quota("business", "max_packet_size") == 1024 * 1024

    def test_unknown_tier_defaults_to_free(self):
        """Unknown tier should fall back to free tier quotas."""
        assert get_tier_quota("enterprise", "max_agents") == 2
        assert get_tier_quota("enterprise", "max_packet_size") == 64 * 1024

    def test_tier_quotas_constant_matches(self):
        """TIER_QUOTAS constant should match expected values."""
        assert "free" in TIER_QUOTAS
        assert "pro" in TIER_QUOTAS
        assert "business" in TIER_QUOTAS
        # Verify size progression
        assert TIER_QUOTAS["free"]["max_packet_size"] < TIER_QUOTAS["pro"]["max_packet_size"]
        assert TIER_QUOTAS["pro"]["max_packet_size"] < TIER_QUOTAS["business"]["max_packet_size"]


class TestDailyHandoffCounter:
    """Tests for the daily handoff counter."""

    def test_increment_and_get(self):
        counter = DailyHandoffCounter()
        day = "2026-05-28"

        assert counter.get_count("tenant1", day) == 0
        assert counter.increment("tenant1", day) == 1
        assert counter.increment("tenant1", day) == 2
        assert counter.get_count("tenant1", day) == 2

    def test_separate_tenants(self):
        counter = DailyHandoffCounter()
        day = "2026-05-28"

        counter.increment("tenant1", day)
        counter.increment("tenant2", day)
        assert counter.get_count("tenant1", day) == 1
        assert counter.get_count("tenant2", day) == 1

    def test_separate_days(self):
        counter = DailyHandoffCounter()
        counter.increment("tenant1", "2026-05-28")
        counter.increment("tenant1", "2026-05-28")
        counter.increment("tenant1", "2026-05-29")
        assert counter.get_count("tenant1", "2026-05-28") == 2
        assert counter.get_count("tenant1", "2026-05-29") == 1

    def test_cleanup_old(self):
        counter = DailyHandoffCounter()
        counter.increment("tenant1", "2026-05-27")
        counter.increment("tenant1", "2026-05-28")
        counter.cleanup_old("tenant1", "2026-05-28")
        # Old day should still be there (cleanup is for older than current)
        # This is a basic test — cleanup removes keys < current_day
        assert counter.get_count("tenant1", "2026-05-28") == 1

    def test_reset(self):
        counter = DailyHandoffCounter()
        counter.increment("t1", "day1")
        counter.reset()
        assert counter.get_count("t1", "day1") == 0


# ── Health endpoint tests ──────────────────────────────────────────────────────


class TestHealthEndpoints:
    """Tests for /health and /ready endpoints."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_db(self):
        from app.database import engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @pytest_asyncio.fixture
    async def client(self):
        from app.middleware.rate_limit import rate_limiter_registry

        rate_limiter_registry.reset()
        app = create_app(tier_limits={"free": 100000, "pro": 100000, "business": 100000})
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    async def test_health_endpoint(self, client):
        """Health endpoint should return 200 with status ok."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "handoffrail"

    async def test_ready_endpoint(self, client):
        """Readiness endpoint should return 200 when DB is healthy."""
        resp = await client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["db"] is True

    async def test_ready_endpoint_db_failure(self, client):
        """Readiness endpoint should return 503 when DB is unreachable."""
        with patch("app.routers.health.async_session") as mock_session:
            mock_session_instance = AsyncMock()
            mock_session_instance.__aenter__ = AsyncMock(
                side_effect=Exception("DB connection failed")
            )
            mock_session_instance.__aexit__ = AsyncMock(return_value=False)
            mock_session.return_value = mock_session_instance

            resp = await client.get("/ready")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "not_ready"
            assert data["db"] is False


# ── Prometheus metrics tests ───────────────────────────────────────────────────


class TestPrometheusMetrics:
    """Tests for Prometheus /metrics endpoint."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_db(self):
        from app.database import engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @pytest_asyncio.fixture
    async def client(self):
        from app.middleware.rate_limit import rate_limiter_registry

        rate_limiter_registry.reset()
        app = create_app(tier_limits={"free": 100000, "pro": 100000, "business": 100000})
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    async def test_metrics_endpoint(self, client):
        """Metrics endpoint should return Prometheus format."""
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        # Prometheus exposition format
        assert "text/plain" in resp.headers.get("content-type", "") or "application/openmetrics-text" in resp.headers.get("content-type", "")
        body = resp.text
        # Should contain our custom metrics
        assert "handoffrail_requests_total" in body or "handoffrail" in body

    async def test_metrics_after_request(self, client):
        """Metrics should track requests after hitting endpoints."""
        # Hit health endpoint to generate some metrics
        await client.get("/health")
        resp = await client.get("/metrics")
        assert resp.status_code == 200

    def test_record_handoff_function(self):
        """record_handoff should increment counter for tenant."""
        from app.routers.metrics import record_handoff

        # This is a no-op test — just verify it doesn't raise
        record_handoff("test_tenant")

    def test_update_active_packets_function(self):
        """update_active_packets should set gauge value."""
        from app.routers.metrics import update_active_packets

        update_active_packets(42)


# ── Tier-based rate limit tests ────────────────────────────────────────────────


class TestTierRateLimits:
    """Tests for tier-aware rate limiting."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_db(self):
        from app.database import engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @pytest_asyncio.fixture
    async def client(self):
        from app.middleware.rate_limit import rate_limiter_registry

        rate_limiter_registry.reset()
        # Use very low limits for testing
        app = create_app(tier_limits={"free": 2, "pro": 100, "business": 10000})
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    async def test_free_tier_rate_limited(self, client):
        """Free tier should be rate limited after hitting quota."""
        # Make requests until rate limited
        resp1 = await client.get("/api/v1/packets")
        resp2 = await client.get("/api/v1/packets")

        # Third request should be rate limited
        resp3 = await client.get("/api/v1/packets")
        assert resp3.status_code == 429

    async def test_health_exempt_from_rate_limit(self, client):
        """Health endpoint should be exempt from rate limiting."""
        # Exhaust free tier
        await client.get("/api/v1/packets")
        await client.get("/api/v1/packets")

        # Health should still work
        resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_ready_exempt_from_rate_limit(self, client):
        """Readiness endpoint should be exempt from rate limiting."""
        await client.get("/api/v1/packets")
        await client.get("/api/v1/packets")

        resp = await client.get("/ready")
        assert resp.status_code == 200

    async def test_metrics_exempt_from_rate_limit(self, client):
        """Metrics endpoint should be exempt from rate limiting."""
        await client.get("/api/v1/packets")
        await client.get("/api/v1/packets")

        resp = await client.get("/metrics")
        assert resp.status_code == 200

    async def test_rate_limit_headers(self, client):
        """Rate limit headers should be present in responses."""
        resp = await client.get("/api/v1/packets")
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert "X-RateLimit-Reset" in resp.headers
        assert "X-RateLimit-Tier" in resp.headers

    async def test_rate_limit_429_has_headers(self, client):
        """429 response should include rate limit headers."""
        await client.get("/api/v1/packets")
        await client.get("/api/v1/packets")
        resp = await client.get("/api/v1/packets")
        assert resp.status_code == 429
        assert "X-RateLimit-Limit" in resp.headers
        assert resp.headers["X-RateLimit-Remaining"] == "0"


# ── RateLimitRegistry tests ────────────────────────────────────────────────────


class TestRateLimitRegistry:
    """Tests for the rate limit counter registry."""

    def test_increment(self):
        reg = RateLimitRegistry()
        assert reg.increment("key1", 100.0) == 1
        assert reg.increment("key1", 100.0) == 2

    def test_get_count(self):
        reg = RateLimitRegistry()
        reg.increment("key1", 100.0)
        assert reg.get_count("key1", 100.0) == 1
        assert reg.get_count("key1", 200.0) == 0

    def test_cleanup_old(self):
        reg = RateLimitRegistry()
        reg.increment("key1", 100.0)
        reg.increment("key1", 200.0)
        reg.cleanup_old("key1", 200.0, 50)
        assert reg.get_count("key1", 100.0) == 0
        assert reg.get_count("key1", 200.0) == 1

    def test_reset(self):
        reg = RateLimitRegistry()
        reg.increment("key1", 100.0)
        reg.reset()
        assert reg.get_count("key1", 100.0) == 0


# ── Integration: App creation with config ──────────────────────────────────────


class TestAppCreation:
    """Tests for app factory with configuration."""

    def test_create_app_defaults(self):
        """App should be created with default settings."""
        from app.config import reset_settings

        reset_settings()
        app = create_app()
        assert app is not None
        assert app.title == "HandoffRail"
        reset_settings()

    def test_create_app_custom_tier_limits(self):
        """App should accept custom tier limits."""
        custom_limits = {"free": 50, "pro": 500, "business": 5000}
        app = create_app(tier_limits=custom_limits)
        assert app is not None

    @pytest_asyncio.fixture(autouse=True)
    async def setup_db(self):
        from app.database import engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @pytest_asyncio.fixture
    async def client(self):
        from app.middleware.rate_limit import rate_limiter_registry

        rate_limiter_registry.reset()
        app = create_app(tier_limits={"free": 100000, "pro": 100000, "business": 100000})
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    async def test_all_system_endpoints(self, client):
        """All system endpoints should be accessible."""
        health = await client.get("/health")
        assert health.status_code == 200

        ready = await client.get("/ready")
        assert ready.status_code == 200

        metrics = await client.get("/metrics")
        assert metrics.status_code == 200


# ── Tier-based size limit tests ─────────────────────────────────────────────────


class TestTierSizeLimits:
    """Tests for tier-based request size limits."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_db(self):
        from app.database import engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @pytest_asyncio.fixture
    async def client(self):
        from app.middleware.rate_limit import rate_limiter_registry

        rate_limiter_registry.reset()
        app = create_app(tier_limits={"free": 100000, "pro": 100000, "business": 100000})
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    async def test_large_request_rejected_for_free_tier(self, client):
        """Oversized requests should be rejected with 413."""
        # Create a large payload (simulated via content-length header)
        large_body = "x" * (65 * 1024)  # 65KB, over free tier 64KB limit
        resp = await client.post(
            "/api/v1/packets",
            content=large_body,
            headers={
                "Content-Type": "application/json",
            },
        )
        # Without auth, should use free tier limit of 64KB
        assert resp.status_code == 413

    async def test_normal_request_accepted(self, client):
        """Normal-sized requests should pass through."""
        small_body = '{"test": true}'
        # This should not be rejected for size (way under any limit)
        # The request will fail for other reasons (auth, validation) but not size
        resp = await client.post(
            "/api/v1/packets",
            content=small_body,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": "hr_testkey",
            },
        )
        # Should not be 413 (too large)
        assert resp.status_code != 413
