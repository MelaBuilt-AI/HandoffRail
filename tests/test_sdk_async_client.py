"""Tests for HandoffRail SDK — Async client.

All HTTP calls are mocked using ``respx`` so no real server is needed.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from handoffrail.sdk.async_client import AsyncHandoffRailClient
from handoffrail.sdk.exceptions import (
    AuthenticationError,
    ConnectionError,
    NotFoundError,
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

BASE_URL = "http://testserver/api/v1"
API_KEY = "hr_test_key_async_1234"


def _make_client() -> AsyncHandoffRailClient:
    return AsyncHandoffRailClient(base_url=BASE_URL, api_key=API_KEY, timeout=5.0, max_retries=1)


def _sample_packet_response(packet_id: str | None = None) -> dict:
    from uuid import uuid4
    pid = packet_id or str(uuid4())
    return {
        "id": pid,
        "version": "1.0.0",
        "parent_packet_id": None,
        "metadata": {
            "source_agent": {"id": "sales-01", "name": "SalesBot", "framework": "langchain"},
            "target_agent": {"id": "billing-01", "name": "BillingBot"},
            "created_at": "2026-05-13T21:00:00Z",
            "claimed_at": None,
            "completed_at": None,
            "priority": "normal",
            "tags": [],
        },
        "context": {
            "summary": "Test packet",
            "conversation_state": [],
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
    return {
        "parent_packet_id": None,
        "metadata": {
            "source_agent": {"id": "sales-01", "name": "SalesBot", "framework": "langchain"},
            "target_agent": {"id": "billing-01", "name": "BillingBot"},
            "priority": "normal",
            "tags": [],
        },
        "context": {"summary": "Test packet", "conversation_state": [], "artifacts": [], "custom": {}},
        "decisions": [],
        "actions": {"pending": [], "completed": [], "failed": []},
        "dependencies": [],
        "hitl": None,
    }


# ── create_packet ──────────────────────────────────────────────────────────────


class TestAsyncCreatePacket:
    @respx.mock
    @pytest.mark.asyncio
    async def test_create_packet(self):
        async with _make_client() as client:
            response_data = _sample_packet_response()
            respx.post(f"{BASE_URL}/packets").mock(
                return_value=httpx.Response(201, json=response_data),
            )

            payload = PacketCreate.from_dict(_sample_create_payload())
            result = await client.create_packet(payload)

            assert isinstance(result, PacketResponse)
            assert result.status == PacketStatus.created

    @respx.mock
    @pytest.mark.asyncio
    async def test_create_packet_validation_error(self):
        async with _make_client() as client:
            respx.post(f"{BASE_URL}/packets").mock(
                return_value=httpx.Response(400, json={"detail": "Bad request"}),
            )

            payload = PacketCreate.from_dict(_sample_create_payload())
            with pytest.raises(ValidationError):
                await client.create_packet(payload)


# ── get_packet ──────────────────────────────────────────────────────────────────


class TestAsyncGetPacket:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_packet(self):
        from uuid import uuid4
        async with _make_client() as client:
            packet_id = str(uuid4())
            respx.get(f"{BASE_URL}/packets/{packet_id}").mock(
                return_value=httpx.Response(200, json=_sample_packet_response(packet_id)),
            )

            result = await client.get_packet(packet_id)
            assert str(result.id) == packet_id

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_packet_not_found(self):
        from uuid import uuid4
        async with _make_client() as client:
            packet_id = str(uuid4())
            respx.get(f"{BASE_URL}/packets/{packet_id}").mock(
                return_value=httpx.Response(404, json={"detail": "Not found"}),
            )

            with pytest.raises(NotFoundError):
                await client.get_packet(packet_id)


# ── list_packets ───────────────────────────────────────────────────────────────


class TestAsyncListPackets:
    @respx.mock
    @pytest.mark.asyncio
    async def test_list_packets(self):
        async with _make_client() as client:
            respx.get(f"{BASE_URL}/packets").mock(
                return_value=httpx.Response(
                    200, json={"packets": [_sample_packet_response()], "total": 1, "limit": 50, "offset": 0}
                ),
            )

            result = await client.list_packets()
            assert result.total == 1


# ── claim_packet ────────────────────────────────────────────────────────────────


class TestAsyncClaimPacket:
    @respx.mock
    @pytest.mark.asyncio
    async def test_claim_packet(self):
        from uuid import uuid4
        async with _make_client() as client:
            packet_id = str(uuid4())
            response_data = _sample_packet_response(packet_id)
            response_data["status"] = "claimed"
            response_data["metadata"]["claimed_at"] = "2026-05-13T21:05:00Z"

            respx.post(f"{BASE_URL}/packets/{packet_id}/claim").mock(
                return_value=httpx.Response(200, json=response_data),
            )

            result = await client.claim_packet(packet_id, agent_id="billing-01", agent_name="BillingBot")
            assert result.status == PacketStatus.claimed


# ── update_packet ───────────────────────────────────────────────────────────────


class TestAsyncUpdatePacket:
    @respx.mock
    @pytest.mark.asyncio
    async def test_update_packet(self):
        from uuid import uuid4
        async with _make_client() as client:
            packet_id = str(uuid4())
            response_data = _sample_packet_response(packet_id)
            response_data["status"] = "in_progress"

            respx.patch(f"{BASE_URL}/packets/{packet_id}").mock(
                return_value=httpx.Response(200, json=response_data),
            )

            result = await client.update_packet(packet_id, PacketUpdate(status=PacketStatus.in_progress))
            assert result.status == PacketStatus.in_progress


# ── complete_packet ─────────────────────────────────────────────────────────────


class TestAsyncCompletePacket:
    @respx.mock
    @pytest.mark.asyncio
    async def test_complete_packet(self):
        from uuid import uuid4
        async with _make_client() as client:
            packet_id = str(uuid4())
            response_data = _sample_packet_response(packet_id)
            response_data["status"] = "completed"

            respx.patch(f"{BASE_URL}/packets/{packet_id}").mock(
                return_value=httpx.Response(200, json=response_data),
            )

            result = await client.complete_packet(packet_id)
            assert result.status == PacketStatus.completed


# ── delete_packet ───────────────────────────────────────────────────────────────


class TestAsyncDeletePacket:
    @respx.mock
    @pytest.mark.asyncio
    async def test_delete_packet(self):
        from uuid import uuid4
        async with _make_client() as client:
            packet_id = str(uuid4())
            respx.delete(f"{BASE_URL}/packets/{packet_id}").mock(
                return_value=httpx.Response(204),
            )

            await client.delete_packet(packet_id)  # Should not raise


# ── respond_to_hitl ─────────────────────────────────────────────────────────────


class TestAsyncRespondToHITL:
    @respx.mock
    @pytest.mark.asyncio
    async def test_respond_to_hitl(self):
        from uuid import uuid4
        async with _make_client() as client:
            packet_id = str(uuid4())
            response_data = _sample_packet_response(packet_id)
            response_data["status"] = "claimed"
            response_data["hitl"] = {
                "required": True,
                "reason": "Needs approval",
                "question": "Approve?",
                "response": "Approved",
                "responded_at": "2026-05-13T22:00:00Z",
                "responded_by": "manager@test.com",
            }

            respx.post(f"{BASE_URL}/packets/{packet_id}/respond").mock(
                return_value=httpx.Response(200, json=response_data),
            )

            result = await client.respond_to_hitl(
                packet_id, response="Approved", responded_by="manager@test.com"
            )
            assert result.hitl is not None
            assert result.hitl.response == "Approved"


# ── get_awaiting ─────────────────────────────────────────────────────────────────


class TestAsyncGetAwaiting:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_awaiting(self):
        async with _make_client() as client:
            respx.get(f"{BASE_URL}/packets/awaiting").mock(
                return_value=httpx.Response(200, json={"packets": [], "total": 0, "limit": 50, "offset": 0}),
            )

            result = await client.get_awaiting()
            assert result.total == 0


# ── get_history ─────────────────────────────────────────────────────────────────


class TestAsyncGetHistory:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_history(self):
        from uuid import uuid4
        async with _make_client() as client:
            packet_id = str(uuid4())
            respx.get(f"{BASE_URL}/packets/{packet_id}/history").mock(
                return_value=httpx.Response(200, json={"packet_id": packet_id, "events": []}),
            )

            result = await client.get_history(packet_id)
            assert result.packet_id == packet_id


# ── chain_handoff ───────────────────────────────────────────────────────────────


class TestAsyncChainHandoff:
    @respx.mock
    @pytest.mark.asyncio
    async def test_chain_handoff(self):
        from uuid import uuid4
        async with _make_client() as client:
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
                context=PacketContext(summary="Follow-up work"),
            )
            result = await client.chain_handoff(parent_id, chain_request)
            assert str(result.parent_packet_id) == parent_id


# ── Webhook CRUD ────────────────────────────────────────────────────────────────


class TestAsyncWebhooks:
    @respx.mock
    @pytest.mark.asyncio
    async def test_register_webhook(self):
        async with _make_client() as client:
            webhook_data = {
                "id": "wh-1",
                "url": "https://example.com/webhook",
                "events": ["packet.created"],
                "tenant_id": "tenant-1",
                "active": True,
                "created_at": "2026-05-13T21:00:00Z",
            }

            respx.post(f"{BASE_URL}/hooks").mock(
                return_value=httpx.Response(201, json=webhook_data),
            )

            result = await client.register_webhook(
                url="https://example.com/webhook",
                events=["packet.created"],
                secret="a" * 16,
            )
            assert result.id == "wh-1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_webhooks(self):
        async with _make_client() as client:
            respx.get(f"{BASE_URL}/hooks").mock(
                return_value=httpx.Response(200, json=[]),
            )

            result = await client.list_webhooks()
            assert result == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_delete_webhook(self):
        async with _make_client() as client:
            respx.delete(f"{BASE_URL}/hooks/wh-1").mock(
                return_value=httpx.Response(204),
            )

            await client.delete_webhook("wh-1")  # Should not raise


# ── Error handling ──────────────────────────────────────────────────────────────


class TestAsyncErrorHandling:
    @respx.mock
    @pytest.mark.asyncio
    async def test_authentication_error(self):
        async with _make_client() as client:
            respx.get(f"{BASE_URL}/packets/test-id").mock(
                return_value=httpx.Response(401, json={"detail": "Invalid API key"}),
            )

            with pytest.raises(AuthenticationError):
                await client.get_packet("test-id")

    @respx.mock
    @pytest.mark.asyncio
    async def test_server_error(self):
        async with _make_client() as client:
            respx.get(f"{BASE_URL}/packets/test-id").mock(
                return_value=httpx.Response(500, json={"detail": "Internal error"}),
            )

            with pytest.raises(ServerError):
                await client.get_packet("test-id")

    @respx.mock
    @pytest.mark.asyncio
    async def test_connection_error(self):
        async with _make_client() as client:
            respx.get(f"{BASE_URL}/packets").mock(
                side_effect=httpx.ConnectError("Connection refused"),
            )

            with pytest.raises(ConnectionError):
                await client.list_packets()
