"""Tests for HandoffRail SDK — Synchronous client.

All HTTP calls are mocked using ``respx`` so no real server is needed.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
import respx
from handoffrail.sdk.client import HandoffRailClient
from handoffrail.sdk.exceptions import (
    AuthenticationError,
    ConnectionError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from handoffrail.sdk.models import (
    AgentInfo,
    ChainHandoffRequest,
    Metadata,
    PacketContext,
    PacketCreate,
    PacketResponse,
    PacketStatus,
    PacketUpdate,
    TargetAgentInfo,
)

# ── Fixtures ────────────────────────────────────────────────────────────────────

BASE_URL = "http://testserver/api/v1"
API_KEY = "hr_test_key_12345678"


def _make_client() -> HandoffRailClient:
    return HandoffRailClient(base_url=BASE_URL, api_key=API_KEY, timeout=5.0, max_retries=1)


def _sample_packet_response(packet_id: str | None = None) -> dict:
    """Return a sample packet response dict matching the API schema."""
    pid = packet_id or str(uuid4())
    return {
        "id": pid,
        "version": "1.0.0",
        "parent_packet_id": None,
        "metadata": {
            "source_agent": {"id": "sales-01", "name": "SalesBot", "framework": "langchain"},
            "target_agent": {"id": "billing-01", "name": "BillingBot", "framework": "crewai"},
            "created_at": "2026-05-13T21:00:00Z",
            "claimed_at": None,
            "completed_at": None,
            "priority": "normal",
            "tags": ["test"],
        },
        "context": {
            "summary": "Customer wants to upgrade",
            "conversation_state": [
                {"role": "user", "content": "I want to upgrade"},
            ],
            "artifacts": [],
            "custom": {},
        },
        "decisions": [],
        "actions": {"pending": [], "completed": [], "failed": []},
        "dependencies": [],
        "hitl": None,
        "status": "created",
        "created_at": "2026-05-13T21:00:00Z",
        "updated_at": "2026-05-13T21:00:00Z",
    }


def _sample_create_payload() -> dict:
    """Return a valid packet creation payload dict."""
    return {
        "parent_packet_id": None,
        "metadata": {
            "source_agent": {"id": "sales-01", "name": "SalesBot", "framework": "langchain"},
            "target_agent": {"id": "billing-01", "name": "BillingBot", "framework": "crewai"},
            "priority": "normal",
            "tags": ["test"],
        },
        "context": {
            "summary": "Customer wants to upgrade",
            "conversation_state": [{"role": "user", "content": "I want to upgrade"}],
            "artifacts": [],
            "custom": {},
        },
        "decisions": [],
        "actions": {"pending": [], "completed": [], "failed": []},
        "dependencies": [],
        "hitl": None,
    }


# ── create_packet ──────────────────────────────────────────────────────────────


class TestCreatePacket:
    @respx.mock
    def test_create_packet_success(self):
        client = _make_client()
        response_data = _sample_packet_response()

        respx.post(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(201, json=response_data),
        )

        payload = PacketCreate.from_dict(_sample_create_payload())
        result = client.create_packet(payload)

        assert isinstance(result, PacketResponse)
        assert result.status == PacketStatus.created
        assert result.metadata.source_agent.id == "sales-01"
        assert result.context.summary == "Customer wants to upgrade"

    @respx.mock
    def test_create_packet_sends_api_key(self):
        client = _make_client()
        response_data = _sample_packet_response()

        route = respx.post(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(201, json=response_data),
        )

        payload = PacketCreate.from_dict(_sample_create_payload())
        client.create_packet(payload)

        assert route.calls[0].request.headers["X-API-Key"] == API_KEY

    @respx.mock
    def test_create_packet_validation_error(self):
        client = _make_client()

        respx.post(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(400, json={"detail": "Invalid payload", "field": "metadata"}),
        )

        payload = PacketCreate.from_dict(_sample_create_payload())
        with pytest.raises(ValidationError) as exc_info:
            client.create_packet(payload)
        assert exc_info.value.status_code == 400
        assert exc_info.value.field == "metadata"


# ── get_packet ──────────────────────────────────────────────────────────────────


class TestGetPacket:
    @respx.mock
    def test_get_packet_success(self):
        client = _make_client()
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)

        respx.get(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = client.get_packet(packet_id)
        assert str(result.id) == packet_id
        assert result.status == PacketStatus.created

    @respx.mock
    def test_get_packet_not_found(self):
        client = _make_client()
        packet_id = str(uuid4())

        respx.get(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(404, json={"detail": "Packet not found"}),
        )

        with pytest.raises(NotFoundError):
            client.get_packet(packet_id)


# ── list_packets ───────────────────────────────────────────────────────────────


class TestListPackets:
    @respx.mock
    def test_list_packets_success(self):
        client = _make_client()
        response_data = {
            "packets": [_sample_packet_response()],
            "total": 1,
            "limit": 50,
            "offset": 0,
        }

        respx.get(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = client.list_packets()
        assert result.total == 1
        assert len(result.packets) == 1

    @respx.mock
    def test_list_packets_with_filters(self):
        client = _make_client()
        response_data = {"packets": [], "total": 0, "limit": 10, "offset": 0}

        route = respx.get(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        client.list_packets(status="created", priority="high", limit=10, offset=0)
        request = route.calls[0].request
        assert "status=created" in str(request.url)
        assert "priority=high" in str(request.url)


# ── claim_packet ────────────────────────────────────────────────────────────────


class TestClaimPacket:
    @respx.mock
    def test_claim_packet_success(self):
        client = _make_client()
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "claimed"
        response_data["metadata"]["claimed_at"] = "2026-05-13T21:05:00Z"

        respx.post(f"{BASE_URL}/packets/{packet_id}/claim").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = client.claim_packet(packet_id, agent_id="billing-01", agent_name="BillingBot")
        assert result.status == PacketStatus.claimed

    @respx.mock
    def test_claim_packet_conflict(self):
        client = _make_client()
        packet_id = str(uuid4())

        respx.post(f"{BASE_URL}/packets/{packet_id}/claim").mock(
            return_value=httpx.Response(409, json={"detail": "Packet already claimed"}),
        )

        with pytest.raises(ValidationError) as exc_info:
            client.claim_packet(packet_id, agent_id="billing-01", agent_name="BillingBot")
        assert exc_info.value.status_code == 409


# ── update_packet ───────────────────────────────────────────────────────────────


class TestUpdatePacket:
    @respx.mock
    def test_update_packet_status(self):
        client = _make_client()
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "in_progress"

        respx.patch(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        update = PacketUpdate(status=PacketStatus.in_progress)
        result = client.update_packet(packet_id, update)
        assert result.status == PacketStatus.in_progress


# ── complete_packet ─────────────────────────────────────────────────────────────


class TestCompletePacket:
    @respx.mock
    def test_complete_packet(self):
        client = _make_client()
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "completed"
        response_data["metadata"]["completed_at"] = "2026-05-13T21:30:00Z"

        respx.patch(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = client.complete_packet(packet_id)
        assert result.status == PacketStatus.completed


# ── delete_packet ───────────────────────────────────────────────────────────────


class TestDeletePacket:
    @respx.mock
    def test_delete_packet_success(self):
        client = _make_client()
        packet_id = str(uuid4())

        respx.delete(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(204),
        )

        # Should not raise
        client.delete_packet(packet_id)

    @respx.mock
    def test_delete_packet_not_found(self):
        client = _make_client()
        packet_id = str(uuid4())

        respx.delete(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(404, json={"detail": "Packet not found"}),
        )

        with pytest.raises(NotFoundError):
            client.delete_packet(packet_id)


# ── respond_to_hitl ─────────────────────────────────────────────────────────────


class TestRespondToHITL:
    @respx.mock
    def test_respond_to_hitl(self):
        client = _make_client()
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "claimed"
        response_data["hitl"] = {
            "required": True,
            "reason": "Approval needed",
            "question": "Approve?",
            "response": "Approved",
            "responded_at": "2026-05-13T22:00:00Z",
            "responded_by": "manager@example.com",
        }

        respx.post(f"{BASE_URL}/packets/{packet_id}/respond").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = client.respond_to_hitl(
            packet_id, response="Approved", responded_by="manager@example.com"
        )
        assert result.status == PacketStatus.claimed
        assert result.hitl is not None
        assert result.hitl.response == "Approved"


# ── get_awaiting ─────────────────────────────────────────────────────────────────


class TestGetAwaiting:
    @respx.mock
    def test_get_awaiting(self):
        client = _make_client()
        response_data = {
            "packets": [_sample_packet_response()],
            "total": 1,
            "limit": 50,
            "offset": 0,
        }

        respx.get(f"{BASE_URL}/packets/awaiting").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = client.get_awaiting()
        assert result.total == 1


# ── get_history ──────────────────────────────────────────────────────────────────


class TestGetHistory:
    @respx.mock
    def test_get_history(self):
        client = _make_client()
        packet_id = str(uuid4())
        history_data = {
            "packet_id": packet_id,
            "events": [
                {
                    "id": "evt-1",
                    "packet_id": packet_id,
                    "event_type": "created",
                    "actor": "agent:sales-01",
                    "details": {},
                    "timestamp": "2026-05-13T21:00:00Z",
                }
            ],
        }

        respx.get(f"{BASE_URL}/packets/{packet_id}/history").mock(
            return_value=httpx.Response(200, json=history_data),
        )

        result = client.get_history(packet_id)
        assert result.packet_id == packet_id
        assert len(result.events) == 1
        assert result.events[0].event_type == "created"


# ── chain_handoff ───────────────────────────────────────────────────────────────


class TestChainHandoff:
    @respx.mock
    def test_chain_handoff(self):
        client = _make_client()
        parent_id = str(uuid4())
        child_id = str(uuid4())
        response_data = _sample_packet_response(child_id)
        response_data["parent_packet_id"] = parent_id

        respx.post(f"{BASE_URL}/packets/{parent_id}/chain").mock(
            return_value=httpx.Response(201, json=response_data),
        )

        chain_request = ChainHandoffRequest(
            metadata=Metadata(
                source_agent=AgentInfo(id="billing-01", name="BillingBot"),
                target_agent=TargetAgentInfo(id="followup-01", name="FollowUpBot"),
            ),
            context=PacketContext(summary="Follow-up work needed"),
        )
        result = client.chain_handoff(parent_id, chain_request)
        assert str(result.parent_packet_id) == parent_id
        # parent_packet_id is UUID, compare as string


# ── Webhook CRUD ────────────────────────────────────────────────────────────────


class TestWebhooks:
    @respx.mock
    def test_register_webhook(self):
        client = _make_client()
        webhook_data = {
            "id": "wh-1",
            "url": "https://example.com/webhook",
            "events": ["packet.created", "packet.completed"],
            "tenant_id": "tenant-1",
            "active": True,
            "created_at": "2026-05-13T21:00:00Z",
        }

        respx.post(f"{BASE_URL}/hooks").mock(
            return_value=httpx.Response(201, json=webhook_data),
        )

        result = client.register_webhook(
            url="https://example.com/webhook",
            events=["packet.created", "packet.completed"],
            secret="a" * 16,
        )
        assert result.id == "wh-1"
        assert result.active is True

    @respx.mock
    def test_list_webhooks(self):
        client = _make_client()
        webhook_list = [
            {
                "id": "wh-1",
                "url": "https://example.com/webhook",
                "events": ["packet.created"],
                "tenant_id": "tenant-1",
                "active": True,
                "created_at": "2026-05-13T21:00:00Z",
            }
        ]

        respx.get(f"{BASE_URL}/hooks").mock(
            return_value=httpx.Response(200, json=webhook_list),
        )

        result = client.list_webhooks()
        assert len(result) == 1
        assert result[0].id == "wh-1"

    @respx.mock
    def test_delete_webhook(self):
        client = _make_client()
        webhook_id = "wh-1"

        respx.delete(f"{BASE_URL}/hooks/{webhook_id}").mock(
            return_value=httpx.Response(204),
        )

        # Should not raise
        client.delete_webhook(webhook_id)


# ── Error handling ──────────────────────────────────────────────────────────────


class TestErrorHandling:
    @respx.mock
    def test_authentication_error(self):
        client = _make_client()

        respx.get(f"{BASE_URL}/packets/test-id").mock(
            return_value=httpx.Response(401, json={"detail": "Invalid API key"}),
        )

        with pytest.raises(AuthenticationError) as exc_info:
            client.get_packet("test-id")
        assert exc_info.value.status_code == 401

    @respx.mock
    def test_rate_limit_error(self):
        client = _make_client()

        respx.get(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(429, json={"detail": "Rate limit exceeded"}, headers={"Retry-After": "60"}),
        )

        with pytest.raises(RateLimitError) as exc_info:
            client.list_packets()
        assert exc_info.value.retry_after == 60

    @respx.mock
    def test_server_error(self):
        client = _make_client()

        respx.get(f"{BASE_URL}/packets/test-id").mock(
            return_value=httpx.Response(500, json={"detail": "Internal server error"}),
        )

        with pytest.raises(ServerError) as exc_info:
            client.get_packet("test-id")
        assert exc_info.value.status_code == 500

    @respx.mock
    def test_connection_error(self):
        client = _make_client()

        # Simulate connection refused
        respx.get(f"{BASE_URL}/packets").mock(side_effect=httpx.ConnectError("Connection refused"))

        with pytest.raises(ConnectionError):
            client.list_packets()

    @respx.mock
    def test_gone_error(self):
        client = _make_client()
        packet_id = str(uuid4())

        respx.get(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(410, json={"detail": "Packet expired"}),
        )

        with pytest.raises(NotFoundError) as exc_info:
            client.get_packet(packet_id)
        assert exc_info.value.status_code == 410


# ── Context manager ────────────────────────────────────────────────────────────


class TestContextManager:
    @respx.mock
    def test_context_manager(self):
        with HandoffRailClient(base_url=BASE_URL, api_key=API_KEY) as client:
            assert isinstance(client, HandoffRailClient)
        # Client should be closed after exiting context

    @respx.mock
    def test_retry_on_connection_error(self):
        client = _make_client()  # max_retries=1 in test helper

        # First call fails, second succeeds
        # Use a valid UUID for the retry test
        valid_id = str(uuid4())
        route = respx.get(f"{BASE_URL}/packets/{valid_id}").mock(
            side_effect=[
                httpx.ConnectError("Connection refused"),
                httpx.Response(200, json=_sample_packet_response(valid_id)),
            ]
        )

        # With max_retries=1, should get 2 attempts total
        result = client.get_packet(valid_id)
        assert str(result.id) == valid_id
        assert route.call_count == 2
