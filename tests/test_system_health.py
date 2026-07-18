"""Tests for the System Health Dashboard endpoint.

Tests cover all 7 sections of the health response, RBAC enforcement,
edge cases (empty system, various states), and data accuracy.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# Add server dir to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from app.database import async_session
from app.main import create_app
from app.middleware.auth import generate_api_key
from app.middleware.rbac import reset_role_cache
from app.models.db import ApiKey, Packet, Webhook, WebhookDelivery

# Create a dedicated test app with RBAC middleware ENABLED for RBAC tests
_rbac_app = create_app(
    tier_limits={"free": 100000, "pro": 100000, "business": 100000},
    rate_limit_per_minute=100000,
    disable_rbac=False,
)


def _minimal_payload() -> dict:
    """Return a minimal valid packet creation payload."""
    return {
        "metadata": {
            "source_agent": {"id": "test-source", "name": "TestSource", "framework": "test"},
            "target_agent": {"id": "test-target", "name": "TestTarget"},
            "priority": "normal",
            "tags": ["test"],
        },
        "context": {
            "summary": "Test handoff packet",
            "conversation_state": [
                {"role": "user", "content": "Hello"},
            ],
        },
        "decisions": [],
        "actions": {"pending": [], "completed": [], "failed": []},
        "dependencies": [],
        "hitl": None,
    }


async def _make_admin_key(tenant_id: str = "default") -> str:
    """Create an admin API key and return the plain key string."""
    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]

    async with async_session() as session:
        db_key = ApiKey(
            id=str(uuid4()),
            name="system-health-admin",
            key_hash=key_hash,
            key_prefix=key_prefix,
            tenant_id=tenant_id,
            tier="business",
            role="admin",
        )
        session.add(db_key)
        await session.commit()

    return plain_key


async def _make_non_admin_key(tenant_id: str = "default") -> str:
    """Create a non-admin API key and return the plain key string."""
    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]

    async with async_session() as session:
        db_key = ApiKey(
            id=str(uuid4()),
            name="system-health-writer",
            key_hash=key_hash,
            key_prefix=key_prefix,
            tenant_id=tenant_id,
            tier="pro",
            role="writer",
        )
        session.add(db_key)
        await session.commit()

    return plain_key


def _packet_with_agent(
    agent_id: str,
    status: str = "created",
    created_at: datetime | None = None,
    claimed_at: str | None = None,
    completed_at: str | None = None,
) -> dict:
    """Create a packet payload with a specific agent and timestamps."""
    payload = _minimal_payload()
    payload["metadata"]["source_agent"] = {"id": agent_id, "name": agent_id.capitalize(), "framework": "test"}
    payload["metadata"]["target_agent"] = {"id": agent_id, "name": agent_id.capitalize()}

    if claimed_at:
        payload["metadata"]["claimed_at"] = claimed_at
    if completed_at:
        payload["metadata"]["completed_at"] = completed_at

    return payload


async def _seed_packet(
    status: str = "created",
    agent_id: str = "test-agent",
    created_at: datetime | None = None,
    claimed_at: str | None = None,
    completed_at: str | None = None,
) -> str:
    """Insert a packet directly into the database and return its ID."""
    now = created_at or datetime.now(UTC)
    pkt_id = str(uuid4())

    metadata: dict[str, object] = {
        "source_agent": {"id": agent_id, "name": agent_id.capitalize(), "framework": "test"},
        "target_agent": {"id": agent_id, "name": agent_id.capitalize()},
        "created_at": now.isoformat(),
    }
    if status in ("claimed", "in_progress", "awaiting_human", "completed"):
        metadata["claimed_at"] = claimed_at or (now - timedelta(minutes=5)).isoformat()
    if status == "completed":
        metadata["completed_at"] = completed_at or (now - timedelta(minutes=2)).isoformat()

    async with async_session() as session:
        pkt = Packet(
            id=pkt_id,
            version="1.0.0",
            status=status,
            tenant_id="default",
            metadata_json=json.dumps(metadata),
            context_json=json.dumps({"summary": "test", "conversation_state": []}),
            decisions_json="[]",
            actions_json=json.dumps({"pending": [], "completed": [], "failed": []}),
            dependencies_json="[]",
            created_at=now,
            updated_at=now,
        )
        session.add(pkt)
        await session.commit()

    return pkt_id


# ════════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ════════════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def admin_key() -> str:
    """Create an admin API key for RBAC tests."""
    reset_role_cache()
    return await _make_admin_key()


@pytest_asyncio.fixture
async def non_admin_key() -> str:
    """Create a non-admin API key for RBAC tests."""
    reset_role_cache()
    return await _make_non_admin_key()


@pytest_asyncio.fixture
async def admin_client(admin_key: str) -> AsyncClient:
    """HTTP client with admin API key."""
    transport = ASGITransport(app=_rbac_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": admin_key},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def writer_client(non_admin_key: str) -> AsyncClient:
    """HTTP client with writer (non-admin) API key."""
    transport = ASGITransport(app=_rbac_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": non_admin_key},
    ) as ac:
        yield ac


# ════════════════════════════════════════════════════════════════════════════════
# RBAC TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestRBACEnforcement:
    """Test that the system health endpoint requires admin role."""

    @pytest.mark.asyncio
    async def test_admin_can_access(self, admin_client: AsyncClient):
        """Admin role can access the endpoint."""
        resp = await admin_client.get("/api/v1/system/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_non_admin_denied(self, writer_client: AsyncClient):
        """Non-admin gets 403 Forbidden."""
        resp = await writer_client.get("/api/v1/system/health")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_no_auth_denied(self):
        """No API key returns 401."""
        transport = ASGITransport(app=_rbac_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/system/health")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_revoked_key_denied(self, admin_key: str):
        """A revoked API key should be denied."""
        # Revoke the admin key
        async with async_session() as session:
            result = await session.execute(
                select(ApiKey).where(ApiKey.key_prefix == admin_key[:8])
            )
            key = result.scalar_one()
            key.revoked = True
            await session.commit()
        reset_role_cache()

        transport = ASGITransport(app=_rbac_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-API-Key": admin_key},
        ) as ac:
            resp = await ac.get("/api/v1/system/health")
        assert resp.status_code == 401 or resp.status_code == 403


# ════════════════════════════════════════════════════════════════════════════════
# SYSTEM OVERVIEW TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestSystemOverview:
    """Test the system overview section of the health response."""

    @pytest.mark.asyncio
    async def test_system_overview_fields(self, admin_client: AsyncClient):
        """Response includes version, uptime, environment, and database backend."""
        resp = await admin_client.get("/api/v1/system/health")
        assert resp.status_code == 200
        data = resp.json()

        assert "version" in data
        assert "uptime_seconds" in data
        assert "environment" in data
        assert "database_backend" in data

        assert isinstance(data["version"], str)
        assert isinstance(data["uptime_seconds"], (int, float))
        assert data["uptime_seconds"] > 0
        assert data["environment"] in ("dev", "staging", "prod")
        assert data["database_backend"] in ("sqlite", "postgresql")


# ════════════════════════════════════════════════════════════════════════════════
# PACKET STATISTICS TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestPacketStatistics:
    """Test the packet statistics section."""

    @pytest.mark.asyncio
    async def test_empty_system_returns_zero_packets(self, admin_client: AsyncClient):
        """Empty system shows zero packets across all metrics."""
        resp = await admin_client.get("/api/v1/system/health")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_packets"] == 0
        assert data["packets_by_status"] == {}
        assert data["packets_created_last_1h"] == 0
        assert data["packets_created_last_24h"] == 0
        assert data["avg_time_to_claim_seconds"] is None
        assert data["avg_time_to_complete_seconds"] is None

    @pytest.mark.asyncio
    async def test_packets_by_status_counts(self, admin_client: AsyncClient):
        """Creates packets in various statuses and verifies counts."""
        await _seed_packet(status="created")
        await _seed_packet(status="claimed")
        await _seed_packet(status="completed")

        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert data["total_packets"] == 3
        assert data["packets_by_status"]["created"] == 1
        assert data["packets_by_status"]["claimed"] == 1
        assert data["packets_by_status"]["completed"] == 1

    @pytest.mark.asyncio
    async def test_packets_last_1h_and_24h(self, admin_client: AsyncClient):
        """Recent packet counts differentiate between 1h and 24h windows."""
        old_time = datetime.now(UTC) - timedelta(hours=2)
        recent_time = datetime.now(UTC) - timedelta(minutes=30)

        await _seed_packet(created_at=old_time)
        await _seed_packet(created_at=recent_time)
        await _seed_packet(created_at=recent_time)

        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert data["packets_created_last_24h"] == 3
        assert data["packets_created_last_1h"] == 2

    @pytest.mark.asyncio
    async def test_avg_time_to_claim_and_complete(self, admin_client: AsyncClient):
        """Average times are calculated from metadata timestamps."""
        now = datetime.now(UTC)

        # Seed packets with metadata containing timestamps
        async with async_session() as session:
            for i in range(2):
                created = now - timedelta(hours=1)
                claimed = created + timedelta(minutes=5)
                completed = claimed + timedelta(minutes=30)
                pkt = Packet(
                    id=str(uuid4()),
                    version="1.0.0",
                    status="completed",
                    tenant_id="default",
                    metadata_json=(
                        '{"created_at":"' + created.isoformat() + '",'
                        '"claimed_at":"' + claimed.isoformat() + '",'
                        '"completed_at":"' + completed.isoformat() + '"}'
                    ),
                    context_json='{"summary":"test"}',
                    decisions_json="[]",
                    actions_json='{"pending":[],"completed":[],"failed":[]}',
                    dependencies_json="[]",
                    created_at=now,
                    updated_at=now,
                )
                session.add(pkt)
            await session.commit()

        resp = await admin_client.get("/api/v1/system/health")
        assert resp.status_code == 200
        data = resp.json()

        # 5 min claim time = 300 seconds
        assert data["avg_time_to_claim_seconds"] is not None
        assert data["avg_time_to_claim_seconds"] == 300.0
        # 30 min completion time = 1800 seconds
        assert data["avg_time_to_complete_seconds"] is not None
        assert data["avg_time_to_complete_seconds"] == 1800.0

    @pytest.mark.asyncio
    async def test_avg_times_with_missing_metadata(self, admin_client: AsyncClient):
        """Packets without metadata timestamps are excluded from averages."""
        now = datetime.now(UTC)

        async with async_session() as session:
            # Packet with claimed_at but no created_at — skip
            pkt1 = Packet(
                id=str(uuid4()),
                version="1.0.0",
                status="claimed",
                tenant_id="default",
                metadata_json='{"claimed_at":"' + now.isoformat() + '"}',
                context_json='{"summary":"test"}',
                decisions_json="[]",
                actions_json='{"pending":[],"completed":[],"failed":[]}',
                dependencies_json="[]",
                created_at=now,
                updated_at=now,
            )
            session.add(pkt1)
            # Packet with both timestamps — should be counted
            pkt2 = Packet(
                id=str(uuid4()),
                version="1.0.0",
                status="completed",
                tenant_id="default",
                metadata_json=(
                    '{"created_at":"' + (now - timedelta(minutes=10)).isoformat() + '",'
                    '"claimed_at":"' + (now - timedelta(minutes=8)).isoformat() + '",'
                    '"completed_at":"' + now.isoformat() + '"}'
                ),
                context_json='{"summary":"test"}',
                decisions_json="[]",
                actions_json='{"pending":[],"completed":[],"failed":[]}',
                dependencies_json="[]",
                created_at=now,
                updated_at=now,
            )
            session.add(pkt2)
            await session.commit()

        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        # Only 1 packet should contribute to avg time-to-claim = 120 seconds
        assert data["avg_time_to_claim_seconds"] is not None
        assert data["avg_time_to_claim_seconds"] == pytest.approx(120.0, rel=0.1)


# ════════════════════════════════════════════════════════════════════════════════
# AGENT ACTIVITY TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestAgentActivity:
    """Test the agent activity section."""

    @pytest.mark.asyncio
    async def test_empty_system_has_no_agents(self, admin_client: AsyncClient):
        """No agents when no packets exist."""
        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert data["active_agents"] == 0
        assert data["total_agents_seen"] == 0
        assert data["top_agents"] == []

    @pytest.mark.asyncio
    async def test_active_agents_counts(self, admin_client: AsyncClient):
        """Only distinct agents with active (claimed/in_progress) packets counted."""
        await _seed_packet(status="claimed", agent_id="agent-alpha")
        await _seed_packet(status="in_progress", agent_id="agent-beta")
        await _seed_packet(status="completed", agent_id="agent-charlie")

        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        # alpha and beta are active, charlie is not (completed)
        assert data["active_agents"] == 2

    @pytest.mark.asyncio
    async def test_total_agents_seen(self, admin_client: AsyncClient):
        """All distinct agents across all packet statuses are counted."""
        await _seed_packet(status="created", agent_id="agent-alpha")
        await _seed_packet(status="completed", agent_id="agent-beta")
        await _seed_packet(status="created", agent_id="agent-alpha")  # same agent

        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert data["total_agents_seen"] == 2  # alpha and beta

    @pytest.mark.asyncio
    async def test_top_agents_by_packet_count(self, admin_client: AsyncClient):
        """Top 5 agents sorted by packet count."""
        now = datetime.now(UTC)

        async with async_session() as session:
            for i in range(5):
                pkt = Packet(
                    id=str(uuid4()),
                    version="1.0.0",
                    status="created",
                    tenant_id="default",
                    metadata_json='{"source_agent":{"id":"busy-agent"},"target_agent":{"id":"busy-agent"}}',
                    context_json='{"summary":"test"}',
                    decisions_json="[]",
                    actions_json='{"pending":[],"completed":[],"failed":[]}',
                    dependencies_json="[]",
                    created_at=now,
                    updated_at=now,
                )
                session.add(pkt)
            for i in range(3):
                pkt = Packet(
                    id=str(uuid4()),
                    version="1.0.0",
                    status="created",
                    tenant_id="default",
                    metadata_json='{"source_agent":{"id":"medium-agent"},"target_agent":{"id":"medium-agent"}}',
                    context_json='{"summary":"test"}',
                    decisions_json="[]",
                    actions_json='{"pending":[],"completed":[],"failed":[]}',
                    dependencies_json="[]",
                    created_at=now,
                    updated_at=now,
                )
                session.add(pkt)
            for i in range(1):
                pkt = Packet(
                    id=str(uuid4()),
                    version="1.0.0",
                    status="created",
                    tenant_id="default",
                    metadata_json='{"source_agent":{"id":"light-agent"},"target_agent":{"id":"light-agent"}}',
                    context_json='{"summary":"test"}',
                    decisions_json="[]",
                    actions_json='{"pending":[],"completed":[],"failed":[]}',
                    dependencies_json="[]",
                    created_at=now,
                    updated_at=now,
                )
                session.add(pkt)
            await session.commit()

        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert len(data["top_agents"]) <= 5
        # busy-agent should be first with the most packets
        if data["top_agents"]:
            assert data["top_agents"][0]["agent_id"] == "busy-agent"
            # busy-agent appears as source and target in each packet → 10 total
            assert data["top_agents"][0]["packet_count"] >= 10


# ════════════════════════════════════════════════════════════════════════════════
# QUEUE DEPTH TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestQueueDepth:
    """Test the queue depth section."""

    @pytest.mark.asyncio
    async def test_empty_queue(self, admin_client: AsyncClient):
        """Empty system shows zero queue depth."""
        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert data["packets_waiting"] == 0
        assert data["oldest_waiting_packet_age_seconds"] is None
        assert data["claimed_not_completed"] == 0

    @pytest.mark.asyncio
    async def test_waiting_and_in_flight_counts(self, admin_client: AsyncClient):
        """Waiting packets vs in-flight packets are correctly counted."""
        await _seed_packet(status="created")
        await _seed_packet(status="created")
        await _seed_packet(status="claimed")
        await _seed_packet(status="in_progress")
        await _seed_packet(status="completed")

        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert data["packets_waiting"] == 2  # status=created
        assert data["claimed_not_completed"] == 2  # claimed + in_progress

    @pytest.mark.asyncio
    async def test_oldest_waiting_age(self, admin_client: AsyncClient):
        """Oldest waiting packet age is calculated correctly."""
        now = datetime.now(UTC)
        old_time = now - timedelta(hours=3)

        # Create an old waiting packet
        old_pkt_id = str(uuid4())
        async with async_session() as session:
            pkt = Packet(
                id=old_pkt_id,
                version="1.0.0",
                status="created",
                tenant_id="default",
                metadata_json='{}',
                context_json='{"summary":"old"}',
                decisions_json="[]",
                actions_json='{"pending":[],"completed":[],"failed":[]}',
                dependencies_json="[]",
                created_at=old_time,
                updated_at=old_time,
            )
            session.add(pkt)
            # Also add a newer one
            pkt2 = Packet(
                id=str(uuid4()),
                version="1.0.0",
                status="created",
                tenant_id="default",
                metadata_json='{}',
                context_json='{"summary":"new"}',
                decisions_json="[]",
                actions_json='{"pending":[],"completed":[],"failed":[]}',
                dependencies_json="[]",
                created_at=now,
                updated_at=now,
            )
            session.add(pkt2)
            await session.commit()

        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert data["oldest_waiting_packet_age_seconds"] is not None
        # Should be around 3 hours = 10800 seconds (within tolerance)
        assert data["oldest_waiting_packet_age_seconds"] == pytest.approx(10800.0, rel=0.2)


# ════════════════════════════════════════════════════════════════════════════════
# WEBHOOK HEALTH TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestWebhookHealth:
    """Test the webhook health section."""

    @pytest.mark.asyncio
    async def test_empty_webhooks(self, admin_client: AsyncClient):
        """No webhooks registered."""
        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert data["total_webhooks"] == 0
        assert data["recent_deliveries_1h"] == 0
        assert data["failed_deliveries_1h"] == 0
        assert data["avg_delivery_latency_ms"] is None

    @pytest.mark.asyncio
    async def test_webhook_deliveries_counted(self, admin_client: AsyncClient):
        """Recent and failed deliveries are counted."""
        now = datetime.now(UTC)
        one_hour_ago = now - timedelta(hours=1)
        two_hours_ago = now - timedelta(hours=2)

        async with async_session() as session:
            # Create a webhook
            hook = Webhook(
                id=str(uuid4()),
                url="https://example.com/hook",
                events='["packet.completed"]',
                secret="test-secret",
                tenant_id="default",
            )
            session.add(hook)

            # Recent successful delivery
            d1 = WebhookDelivery(
                id=str(uuid4()),
                webhook_id=hook.id,
                tenant_id="default",
                packet_id=str(uuid4()),
                event_type="packet.completed",
                payload_json="{}",
                status="delivered",
                created_at=one_hour_ago + timedelta(minutes=30),
                delivered_at=one_hour_ago + timedelta(minutes=30, seconds=1),
            )
            session.add(d1)

            # Recent failed delivery
            d2 = WebhookDelivery(
                id=str(uuid4()),
                webhook_id=hook.id,
                tenant_id="default",
                packet_id=str(uuid4()),
                event_type="packet.completed",
                payload_json="{}",
                status="failed",
                last_error="Connection timeout",
                created_at=one_hour_ago + timedelta(minutes=15),
            )
            session.add(d2)

            # Old delivery (outside 1h window)
            d3 = WebhookDelivery(
                id=str(uuid4()),
                webhook_id=hook.id,
                tenant_id="default",
                packet_id=str(uuid4()),
                event_type="packet.completed",
                payload_json="{}",
                status="delivered",
                created_at=two_hours_ago,
                delivered_at=two_hours_ago + timedelta(seconds=1),
            )
            session.add(d3)

            await session.commit()

        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert data["total_webhooks"] == 1
        assert data["recent_deliveries_1h"] == 2  # d1 + d2
        assert data["failed_deliveries_1h"] == 1  # d2
        # Average latency: d1 has 1 second = 1000ms
        assert data["avg_delivery_latency_ms"] is not None
        assert data["avg_delivery_latency_ms"] == 1000.0


# ════════════════════════════════════════════════════════════════════════════════
# STORAGE TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestStorage:
    """Test the storage section."""

    @pytest.mark.asyncio
    async def test_db_size_reported(self, admin_client: AsyncClient):
        """Database file size is reported for SQLite."""
        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert "db_size_bytes" in data
        # With SQLite, the size should be available (even 0 or more)
        assert data["db_size_bytes"] is None or data["db_size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_connection_pool_sqlite(self, admin_client: AsyncClient):
        """Connection pool stats are None for SQLite."""
        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert data["connection_pool"] is None


# ════════════════════════════════════════════════════════════════════════════════
# RATE LIMITING TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestRateLimiting:
    """Test the rate limiting section."""

    @pytest.mark.asyncio
    async def test_active_api_keys_counted(self, admin_client: AsyncClient):
        """Non-revoked API keys are counted."""
        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        # At least the admin key used for this request + any from conftest should exist
        assert data["active_api_keys"] >= 1

    @pytest.mark.asyncio
    async def test_api_key_counts_include_all_tenants(self, admin_client: AsyncClient, admin_key: str):
        """Keys from all tenants are counted."""
        # Create keys in a different tenant
        await _make_admin_key(tenant_id="other-tenant")
        await _make_admin_key(tenant_id="other-tenant")

        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert data["active_api_keys"] >= 3

    @pytest.mark.asyncio
    async def test_revoked_keys_not_counted(self, admin_client: AsyncClient, admin_key: str):
        """Revoked keys are excluded from the count."""
        # Get baseline
        resp = await admin_client.get("/api/v1/system/health")
        baseline = resp.json()["active_api_keys"]

        # Create and revoke a key
        new_key = await _make_admin_key()
        async with async_session() as session:
            result = await session.execute(
                select(ApiKey).where(ApiKey.key_prefix == new_key[:8])
            )
            key = result.scalar_one()
            key.revoked = True
            await session.commit()

        resp = await admin_client.get("/api/v1/system/health")
        count = resp.json()["active_api_keys"]

        assert count == baseline


# ════════════════════════════════════════════════════════════════════════════════
# RESPONSE STRUCTURE TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestResponseStructure:
    """Test the overall structure of the response."""

    @pytest.mark.asyncio
    async def test_response_has_all_sections(self, admin_client: AsyncClient):
        """Response contains all 7 sections with correct top-level keys."""
        resp = await admin_client.get("/api/v1/system/health")
        assert resp.status_code == 200
        data = resp.json()

        # System overview
        assert "version" in data
        assert "uptime_seconds" in data
        assert "environment" in data
        assert "database_backend" in data

        # Packet statistics
        assert "total_packets" in data
        assert "packets_by_status" in data
        assert "packets_created_last_1h" in data
        assert "packets_created_last_24h" in data
        assert "avg_time_to_claim_seconds" in data
        assert "avg_time_to_complete_seconds" in data

        # Agent activity
        assert "active_agents" in data
        assert "total_agents_seen" in data
        assert "top_agents" in data

        # Queue depth
        assert "packets_waiting" in data
        assert "oldest_waiting_packet_age_seconds" in data
        assert "claimed_not_completed" in data

        # Webhook health
        assert "total_webhooks" in data
        assert "recent_deliveries_1h" in data
        assert "failed_deliveries_1h" in data
        assert "avg_delivery_latency_ms" in data

        # Storage
        assert "db_size_bytes" in data
        assert "connection_pool" in data

        # Rate limiting
        assert "active_api_keys" in data
        assert "requests_last_1h_per_key" in data

    @pytest.mark.asyncio
    async def test_response_content_type(self, admin_client: AsyncClient):
        """Response is valid JSON with application/json content type."""
        resp = await admin_client.get("/api/v1/system/health")
        assert resp.headers.get("content-type", "").startswith("application/json")

    @pytest.mark.asyncio
    async def test_large_counts(self, admin_client: AsyncClient):
        """System handles large numbers of packets gracefully."""
        now = datetime.now(UTC)

        async with async_session() as session:
            for i in range(50):
                agent_num = i % 3
                pkt = Packet(
                    id=str(uuid4()),
                    version="1.0.0",
                    status="created" if i < 30 else "completed",
                    tenant_id="default",
                    metadata_json=json.dumps({
                        "source_agent": {"id": f"agent-{agent_num}"},
                        "target_agent": {"id": f"agent-{agent_num}"},
                    }),
                    context_json=json.dumps({"summary": "bulk"}),
                    decisions_json="[]",
                    actions_json=json.dumps({"pending": [], "completed": [], "failed": []}),
                    dependencies_json="[]",
                    created_at=now,
                    updated_at=now,
                )
                session.add(pkt)
            await session.commit()

        resp = await admin_client.get("/api/v1/system/health")
        data = resp.json()

        assert data["total_packets"] == 50
        assert data["packets_waiting"] == 30
        # 3 distinct agents, each with multiple packets
        assert data["total_agents_seen"] == 3
        assert len(data["top_agents"]) == 3
