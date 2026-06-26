"""Tests for the integration base adapter — contract enforcement.

Verifies that:
1. BaseAdapter defines the required abstract interface
2. Concrete subclasses implement all required methods
3. The shared handoff methods work correctly with a mocked client
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

# Ensure SDK src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "src"))

import httpx
import respx
from handoffrail.integrations.base import BaseAdapter
from handoffrail.sdk.client import HandoffRailClient
from handoffrail.sdk.models import PacketResponse, PacketStatus

BASE_URL = "http://testserver/api/v1"
API_KEY = "hr_test_base_adapter_key"


def _make_client() -> HandoffRailClient:
    return HandoffRailClient(base_url=BASE_URL, api_key=API_KEY, timeout=5.0, max_retries=1)


def _sample_packet_response(packet_id: str | None = None) -> dict:
    pid = packet_id or str(uuid4())
    return {
        "id": pid,
        "version": "1.0.0",
        "parent_packet_id": None,
        "metadata": {
            "source_agent": {"id": "agent-1", "name": "AgentOne", "framework": "custom"},
            "target_agent": {"id": "agent-2", "name": "AgentTwo"},
            "created_at": "2026-05-13T21:00:00Z",
            "claimed_at": None,
            "completed_at": None,
            "priority": "normal",
            "tags": ["test"],
        },
        "context": {
            "summary": "Test handoff",
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


# ── Concrete test subclass ─────────────────────────────────────────────────────


class SampleAdapter(BaseAdapter):
    """Minimal concrete adapter for testing the base class contract."""

    def _default_framework(self) -> str:
        return "test"

    def extract_conversation(self, context: Any) -> list[dict[str, Any]]:
        """Simple extraction: accept list of dicts or string."""
        if isinstance(context, str):
            return [{"role": "user", "content": context}]
        if isinstance(context, list):
            return context
        return []

    def resume_conversation(self, packet: PacketResponse) -> Any:
        """Return a simple dict with summary and conversation."""
        return {
            "summary": packet.context.summary,
            "messages": [
                {"role": e.role.value if hasattr(e.role, "value") else str(e.role), "content": e.content}
                for e in packet.context.conversation_state
            ],
        }


# ── Abstract interface tests ───────────────────────────────────────────────────


class TestBaseAdapterAbstract:
    """Verify BaseAdapter cannot be instantiated directly."""

    def test_base_adapter_is_abstract(self):
        """BaseAdapter should not be instantiable without implementing abstract methods."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseAdapter(client=_make_client(), agent_id="test", agent_name="TestBot")  # type: ignore[abstract]

    def test_missing_extract_conversation_raises(self):
        """Subclass missing extract_conversation should fail."""
        class IncompleteAdapter(BaseAdapter):
            def resume_conversation(self, packet):
                return {}

        with pytest.raises(TypeError, match="Can't instantiate abstract class|abstract method"):
            IncompleteAdapter(client=_make_client(), agent_id="test", agent_name="TestBot")  # type: ignore[abstract]

    def test_missing_resume_conversation_raises(self):
        """Subclass missing resume_conversation should fail."""
        class IncompleteAdapter(BaseAdapter):
            def extract_conversation(self, context):
                return []

        with pytest.raises(TypeError, match="Can't instantiate abstract class|abstract method"):
            IncompleteAdapter(client=_make_client(), agent_id="test", agent_name="TestBot")  # type: ignore[abstract]


class TestBaseAdapterConcrete:
    """Verify the concrete TestAdapter implements required methods."""

    def test_concrete_adapter_instantiates(self):
        adapter = SampleAdapter(client=_make_client(), agent_id="test-01", agent_name="TestBot")
        assert adapter.agent_id == "test-01"
        assert adapter.agent_name == "TestBot"
        assert adapter.framework == "test"

    def test_default_framework_override(self):
        adapter = SampleAdapter(client=_make_client(), agent_id="test-01", agent_name="TestBot")
        assert adapter._default_framework() == "test"

    def test_framework_param_override(self):
        adapter = SampleAdapter(
            client=_make_client(), agent_id="test-01", agent_name="TestBot", framework="langchain"
        )
        assert adapter.framework == "langchain"


class TestBaseAdapterCreateHandoff:
    """Test the create_handoff shared method."""

    @respx.mock
    def test_create_handoff_basic(self):
        client = _make_client()
        adapter = SampleAdapter(client=client, agent_id="sales-01", agent_name="SalesBot")
        response_data = _sample_packet_response()

        respx.post(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(201, json=response_data),
        )

        result = adapter.create_handoff(
            target_agent_id="billing-01",
            target_agent_name="BillingBot",
            summary="Customer upgrade request",
        )

        assert isinstance(result, PacketResponse)
        assert result.context.summary == "Test handoff"

    @respx.mock
    def test_create_handoff_with_conversation(self):
        client = _make_client()
        adapter = SampleAdapter(client=client, agent_id="sales-01", agent_name="SalesBot")
        response_data = _sample_packet_response()

        respx.post(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(201, json=response_data),
        )

        result = adapter.create_handoff(
            target_agent_id="billing-01",
            target_agent_name="BillingBot",
            summary="Customer upgrade",
            conversation_state=[{"role": "user", "content": "I want to upgrade"}],
        )

        assert isinstance(result, PacketResponse)

    @respx.mock
    def test_create_handoff_with_priority(self):
        client = _make_client()
        adapter = SampleAdapter(client=client, agent_id="sales-01", agent_name="SalesBot")
        response_data = _sample_packet_response()

        route = respx.post(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(201, json=response_data),
        )

        result = adapter.create_handoff(
            target_agent_id="billing-01",
            target_agent_name="BillingBot",
            summary="Urgent issue",
            priority="high",
        )

        assert isinstance(result, PacketResponse)
        # Verify priority was sent in the request
        request_body = route.calls[0].request.content.decode()
        import json
        body = json.loads(request_body)
        assert body["metadata"]["priority"] == "high"


class TestBaseAdapterClaimHandoff:
    """Test the claim_handoff shared method."""

    @respx.mock
    def test_claim_handoff(self):
        client = _make_client()
        adapter = SampleAdapter(client=client, agent_id="billing-01", agent_name="BillingBot")
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "claimed"
        response_data["metadata"]["claimed_at"] = "2026-05-13T21:05:00Z"

        respx.post(f"{BASE_URL}/packets/{packet_id}/claim").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = adapter.claim_handoff(packet_id)
        assert result.status == PacketStatus.claimed


class TestBaseAdapterUpdateHandoff:
    """Test the update_handoff shared method."""

    @respx.mock
    def test_update_handoff_status(self):
        client = _make_client()
        adapter = SampleAdapter(client=client, agent_id="billing-01", agent_name="BillingBot")
        packet_id = str(uuid4())

        # First get_packet call for context update
        get_data = _sample_packet_response(packet_id)
        respx.get(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(200, json=get_data),
        )

        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "in_progress"
        respx.patch(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = adapter.update_handoff(packet_id, status="in_progress")
        assert result.status == PacketStatus.in_progress


class TestBaseAdapterCompleteHandoff:
    """Test the complete_handoff shared method."""

    @respx.mock
    def test_complete_handoff(self):
        client = _make_client()
        adapter = SampleAdapter(client=client, agent_id="billing-01", agent_name="BillingBot")
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "completed"
        response_data["metadata"]["completed_at"] = "2026-05-13T21:30:00Z"

        respx.patch(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = adapter.complete_handoff(packet_id)
        assert result.status == PacketStatus.completed


class TestBaseAdapterGetHandoff:
    """Test the get_handoff shared method."""

    @respx.mock
    def test_get_handoff(self):
        client = _make_client()
        adapter = SampleAdapter(client=client, agent_id="billing-01", agent_name="BillingBot")
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)

        respx.get(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = adapter.get_handoff(packet_id)
        assert str(result.id) == packet_id


class TestBaseAdapterPollForHandoff:
    """Test the poll_for_handoff shared method."""

    @respx.mock
    def test_poll_for_handoff(self):
        client = _make_client()
        adapter = SampleAdapter(client=client, agent_id="billing-01", agent_name="BillingBot")
        response_data = {
            "packets": [_sample_packet_response()],
            "total": 1,
            "limit": 10,
            "offset": 0,
        }

        respx.get(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = adapter.poll_for_handoff(status="created", limit=10)
        assert len(result) == 1


class TestBaseAdapterRespondToHITL:
    """Test the respond_to_hitl shared method."""

    @respx.mock
    def test_respond_to_hitl(self):
        client = _make_client()
        adapter = SampleAdapter(client=client, agent_id="manager-01", agent_name="Manager")
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "claimed"
        response_data["hitl"] = {
            "required": True,
            "reason": "Approval needed",
            "question": "Approve?",
            "response": "Approved",
            "responded_at": "2026-05-13T22:00:00Z",
            "responded_by": "manager-01",
        }

        respx.post(f"{BASE_URL}/packets/{packet_id}/respond").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = adapter.respond_to_hitl(packet_id, response="Approved")
        assert result.hitl is not None
        assert result.hitl.response == "Approved"


class TestBaseAdapterChainHandoff:
    """Test the chain_handoff shared method."""

    @respx.mock
    def test_chain_handoff(self):
        client = _make_client()
        adapter = SampleAdapter(client=client, agent_id="billing-01", agent_name="BillingBot")
        parent_id = str(uuid4())
        child_id = str(uuid4())
        response_data = _sample_packet_response(child_id)
        response_data["parent_packet_id"] = parent_id

        respx.post(f"{BASE_URL}/packets/{parent_id}/chain").mock(
            return_value=httpx.Response(201, json=response_data),
        )

        result = adapter.chain_handoff(
            parent_packet_id=parent_id,
            target_agent_id="followup-01",
            target_agent_name="FollowUpBot",
            summary="Follow-up needed",
        )

        assert str(result.parent_packet_id) == parent_id


class TestAdapterInterfaceConsistency:
    """Verify that both LangChain and CrewAI adapters implement the BaseAdapter interface."""

    def test_langchain_adapter_inherits_base(self):
        from handoffrail.integrations.langchain import LangChainAdapter
        assert issubclass(LangChainAdapter, BaseAdapter)

    def test_crewai_adapter_inherits_base(self):
        from handoffrail.integrations.crewai import CrewAIAdapter
        assert issubclass(CrewAIAdapter, BaseAdapter)

    def test_langchain_adapter_has_required_methods(self):
        from handoffrail.integrations.langchain import LangChainAdapter
        required = {"extract_conversation", "resume_conversation", "create_handoff",
                     "claim_handoff", "update_handoff", "complete_handoff", "get_handoff"}
        actual = {m for m in dir(LangChainAdapter) if not m.startswith("_")}
        assert required.issubset(actual), f"Missing methods: {required - actual}"

    def test_crewai_adapter_has_required_methods(self):
        from handoffrail.integrations.crewai import CrewAIAdapter
        required = {"extract_conversation", "resume_conversation", "create_handoff",
                     "claim_handoff", "update_handoff", "complete_handoff", "get_handoff"}
        actual = {m for m in dir(CrewAIAdapter) if not m.startswith("_")}
        assert required.issubset(actual), f"Missing methods: {required - actual}"

    def test_langchain_adapter_default_framework(self):
        from handoffrail.integrations.langchain import LangChainAdapter
        adapter = LangChainAdapter(client=_make_client(), agent_id="test", agent_name="Test")
        assert adapter.framework == "langchain"

    def test_crewai_adapter_default_framework(self):
        from handoffrail.integrations.crewai import CrewAIAdapter
        adapter = CrewAIAdapter(client=_make_client(), agent_id="test", agent_name="Test")
        assert adapter.framework == "crewai"


class TestAdapterMethodSignatures:
    """Verify shared method signatures match across adapters."""

    def test_create_handoff_params(self):
        """All adapters should accept the same create_handoff parameters."""
        import inspect

        from handoffrail.integrations.crewai import CrewAIAdapter
        from handoffrail.integrations.langchain import LangChainAdapter

        base_sig = set(inspect.signature(BaseAdapter.create_handoff).parameters)
        lc_sig = set(inspect.signature(LangChainAdapter.create_handoff).parameters)
        ca_sig = set(inspect.signature(CrewAIAdapter.create_handoff).parameters)

        # Adapters inherit the base method, so signatures should match
        assert base_sig == lc_sig, f"LangChain create_handoff signature differs: {lc_sig - base_sig}"
        assert base_sig == ca_sig, f"CrewAI create_handoff signature differs: {ca_sig - base_sig}"
