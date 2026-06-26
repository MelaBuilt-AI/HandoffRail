"""HandoffRail API Server — Integration tests for Week 3 features.

Tests cover: listing with filters, pagination, awaiting endpoint,
event history, chain creation, webhook CRUD, webhook delivery (mocked),
rate limiting.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

# Add server dir to Python path so `app` module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from app.database import async_session
from app.middleware.auth import generate_api_key
from app.models.db import ApiKey


def _minimal_payload(**overrides) -> dict:
    """Return a minimal valid packet creation payload with optional overrides."""
    payload = {
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
    payload.update(overrides)
    return payload


def _hitl_payload(**overrides) -> dict:
    """Return a payload with a HITL checkpoint."""
    payload = _minimal_payload()
    payload["hitl"] = {
        "required": True,
        "reason": "Needs approval",
        "question": "Proceed?",
        "options": ["Yes", "No"],
    }
    payload.update(overrides)
    return payload


async def _create_packet(client: AsyncClient, payload: dict | None = None) -> dict:
    """Helper to create a packet and return its JSON."""
    resp = await client.post("/api/v1/packets", json=payload or _minimal_payload())
    assert resp.status_code == 201, f"Create failed: {resp.text}"
    return resp.json()


async def _create_api_key(client: AsyncClient) -> tuple[str, str]:
    """Helper to create an API key directly in the database. Returns (key_id, plain_key)."""
    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]

    async with async_session() as session:
        db_key = ApiKey(
            id=str(uuid4()),
            name="test-key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            tenant_id="default",
            tier="pro",
        )
        session.add(db_key)
        await session.commit()
        await session.refresh(db_key)
        key_id = db_key.id

    return key_id, plain_key


# ════════════════════════════════════════════════════════════════════════════════
# LIST WITH FILTERS
# ════════════════════════════════════════════════════════════════════════════════


class TestListPackets:
    """Test GET /packets with filtering and pagination."""

    @pytest.mark.asyncio
    async def test_list_packets_empty(self, client: AsyncClient):
        """Listing packets when none exist returns empty list."""
        resp = await client.get("/api/v1/packets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["packets"] == []
        assert data["total"] == 0
        assert data["limit"] == 50
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_list_packets_returns_created(self, client: AsyncClient):
        """Listing packets returns created packets."""
        await _create_packet(client)
        await _create_packet(client)

        resp = await client.get("/api/v1/packets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["packets"]) == 2
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_list_packets_filter_by_status(self, client: AsyncClient):
        """Filter packets by status."""
        # Create one normal packet (status=created) and one HITL packet (status=awaiting_human)
        await _create_packet(client)
        await _create_packet(client, _hitl_payload())

        resp = await client.get("/api/v1/packets", params={"status": "created"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["packets"][0]["status"] == "created"

    @pytest.mark.asyncio
    async def test_list_packets_filter_by_multiple_statuses(self, client: AsyncClient):
        """Filter packets by multiple comma-separated statuses."""
        await _create_packet(client)
        await _create_packet(client, _hitl_payload())

        resp = await client.get("/api/v1/packets", params={"status": "created,awaiting_human"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_list_packets_filter_by_source_agent(self, client: AsyncClient):
        """Filter packets by source agent ID."""
        await _create_packet(client)
        payload = _minimal_payload()
        payload["metadata"]["source_agent"]["id"] = "special-agent"
        await _create_packet(client, payload)

        resp = await client.get("/api/v1/packets", params={"source_agent": "special-agent"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["packets"][0]["metadata"]["source_agent"]["id"] == "special-agent"

    @pytest.mark.asyncio
    async def test_list_packets_filter_by_target_agent(self, client: AsyncClient):
        """Filter packets by target agent ID."""
        await _create_packet(client)
        payload = _minimal_payload()
        payload["metadata"]["target_agent"]["id"] = "billing-01"
        await _create_packet(client, payload)

        resp = await client.get("/api/v1/packets", params={"target_agent": "billing-01"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_list_packets_filter_by_priority(self, client: AsyncClient):
        """Filter packets by priority."""
        await _create_packet(client)
        payload = _minimal_payload()
        payload["metadata"]["priority"] = "high"
        await _create_packet(client, payload)

        resp = await client.get("/api/v1/packets", params={"priority": "high"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["packets"][0]["metadata"]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_list_packets_filter_by_tags(self, client: AsyncClient):
        """Filter packets by tags (all must match)."""
        payload = _minimal_payload()
        payload["metadata"]["tags"] = ["urgent", "billing"]
        await _create_packet(client, payload)

        # Match both tags
        resp = await client.get("/api/v1/packets", params={"tags": "urgent,billing"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

        # Only one tag — should still match since packet has both
        resp = await client.get("/api/v1/packets", params={"tags": "urgent"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        # Non-existent tag
        resp = await client.get("/api/v1/packets", params={"tags": "nonexistent"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_list_packets_pagination(self, client: AsyncClient):
        """Test pagination with limit and offset."""
        for _ in range(5):
            await _create_packet(client)

        # Get first 2
        resp = await client.get("/api/v1/packets", params={"limit": 2, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["packets"]) == 2
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 0

        # Get next 2
        resp = await client.get("/api/v1/packets", params={"limit": 2, "offset": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["packets"]) == 2
        assert data["offset"] == 2

        # Get remaining 1
        resp = await client.get("/api/v1/packets", params={"limit": 2, "offset": 4})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["packets"]) == 1

    @pytest.mark.asyncio
    async def test_list_packets_date_filter(self, client: AsyncClient):
        """Filter packets by created_after and created_before."""
        await _create_packet(client)

        # Use a far-future date to get no results
        resp = await client.get("/api/v1/packets", params={"created_after": "2099-01-01T00:00:00Z"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

        # Use a far-past date to get all results
        resp = await client.get("/api/v1/packets", params={"created_after": "2000-01-01T00:00:00Z"})
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1


# ════════════════════════════════════════════════════════════════════════════════
# AWAITING HUMAN ENDPOINT
# ════════════════════════════════════════════════════════════════════════════════


class TestAwaitingHuman:
    """Test GET /packets/awaiting convenience endpoint."""

    @pytest.mark.asyncio
    async def test_list_awaiting_empty(self, client: AsyncClient):
        """No awaiting packets returns empty list."""
        resp = await client.get("/api/v1/packets/awaiting")
        assert resp.status_code == 200
        data = resp.json()
        assert data["packets"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_awaiting_returns_hitl_packets(self, client: AsyncClient):
        """Awaiting endpoint returns only awaiting_human packets."""
        # Create one normal and one HITL packet
        await _create_packet(client)
        await _create_packet(client, _hitl_payload())

        resp = await client.get("/api/v1/packets/awaiting")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["packets"][0]["status"] == "awaiting_human"

    @pytest.mark.asyncio
    async def test_list_awaiting_pagination(self, client: AsyncClient):
        """Awaiting endpoint supports pagination."""
        for _ in range(3):
            await _create_packet(client, _hitl_payload())

        resp = await client.get("/api/v1/packets/awaiting", params={"limit": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["packets"]) == 2
        assert data["total"] == 3

    @pytest.mark.asyncio
    async def test_awaiting_excludes_other_statuses(self, client: AsyncClient):
        """Packets in other statuses don't appear in awaiting list."""
        packet = await _create_packet(client)
        # Claim the packet
        await client.post(f"/api/v1/packets/{packet['id']}/claim", json={"agent_id": "a1", "agent_name": "A1"})

        resp = await client.get("/api/v1/packets/awaiting")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ════════════════════════════════════════════════════════════════════════════════
# EVENT HISTORY
# ════════════════════════════════════════════════════════════════════════════════


class TestEventHistory:
    """Test GET /packets/{id}/history endpoint."""

    @pytest.mark.asyncio
    async def test_history_new_packet(self, client: AsyncClient):
        """New packet has a 'created' event in history."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        resp = await client.get(f"/api/v1/packets/{packet_id}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["packet_id"] == packet_id
        assert len(data["events"]) == 1
        assert data["events"][0]["event_type"] == "created"
        assert data["events"][0]["actor"] == "agent:test-source"

    @pytest.mark.asyncio
    async def test_history_after_claim(self, client: AsyncClient):
        """Claiming a packet adds a 'claimed' event."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        await client.post(f"/api/v1/packets/{packet_id}/claim", json={"agent_id": "billing-01", "agent_name": "BillingBot"})

        resp = await client.get(f"/api/v1/packets/{packet_id}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 2
        event_types = [e["event_type"] for e in data["events"]]
        assert "created" in event_types
        assert "claimed" in event_types

    @pytest.mark.asyncio
    async def test_history_after_full_lifecycle(self, client: AsyncClient):
        """Full lifecycle creates a complete audit trail."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        # Claim
        await client.post(f"/api/v1/packets/{packet_id}/claim", json={"agent_id": "a1", "agent_name": "A1"})
        # Progress
        await client.patch(f"/api/v1/packets/{packet_id}", json={"status": "in_progress"})
        # Complete
        await client.patch(f"/api/v1/packets/{packet_id}", json={"status": "completed"})

        resp = await client.get(f"/api/v1/packets/{packet_id}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 4
        event_types = [e["event_type"] for e in data["events"]]
        assert event_types == ["created", "claimed", "in_progress", "completed"]

    @pytest.mark.asyncio
    async def test_history_not_found(self, client: AsyncClient):
        """History for non-existent packet returns 404."""
        resp = await client.get("/api/v1/packets/00000000-0000-0000-0000-000000000000/history")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_hitl_respond_creates_event(self, client: AsyncClient):
        """HITL response creates a hitl_responded event."""
        packet = await _create_packet(client, _hitl_payload())
        packet_id = packet["id"]

        await client.post(
            f"/api/v1/packets/{packet_id}/respond",
            json={"response": "Approved", "responded_by": "manager@test.com"},
        )

        resp = await client.get(f"/api/v1/packets/{packet_id}/history")
        assert resp.status_code == 200
        data = resp.json()
        event_types = [e["event_type"] for e in data["events"]]
        assert "hitl_responded" in event_types

    @pytest.mark.asyncio
    async def test_soft_delete_creates_event(self, client: AsyncClient):
        """Soft deleting a packet creates an expired event."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        await client.delete(f"/api/v1/packets/{packet_id}")

        resp = await client.get(f"/api/v1/packets/{packet_id}/history")
        assert resp.status_code == 200
        data = resp.json()
        event_types = [e["event_type"] for e in data["events"]]
        assert "expired" in event_types


# ════════════════════════════════════════════════════════════════════════════════
# CHAIN CREATION
# ════════════════════════════════════════════════════════════════════════════════


class TestChainPacket:
    """Test POST /packets/{id}/chain endpoint."""

    @pytest.mark.asyncio
    async def test_chain_creates_follow_up(self, client: AsyncClient):
        """Creating a chained packet links it to the parent."""
        parent = await _create_packet(client)
        parent_id = parent["id"]

        chain_payload = {
            "metadata": {
                "source_agent": {"id": "agent-2", "name": "FollowUpBot", "framework": "crewai"},
                "target_agent": {"id": "agent-3", "name": "NextBot"},
                "priority": "high",
                "tags": ["follow-up"],
            },
            "context": {
                "summary": "Follow-up from previous agent",
                "conversation_state": [
                    {"role": "agent", "content": "Handing off to next agent"},
                ],
            },
            "decisions": [],
            "actions": {"pending": [], "completed": [], "failed": []},
            "dependencies": [],
        }

        resp = await client.post(f"/api/v1/packets/{parent_id}/chain", json=chain_payload)
        assert resp.status_code == 201

        data = resp.json()
        assert data["parent_packet_id"] == parent_id
        assert data["status"] == "created"
        assert data["metadata"]["source_agent"]["id"] == "agent-2"

    @pytest.mark.asyncio
    async def test_chain_with_hitl(self, client: AsyncClient):
        """Chained packet with HITL has awaiting_human status."""
        parent = await _create_packet(client)
        parent_id = parent["id"]

        chain_payload = {
            "metadata": {
                "source_agent": {"id": "agent-2", "name": "FollowUpBot"},
                "target_agent": {"id": "human", "name": "Manager"},
                "priority": "critical",
                "tags": [],
            },
            "context": {
                "summary": "Needs human approval",
                "conversation_state": [],
            },
            "decisions": [],
            "actions": {"pending": [], "completed": [], "failed": []},
            "dependencies": [],
            "hitl": {
                "required": True,
                "reason": "High-value transaction needs approval",
                "question": "Approve this transaction?",
            },
        }

        resp = await client.post(f"/api/v1/packets/{parent_id}/chain", json=chain_payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "awaiting_human"
        assert data["parent_packet_id"] == parent_id

    @pytest.mark.asyncio
    async def test_chain_merges_conversation_state(self, client: AsyncClient):
        """Chained packet inherits parent's conversation state."""
        parent = await _create_packet(client)
        parent_id = parent["id"]

        chain_payload = {
            "metadata": {
                "source_agent": {"id": "agent-2", "name": "FollowUpBot"},
                "target_agent": {"id": "agent-3", "name": "NextBot"},
                "priority": "normal",
                "tags": [],
            },
            "context": {
                "summary": "Continuing from parent",
                "conversation_state": [
                    {"role": "agent", "content": "New message from follow-up"},
                ],
            },
            "decisions": [],
            "actions": {"pending": [], "completed": [], "failed": []},
            "dependencies": [],
        }

        resp = await client.post(f"/api/v1/packets/{parent_id}/chain", json=chain_payload)
        assert resp.status_code == 201
        data = resp.json()

        # Should have both parent's conversation and the new one
        conv = data["context"]["conversation_state"]
        assert len(conv) >= 2  # Parent's + new one

    @pytest.mark.asyncio
    async def test_chain_creates_events_on_both_packets(self, client: AsyncClient):
        """Chain creation logs events on both parent and child."""
        parent = await _create_packet(client)
        parent_id = parent["id"]

        chain_payload = {
            "metadata": {
                "source_agent": {"id": "agent-2", "name": "FollowUpBot"},
                "target_agent": {"id": "agent-3", "name": "NextBot"},
                "priority": "normal",
                "tags": [],
            },
            "context": {"summary": "Chain", "conversation_state": []},
            "decisions": [],
            "actions": {"pending": [], "completed": [], "failed": []},
            "dependencies": [],
        }

        resp = await client.post(f"/api/v1/packets/{parent_id}/chain", json=chain_payload)
        assert resp.status_code == 201
        child_id = resp.json()["id"]

        # Check parent history has a "chained" event
        parent_history = await client.get(f"/api/v1/packets/{parent_id}/history")
        assert parent_history.status_code == 200
        parent_events = [e["event_type"] for e in parent_history.json()["events"]]
        assert "chained" in parent_events

        # Check child history has a "created" event with chain details
        child_history = await client.get(f"/api/v1/packets/{child_id}/history")
        assert child_history.status_code == 200
        child_events = child_history.json()["events"]
        created_event = [e for e in child_events if e["event_type"] == "created"][0]
        assert created_event["details"]["parent_packet_id"] == parent_id
        assert created_event["details"]["chain"] is True

    @pytest.mark.asyncio
    async def test_chain_parent_not_found(self, client: AsyncClient):
        """Chaining from non-existent parent returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        chain_payload = {
            "metadata": {
                "source_agent": {"id": "agent-2", "name": "FollowUpBot"},
                "target_agent": {"id": "agent-3", "name": "NextBot"},
                "priority": "normal",
                "tags": [],
            },
            "context": {"summary": "Chain", "conversation_state": []},
            "decisions": [],
            "actions": {"pending": [], "completed": [], "failed": []},
            "dependencies": [],
        }

        resp = await client.post(f"/api/v1/packets/{fake_id}/chain", json=chain_payload)
        assert resp.status_code == 404


# ════════════════════════════════════════════════════════════════════════════════
# WEBHOOK CRUD
# ════════════════════════════════════════════════════════════════════════════════


class TestWebhookCrud:
    """Test POST/GET/DELETE /hooks endpoints."""

    @pytest.mark.asyncio
    async def test_create_webhook(self, client: AsyncClient):
        """POST /hooks creates a new webhook registration."""
        _, api_key = await _create_api_key(client)

        resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["packet.created", "packet.completed"],
                "secret": "my_super_secret_key_16ch",
            },
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["url"] == "https://example.com/webhook"
        assert "packet.created" in data["events"]
        assert data["active"] is True

    @pytest.mark.asyncio
    async def test_create_webhook_invalid_url(self, client: AsyncClient):
        """POST /hooks with invalid URL returns 422."""
        _, api_key = await _create_api_key(client)

        resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "not-a-url",
                "events": ["packet.created"],
                "secret": "my_super_secret_key_16ch",
            },
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_webhook_invalid_event(self, client: AsyncClient):
        """POST /hooks with invalid event type returns 422."""
        _, api_key = await _create_api_key(client)

        resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["packet.nonexistent"],
                "secret": "my_super_secret_key_16ch",
            },
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_webhook_short_secret(self, client: AsyncClient):
        """POST /hooks with secret shorter than 16 chars returns 422."""
        _, api_key = await _create_api_key(client)

        resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["packet.created"],
                "secret": "short",
            },
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_webhooks(self, client: AsyncClient):
        """GET /hooks lists webhooks for the authenticated tenant."""
        _, api_key = await _create_api_key(client)

        # Create two webhooks
        for i in range(2):
            await client.post(
                "/api/v1/hooks",
                json={
                    "url": f"https://example.com/webhook{i}",
                    "events": ["packet.created"],
                    "secret": f"secret_key_at_least_16_chars_{i}",
                },
                headers={"X-API-Key": api_key},
            )

        resp = await client.get("/api/v1/hooks", headers={"X-API-Key": api_key})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

    @pytest.mark.asyncio
    async def test_list_webhooks_no_auth(self, client: AsyncClient):
        """GET /hooks without auth returns 401."""
        resp = await client.get("/api/v1/hooks")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_webhook(self, client: AsyncClient):
        """DELETE /hooks/{id} deactivates a webhook."""
        _, api_key = await _create_api_key(client)

        create_resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["packet.created"],
                "secret": "my_super_secret_key_16ch",
            },
            headers={"X-API-Key": api_key},
        )
        assert create_resp.status_code == 201
        webhook_id = create_resp.json()["id"]

        delete_resp = await client.delete(f"/api/v1/hooks/{webhook_id}", headers={"X-API-Key": api_key})
        assert delete_resp.status_code == 204

        # Verify webhook is inactive
        list_resp = await client.get("/api/v1/hooks", headers={"X-API-Key": api_key})
        webhooks = list_resp.json()
        deactivated = [w for w in webhooks if w["id"] == webhook_id]
        assert len(deactivated) == 1
        assert deactivated[0]["active"] is False

    @pytest.mark.asyncio
    async def test_delete_webhook_already_inactive(self, client: AsyncClient):
        """Deleting an already inactive webhook returns 409."""
        _, api_key = await _create_api_key(client)

        create_resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["packet.created"],
                "secret": "my_super_secret_key_16ch",
            },
            headers={"X-API-Key": api_key},
        )
        webhook_id = create_resp.json()["id"]

        # First delete
        await client.delete(f"/api/v1/hooks/{webhook_id}", headers={"X-API-Key": api_key})

        # Second delete fails
        resp = await client.delete(f"/api/v1/hooks/{webhook_id}", headers={"X-API-Key": api_key})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_webhook_not_found(self, client: AsyncClient):
        """Deleting non-existent webhook returns 404."""
        _, api_key = await _create_api_key(client)

        resp = await client.delete(
            "/api/v1/hooks/00000000-0000-0000-0000-000000000000",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 404


# ════════════════════════════════════════════════════════════════════════════════
# WEBHOOK DELIVERY (MOCKED)
# ════════════════════════════════════════════════════════════════════════════════


class TestWebhookDelivery:
    """Test webhook payload signing and delivery logic."""

    def test_sign_payload(self):
        """HMAC-SHA256 signing produces consistent signatures."""
        from app.services.webhook import sign_payload

        payload = '{"event":"packet.created","packet_id":"abc123"}'
        secret = "my_super_secret_key_16ch"

        sig1 = sign_payload(payload, secret)
        sig2 = sign_payload(payload, secret)

        # Same payload + secret → same signature
        assert sig1 == sig2
        # Different secret → different signature
        different_sig = sign_payload(payload, "different_secret_16_ch")
        assert sig1 != different_sig

    def test_sign_payload_format(self):
        """HMAC signature is a 64-character hex string."""
        from app.services.webhook import sign_payload

        payload = '{"test": true}'
        secret = "my_super_secret_key_16ch"
        sig = sign_payload(payload, secret)
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_build_webhook_payload(self):
        """Webhook payload includes required fields."""
        from app.services.webhook import build_webhook_payload
        from unittest.mock import MagicMock

        packet = MagicMock()
        packet.id = "test-packet-id"
        packet.status = "created"
        packet.get_metadata.return_value = {"source_agent": {"id": "agent-1"}}

        payload = build_webhook_payload("packet.created", packet)

        assert payload["event"] == "packet.created"
        assert payload["packet_id"] == "test-packet-id"
        assert payload["status"] == "created"
        assert "timestamp" in payload
        assert payload["metadata"]["source_agent"]["id"] == "agent-1"

    def test_build_webhook_payload_with_details(self):
        """Webhook payload includes extra details when provided."""
        from app.services.webhook import build_webhook_payload
        from unittest.mock import MagicMock

        packet = MagicMock()
        packet.id = "test-id"
        packet.status = "claimed"
        packet.get_metadata.return_value = {}

        payload = build_webhook_payload("packet.claimed", packet, {"agent_name": "Bot"})

        assert payload["details"]["agent_name"] == "Bot"

    @pytest.mark.asyncio
    async def test_status_to_events_mapping(self):
        """Status transitions map to correct webhook event types."""
        from app.services.webhook import STATUS_TO_EVENTS

        assert STATUS_TO_EVENTS["created"] == "packet.created"
        assert STATUS_TO_EVENTS["claimed"] == "packet.claimed"
        assert STATUS_TO_EVENTS["completed"] == "packet.completed"
        assert STATUS_TO_EVENTS["awaiting_human"] == "packet.awaiting_human"


# ════════════════════════════════════════════════════════════════════════════════
# RATE LIMITING
# ════════════════════════════════════════════════════════════════════════════════


class TestRateLimiting:
    """Test rate limiting middleware and headers."""

    @pytest.mark.asyncio
    async def test_rate_limit_headers_present(self, client: AsyncClient):
        """Responses include X-RateLimit-* headers."""
        resp = await client.get("/api/v1/packets")
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers
        assert "x-ratelimit-reset" in resp.headers
        assert "x-ratelimit-tier" in resp.headers

    @pytest.mark.asyncio
    async def test_rate_limit_headers_values(self, client: AsyncClient):
        """Rate limit headers reflect the configured tier limits."""
        # Test app uses generous limits (100000 for free tier)
        resp = await client.get("/api/v1/packets")
        assert resp.headers["x-ratelimit-tier"] == "free"
        # Should be generous for tests
        assert int(resp.headers["x-ratelimit-limit"]) > 100

    @pytest.mark.asyncio
    async def test_rate_limit_exempt_paths(self, client: AsyncClient):
        """Health check endpoint is exempt from rate limiting."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        # Health endpoint should NOT have rate limit headers
        assert "x-ratelimit-limit" not in resp.headers

    @pytest.mark.asyncio
    async def test_rate_limit_with_api_key(self, client: AsyncClient):
        """Authenticated requests include rate limit headers."""
        _, api_key = await _create_api_key(client)

        resp = await client.get("/api/v1/keys", headers={"X-API-Key": api_key})
        assert resp.status_code == 200
        # Rate limit headers should be present
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers
        assert "x-ratelimit-tier" in resp.headers

    @pytest.mark.asyncio
    async def test_rate_limit_remaining_decreases(self, client: AsyncClient):
        """X-RateLimit-Remaining decreases with each request."""
        resp1 = await client.get("/api/v1/packets")
        remaining1 = int(resp1.headers["x-ratelimit-remaining"])

        resp2 = await client.get("/api/v1/packets")
        remaining2 = int(resp2.headers["x-ratelimit-remaining"])

        assert remaining2 == remaining1 - 1

    @pytest.mark.asyncio
    async def test_tier_limits_configuration(self):
        """Tier limits are correctly configured."""
        from app.middleware.rate_limit import TIER_LIMITS

        assert TIER_LIMITS["free"] == 100
        assert TIER_LIMITS["pro"] == 1000
        assert TIER_LIMITS["business"] == 10000


# ════════════════════════════════════════════════════════════════════════════════
# STRUCTURED LOGGING
# ════════════════════════════════════════════════════════════════════════════════


class TestStructuredLogging:
    """Verify that structlog is configured and produces structured output."""

    def test_structlog_import(self):
        """structlog is importable and configured."""
        import structlog

        logger = structlog.get_logger()
        assert logger is not None

    def test_structlog_bind(self):
        """structlog supports binding context variables."""
        import structlog

        logger = structlog.get_logger().bind(packet_id="test-123")
        assert logger is not None

    @pytest.mark.asyncio
    async def test_create_packet_logs_structured(self, client: AsyncClient):
        """Creating a packet produces structured log output (no crash)."""
        # This test verifies that the structlog logging calls don't crash
        # The actual log output goes to stderr during tests
        resp = await client.post("/api/v1/packets", json=_minimal_payload())
        assert resp.status_code == 201
