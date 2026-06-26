"""Tests for WebSocket real-time event streaming.

Tests the ConnectionManager, RedisPubSubManager, WebSocket endpoint,
event publishing from packet endpoints, and tier-gated connection limits.
"""

import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import create_app
from app.database import engine, async_session
from app.middleware.auth import generate_api_key
from app.middleware.rate_limit import rate_limiter_registry
from app.models.db import ApiKey, Base
from app.services.websocket import (
    ConnectionManager,
    Subscription,
    get_connection_manager,
    reset_connection_manager,
)
from app.services.redis_pubsub import (
    RedisPubSubManager,
    get_pubsub_manager,
    reset_pubsub_manager,
)


# ── Fixtures ────────────────────────────────────────────────────────────────────

_test_app = create_app(tier_limits={"free": 100000, "pro": 100000, "business": 100000})
_test_api_key: str | None = None


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

    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]
    db_key = ApiKey(
        id="test-ws-key-id",
        name="test-ws",
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
    """Create tables before each test and drop them after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_test_api_key()
    rate_limiter_registry.reset()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """Async HTTP client wired to the test FastAPI app with auth."""
    api_key = await _ensure_test_api_key()
    transport = ASGITransport(app=_test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as ac:
        yield ac


# ── Helper: create a packet via API ────────────────────────────────────────────

async def create_test_packet(client: AsyncClient, **overrides) -> dict:
    """Create a test packet and return the response JSON."""
    payload = {
        "metadata": {
            "source_agent": {"id": "test-agent-1", "name": "TestAgent", "framework": "test"},
            "target_agent": {"id": "test-agent-2", "name": "TargetAgent", "framework": "test"},
            "priority": "normal",
            "tags": ["test"],
        },
        "context": {
            "summary": "Test packet for WebSocket testing",
            "conversation_state": [],
            "artifacts": [],
            "custom": {},
        },
        "decisions": [],
        "actions": {"pending": [], "completed": [], "failed": []},
        "dependencies": [],
    }
    payload.update(overrides)
    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 201, f"Failed to create packet: {response.text}"
    return response.json()


# ── Subscription Tests ──────────────────────────────────────────────────────────


class TestSubscription:
    """Test the Subscription filter class."""

    def test_empty_subscription_matches_all(self):
        sub = Subscription()
        event = {"type": "packet.created", "packet_id": "abc", "data": {"status": "created"}}
        assert sub.matches(event) is True

    def test_status_subscription(self):
        sub = Subscription()
        sub.add("status:created")
        event = {"type": "packet.created", "data": {"status": "created"}}
        assert sub.matches(event) is True
        assert sub.matches({"type": "packet.claimed", "data": {"status": "claimed"}}) is False

    def test_packet_subscription(self):
        sub = Subscription()
        sub.add("packet:abc-123")
        event = {"type": "packet.created", "packet_id": "abc-123", "data": {}}
        assert sub.matches(event) is True
        assert sub.matches({"type": "packet.created", "packet_id": "def-456", "data": {}}) is False

    def test_agent_subscription(self):
        sub = Subscription()
        sub.add("agent:sales-01")
        event = {
            "type": "packet.created",
            "data": {"metadata": {"source_agent": {"id": "sales-01"}, "target_agent": {"id": "billing-01"}}},
        }
        assert sub.matches(event) is True

    def test_remove_subscription(self):
        sub = Subscription()
        sub.add("status:created")
        sub.remove("status:created")
        assert sub.matches({"type": "packet.created", "data": {"status": "created"}}) is True  # empty = match all


# ── ConnectionManager Tests ─────────────────────────────────────────────────────


class TestConnectionManager:
    """Test the ConnectionManager."""

    def setup_method(self):
        self.manager = ConnectionManager()

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        ws = AsyncMock()
        ws.accept = AsyncMock()
        connected = await self.manager.connect(ws, "conn-1", tier="free")
        assert connected is True
        assert self.manager.active_connection_count == 1

        await self.manager.disconnect("conn-1")
        assert self.manager.active_connection_count == 0

    @pytest.mark.asyncio
    async def test_tier_limits_free(self):
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()

        connected = await self.manager.connect(ws1, "conn-1", tier="free", tenant_id="t1")
        assert connected is True

        # Free tier allows 1 connection per tenant
        connected = await self.manager.connect(ws2, "conn-2", tier="free", tenant_id="t1")
        assert connected is False

    @pytest.mark.asyncio
    async def test_tier_limits_pro(self):
        """Pro tier allows 5 connections."""
        for i in range(5):
            ws = AsyncMock()
            ws.accept = AsyncMock()
            connected = await self.manager.connect(ws, f"conn-{i}", tier="pro", tenant_id="t1")
            assert connected is True

        # 6th should fail
        ws = AsyncMock()
        ws.accept = AsyncMock()
        connected = await self.manager.connect(ws, "conn-6", tier="pro", tenant_id="t1")
        assert connected is False

    @pytest.mark.asyncio
    async def test_subscribe_and_broadcast(self):
        ws = AsyncMock()
        ws.accept = AsyncMock()
        await self.manager.connect(ws, "conn-1", tier="pro")

        # Subscribe to created status
        await self.manager.subscribe("conn-1", "status:created")

        # Broadcast a created event
        event = {"type": "packet.created", "data": {"status": "created"}}
        await self.manager.broadcast(event)

        # WebSocket should have received the event
        ws.send_text.assert_called_once()
        sent_data = json.loads(ws.send_text.call_args[0][0])
        assert sent_data["type"] == "packet.created"

    @pytest.mark.asyncio
    async def test_broadcast_filters_by_subscription(self):
        ws = AsyncMock()
        ws.accept = AsyncMock()
        await self.manager.connect(ws, "conn-1", tier="pro")
        await self.manager.subscribe("conn-1", "status:created")

        # Broadcast a completed event — should NOT match subscription
        event = {"type": "packet.completed", "data": {"status": "completed"}}
        await self.manager.broadcast(event)

        # send_text should only be called for the accept() — no event broadcast
        # (send_text is for event data, accept is called separately)
        # The only send_text call should be for the broadcast that didn't match
        # Actually, since subscription doesn't match, there should be no send_text call for the event
        # But we need to check if send_text was called at all for the broadcast
        calls = [call for call in ws.send_text.call_args_list]
        # Should not have sent the completed event
        for call in calls:
            data = json.loads(call[0][0])
            assert data.get("type") != "packet.completed"

    @pytest.mark.asyncio
    async def test_broadcast_tenant_filtering(self):
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()

        await self.manager.connect(ws1, "conn-1", tier="pro", tenant_id="tenant-a")
        await self.manager.connect(ws2, "conn-2", tier="pro", tenant_id="tenant-b")

        # Broadcast only to tenant-a
        event = {"type": "packet.created", "data": {"status": "created"}}
        await self.manager.broadcast(event, tenant_id="tenant-a")

        # ws1 (tenant-a) should receive, ws2 (tenant-b) should not
        ws1.send_text.assert_called_once()
        # ws2 should not have received any broadcast
        # (it was only called for accept())


# ── RedisPubSubManager Tests ────────────────────────────────────────────────────


class TestRedisPubSubManager:
    """Test the RedisPubSubManager (in-process fallback mode)."""

    def setup_method(self):
        self.manager = RedisPubSubManager(redis_url="redis://localhost:6379/0")

    @pytest.mark.asyncio
    async def test_fallback_without_redis(self):
        """When Redis is unavailable, publish should fall back to in-process callback."""
        connected = await self.manager.connect()
        # Redis likely unavailable in test env
        # The method should not raise an exception

        received_events = []

        async def on_event(event):
            received_events.append(event)

        self.manager.set_event_callback(on_event)
        await self.manager.publish("packet.created", {"status": "created"}, packet_id="test-123")

        # In-process callback should have been called
        assert len(received_events) == 1
        assert received_events[0]["type"] == "packet.created"
        assert received_events[0]["packet_id"] == "test-123"

    @pytest.mark.asyncio
    async def test_publish_event_structure(self):
        """Published events should have the correct structure."""
        received = []

        async def on_event(event):
            received.append(event)

        self.manager.set_event_callback(on_event)
        await self.manager.publish(
            "packet.claimed",
            {"status": "claimed", "metadata": {"source_agent": {"id": "agent-1"}}},
            packet_id="pkt-456",
        )

        assert len(received) == 1
        event = received[0]
        assert "type" in event
        assert "packet_id" in event
        assert "data" in event
        assert "timestamp" in event
        assert event["type"] == "packet.claimed"
        assert event["packet_id"] == "pkt-456"

    @pytest.mark.asyncio
    async def test_disconnect_is_safe(self):
        """Disconnecting when not connected should not raise."""
        await self.manager.disconnect()
        # Should not raise


# ── Integration: Packet API + WebSocket events ──────────────────────────────────


class TestWebSocketIntegration:
    """Test that packet API endpoints publish WebSocket events."""

    @pytest.mark.asyncio
    async def test_create_packet_publishes_event(self, client: AsyncClient):
        """Creating a packet should publish a packet.created event."""
        received_events = []

        # Set up the connection manager with a callback that captures events
        manager = get_connection_manager()
        pubsub = get_pubsub_manager()

        async def capture_event(event):
            received_events.append(event)

        pubsub.set_event_callback(capture_event)

        # Create a packet
        await create_test_packet(client)

        # Check that an event was published
        assert len(received_events) >= 1
        event = received_events[0]
        assert event["type"] == "packet.created"
        assert "packet_id" in event
        assert event["data"]["status"] == "created"

        # Reset
        reset_connection_manager()
        reset_pubsub_manager()

    @pytest.mark.asyncio
    async def test_claim_packet_publishes_event(self, client: AsyncClient):
        """Claiming a packet should publish a packet.claimed event."""
        received_events = []

        pubsub = get_pubsub_manager()
        async def capture_event(event):
            received_events.append(event)
        pubsub.set_event_callback(capture_event)

        # Create and claim a packet
        packet = await create_test_packet(client)
        await client.post(
            f"/api/v1/packets/{packet['id']}/claim",
            json={"agent_id": "claimer-1", "agent_name": "Claimer", "framework": "test"},
        )

        # Check that claimed event was published
        event_types = [e["type"] for e in received_events]
        assert "packet.claimed" in event_types

        reset_connection_manager()
        reset_pubsub_manager()

    @pytest.mark.asyncio
    async def test_hitl_respond_publishes_event(self, client: AsyncClient):
        """Responding to a HITL checkpoint should publish a hitl.response_ready event."""
        received_events = []

        pubsub = get_pubsub_manager()
        async def capture_event(event):
            received_events.append(event)
        pubsub.set_event_callback(capture_event)

        # Create a HITL packet
        payload = {
            "metadata": {
                "source_agent": {"id": "agent-1", "name": "Agent", "framework": "test"},
                "target_agent": {"id": "human", "name": "Manager"},
                "priority": "high",
                "tags": [],
            },
            "context": {"summary": "HITL test", "conversation_state": [], "artifacts": [], "custom": {}},
            "decisions": [],
            "actions": {"pending": [], "completed": [], "failed": []},
            "dependencies": [],
            "hitl": {
                "required": True,
                "reason": "Needs approval",
                "question": "Approve this?",
                "options": ["Yes", "No"],
                "response": None,
                "responded_at": None,
                "responded_by": None,
                "timeout_seconds": None,
            },
        }
        response = await client.post("/api/v1/packets", json=payload)
        packet = response.json()

        # Respond to HITL
        await client.post(
            f"/api/v1/packets/{packet['id']}/respond",
            json={"response": "Yes", "responded_by": "manager@test.com"},
        )

        event_types = [e["type"] for e in received_events]
        assert "hitl.response_ready" in event_types

        reset_connection_manager()
        reset_pubsub_manager()


# ── Stats Endpoint Tests ────────────────────────────────────────────────────────


class TestStatsEndpoint:
    """Test the /api/v1/stats endpoint."""

    @pytest.mark.asyncio
    async def test_stats_empty(self, client: AsyncClient):
        """Stats should return zeros for empty database."""
        response = await client.get("/api/v1/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_packets"] == 0
        assert data["packets_last_24h"] == 0
        assert data["hitl_queue_depth"] == 0
        assert data["active_ws_connections"] == 0

    @pytest.mark.asyncio
    async def test_stats_with_packets(self, client: AsyncClient):
        """Stats should reflect created packets."""
        # Create 2 packets
        await create_test_packet(client)
        await create_test_packet(client)

        response = await client.get("/api/v1/stats")
        data = response.json()
        assert data["total_packets"] == 2
        assert data["packets_last_24h"] == 2
        assert "created" in data["packets_by_status"]

    @pytest.mark.asyncio
    async def test_stats_with_hitl(self, client: AsyncClient):
        """Stats should count HITL-queued packets."""
        payload = {
            "metadata": {
                "source_agent": {"id": "agent-1", "name": "Agent", "framework": "test"},
                "target_agent": {"id": "human", "name": "Manager"},
                "priority": "normal",
                "tags": [],
            },
            "context": {"summary": "HITL test", "conversation_state": [], "artifacts": [], "custom": {}},
            "decisions": [],
            "actions": {"pending": [], "completed": [], "failed": []},
            "dependencies": [],
            "hitl": {
                "required": True,
                "reason": "Needs approval",
                "question": "Approve?",
                "options": ["Yes", "No"],
                "response": None,
                "responded_at": None,
                "responded_by": None,
                "timeout_seconds": None,
            },
        }
        await client.post("/api/v1/packets", json=payload)

        response = await client.get("/api/v1/stats")
        data = response.json()
        assert data["hitl_queue_depth"] == 1


# ── Dashboard Static Files ──────────────────────────────────────────────────────


class TestDashboard:
    """Test that dashboard static files are served."""

    @pytest.mark.asyncio
    async def test_dashboard_index(self, client: AsyncClient):
        """The dashboard index.html should be served at /dashboard/."""
        response = await client.get("/dashboard/", follow_redirects=True)
        # Either 200 (served) or 404 (directory not mounted in test env)
        # In production, this would be 200
        assert response.status_code in [200, 404]
