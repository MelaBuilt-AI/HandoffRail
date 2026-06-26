"""Tests for the CrewAI integration adapter.

All HTTP calls are mocked using ``respx`` so no real server is needed.
CrewAI-specific classes (BaseTool) are mocked when crewai is not installed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

# Ensure SDK src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "src"))

import httpx
import respx
from handoffrail.integrations.crewai import _CREWAI_AVAILABLE, CrewAIAdapter
from handoffrail.sdk.client import HandoffRailClient
from handoffrail.sdk.models import PacketResponse, PacketStatus

BASE_URL = "http://testserver/api/v1"
API_KEY = "hr_test_crewai_key"


def _make_client() -> HandoffRailClient:
    return HandoffRailClient(base_url=BASE_URL, api_key=API_KEY, timeout=5.0, max_retries=1)


def _make_adapter() -> CrewAIAdapter:
    return CrewAIAdapter(client=_make_client(), agent_id="billing-01", agent_name="BillingBot")


def _sample_packet_response(packet_id: str | None = None) -> dict:
    pid = packet_id or str(uuid4())
    return {
        "id": pid,
        "version": "1.0.0",
        "parent_packet_id": None,
        "metadata": {
            "source_agent": {"id": "billing-01", "name": "BillingBot", "framework": "crewai"},
            "target_agent": {"id": "support-01", "name": "SupportBot"},
            "created_at": "2026-05-13T21:00:00Z",
            "claimed_at": None,
            "completed_at": None,
            "priority": "normal",
            "tags": ["test"],
        },
        "context": {
            "summary": "Payment processed, customer needs onboarding",
            "conversation_state": [
                {"role": "user", "content": "I just paid"},
                {"role": "agent", "content": "Payment confirmed, sending to support."},
            ],
            "artifacts": [],
            "custom": {},
        },
        "decisions": [
            {"id": "d1", "decision": "Process payment", "rationale": "Customer paid", "alternatives": [], "decided_by": "billing-01", "timestamp": "2026-05-13T21:10:00Z"}
        ],
        "actions": {
            "pending": [
                {"id": "a1", "description": "Onboard customer", "assignee": "support-01", "priority": "normal", "depends_on": []}
            ],
            "completed": [],
            "failed": [],
        },
        "dependencies": [],
        "hitl": None,
        "status": "created",
        "created_at": "2026-05-13T21:00:00Z",
        "updated_at": "2026-05-13T21:00:00Z",
    }


# ── Adapter basics ──────────────────────────────────────────────────────────────


class TestCrewAIAdapterBasics:
    def test_adapter_inherits_base(self):
        from handoffrail.integrations.base import BaseAdapter
        assert issubclass(CrewAIAdapter, BaseAdapter)

    def test_default_framework(self):
        adapter = _make_adapter()
        assert adapter.framework == "crewai"

    def test_custom_framework_override(self):
        adapter = CrewAIAdapter(
            client=_make_client(), agent_id="test", agent_name="TestBot", framework="crewai-custom"
        )
        assert adapter.framework == "crewai-custom"


# ── Extract conversation ────────────────────────────────────────────────────────


class TestCrewAIExtractConversation:
    def test_extract_from_empty_list(self):
        adapter = _make_adapter()
        result = adapter.extract_conversation([])
        assert result == []

    def test_extract_from_dict_list(self):
        adapter = _make_adapter()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "task", "content": "Process the order"},
        ]
        result = adapter.extract_conversation(messages)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "system"  # "task" maps to "system"

    def test_extract_from_string(self):
        adapter = _make_adapter()
        result = adapter.extract_conversation("Task completed successfully")
        assert len(result) == 1
        assert result[0]["role"] == "agent"
        assert result[0]["content"] == "Task completed successfully"

    def test_extract_from_crewai_task_mock(self):
        """Test extraction from a mock CrewAI Task object."""
        adapter = _make_adapter()
        task = MagicMock()
        task.description = "Process the customer payment"
        task.expected_output = "A confirmation receipt"

        result = adapter.extract_conversation(task)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "Process the customer payment" in result[0]["content"]
        assert result[1]["role"] == "system"
        assert "confirmation receipt" in result[1]["content"]

    def test_extract_from_crewai_task_without_expected_output(self):
        adapter = _make_adapter()
        task = MagicMock()
        task.description = "Generate report"
        task.expected_output = None

        result = adapter.extract_conversation(task)
        assert len(result) == 1
        assert "Generate report" in result[0]["content"]

    def test_extract_normalizes_roles(self):
        adapter = _make_adapter()
        messages = [
            {"role": "human", "content": "Help me"},
            {"role": "ai", "content": "Sure"},
            {"role": "assistant", "content": "No problem"},
        ]
        result = adapter.extract_conversation(messages)
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "agent"
        assert result[2]["role"] == "agent"


# ── Resume conversation ─────────────────────────────────────────────────────────


class TestCrewAIResumeConversation:
    def test_resume_conversation_basic(self):
        adapter = _make_adapter()
        response_data = _sample_packet_response()
        packet = PacketResponse.from_dict(response_data)

        result = adapter.resume_conversation(packet)
        assert isinstance(result, dict)
        assert "summary" in result
        assert result["summary"] == "Payment processed, customer needs onboarding"
        assert "conversation" in result
        assert len(result["conversation"]) == 2

    def test_resume_conversation_includes_pending_actions(self):
        adapter = _make_adapter()
        response_data = _sample_packet_response()
        packet = PacketResponse.from_dict(response_data)

        result = adapter.resume_conversation(packet)
        assert "pending_actions" in result
        assert len(result["pending_actions"]) == 1
        assert result["pending_actions"][0]["description"] == "Onboard customer"

    def test_resume_conversation_includes_decisions(self):
        adapter = _make_adapter()
        response_data = _sample_packet_response()
        packet = PacketResponse.from_dict(response_data)

        result = adapter.resume_conversation(packet)
        assert "decisions" in result
        assert len(result["decisions"]) == 1
        assert result["decisions"][0]["decision"] == "Process payment"

    def test_resume_conversation_includes_source_agent(self):
        adapter = _make_adapter()
        response_data = _sample_packet_response()
        packet = PacketResponse.from_dict(response_data)

        result = adapter.resume_conversation(packet)
        assert result["source_agent"] == "BillingBot"
        assert result["source_agent_id"] == "billing-01"

    def test_resume_conversation_includes_hitl(self):
        adapter = _make_adapter()
        response_data = _sample_packet_response()
        response_data["hitl"] = {
            "required": True,
            "reason": "Needs approval",
            "question": "Approve this?",
            "options": ["Yes", "No"],
            "response": None,
        }
        packet = PacketResponse.from_dict(response_data)

        result = adapter.resume_conversation(packet)
        assert result.get("hitl_required") is True
        assert result.get("hitl_question") == "Approve this?"
        assert result.get("hitl_options") == ["Yes", "No"]

    def test_resume_conversation_includes_artifacts(self):
        adapter = _make_adapter()
        response_data = _sample_packet_response()
        response_data["context"]["artifacts"] = [
            {"key": "receipt", "value": {"order_id": "1234", "amount": 99.99}},
        ]
        packet = PacketResponse.from_dict(response_data)

        result = adapter.resume_conversation(packet)
        assert "artifacts" in result
        assert "receipt" in result["artifacts"]


# ── Handoff from task ──────────────────────────────────────────────────────────


class TestCrewAIHandoffFromTask:
    @respx.mock
    def test_handoff_from_task(self):
        adapter = _make_adapter()
        response_data = _sample_packet_response()

        route = respx.post(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(201, json=response_data),
        )

        result = adapter.handoff_from_task(
            task_result="Payment processed successfully",
            target_agent_id="support-01",
            target_agent_name="SupportBot",
            summary="Billing complete, customer needs onboarding",
        )

        assert isinstance(result, PacketResponse)
        # Verify the request includes the task result in conversation
        request_body = json.loads(route.calls[0].request.content.decode())
        assert len(request_body["context"]["conversation_state"]) > 0
        assert "Payment processed successfully" in request_body["context"]["conversation_state"][0]["content"]

    @respx.mock
    def test_handoff_from_task_with_decisions(self):
        adapter = _make_adapter()
        response_data = _sample_packet_response()

        respx.post(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(201, json=response_data),
        )

        result = adapter.handoff_from_task(
            task_result="Order shipped",
            target_agent_id="support-01",
            target_agent_name="SupportBot",
            summary="Order fulfillment complete",
            decisions=[{"id": "d1", "decision": "Ship order", "rationale": "All items in stock"}],
        )

        assert isinstance(result, PacketResponse)


# ── Create handoff ─────────────────────────────────────────────────────────────


class TestCrewAICreateHandoff:
    @respx.mock
    def test_create_handoff_basic(self):
        adapter = _make_adapter()
        response_data = _sample_packet_response()

        respx.post(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(201, json=response_data),
        )

        result = adapter.create_handoff(
            target_agent_id="support-01",
            target_agent_name="SupportBot",
            summary="Customer needs help",
        )

        assert isinstance(result, PacketResponse)
        assert result.status == PacketStatus.created

    @respx.mock
    def test_create_handoff_with_conversation(self):
        adapter = _make_adapter()
        response_data = _sample_packet_response()

        route = respx.post(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(201, json=response_data),
        )

        result = adapter.create_handoff(
            target_agent_id="support-01",
            target_agent_name="SupportBot",
            summary="Follow up needed",
            conversation_state=[
                {"role": "user", "content": "I have a question"},
                {"role": "agent", "content": "Let me connect you"},
            ],
        )

        assert isinstance(result, PacketResponse)
        request_body = json.loads(route.calls[0].request.content.decode())
        assert len(request_body["context"]["conversation_state"]) == 2


# ── Claim handoff ──────────────────────────────────────────────────────────────


class TestCrewAIClaimHandoff:
    @respx.mock
    def test_claim_handoff(self):
        adapter = _make_adapter()
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "claimed"

        respx.post(f"{BASE_URL}/packets/{packet_id}/claim").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = adapter.claim_handoff(packet_id)
        assert result.status == PacketStatus.claimed


# ── Complete handoff ──────────────────────────────────────────────────────────


class TestCrewAICompleteHandoff:
    @respx.mock
    def test_complete_handoff(self):
        adapter = _make_adapter()
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "completed"
        response_data["metadata"]["completed_at"] = "2026-05-13T22:00:00Z"

        respx.patch(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = adapter.complete_handoff(packet_id)
        assert result.status == PacketStatus.completed


# ── Packet to task input ──────────────────────────────────────────────────────


class TestCrewAIPacketToTaskInput:
    """Test the resume_conversation method (which serves as packet_to_task_input)."""

    @respx.mock
    def test_full_workflow(self):
        """End-to-end test: create → claim → resume → complete."""
        adapter = _make_adapter()

        # Create
        create_response = _sample_packet_response()
        respx.post(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(201, json=create_response),
        )
        packet = adapter.create_handoff(
            target_agent_id="support-01",
            target_agent_name="SupportBot",
            summary="Customer inquiry",
        )

        # Claim
        claim_response = _sample_packet_response(str(packet.id))
        claim_response["status"] = "claimed"
        respx.post(f"{BASE_URL}/packets/{packet.id}/claim").mock(
            return_value=httpx.Response(200, json=claim_response),
        )
        claimed = adapter.claim_handoff(packet.id)
        assert claimed.status == PacketStatus.claimed

        # Resume
        task_input = adapter.resume_conversation(claimed)
        assert "summary" in task_input
        assert "conversation" in task_input

        # Complete
        complete_response = _sample_packet_response(str(packet.id))
        complete_response["status"] = "completed"
        respx.patch(f"{BASE_URL}/packets/{packet.id}").mock(
            return_value=httpx.Response(200, json=complete_response),
        )
        result = adapter.complete_handoff(packet.id)
        assert result.status == PacketStatus.completed


# ── CrewAI Tool ────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _CREWAI_AVAILABLE, reason="crewai not installed")
class TestHandoffRailCrewAITool:
    def test_tool_creation(self):
        from handoffrail.integrations.crewai import HandoffRailCrewAITool

        client = _make_client()
        tool = HandoffRailCrewAITool(client=client)
        assert tool is not None

    @respx.mock
    def test_tool_create_action(self):
        from handoffrail.integrations.crewai import HandoffRailCrewAITool

        client = _make_client()
        tool = HandoffRailCrewAITool(client=client)
        response_data = _sample_packet_response()

        respx.post(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(201, json=response_data),
        )

        result = tool._run(
            action="create",
            target_agent_id="support-01",
            target_agent_name="SupportBot",
            summary="Test create via tool",
            agent_id="billing-01",
            agent_name="BillingBot",
        )

        parsed = json.loads(result)
        assert parsed["status"] == "created"
        assert "packet_id" in parsed

    @respx.mock
    def test_tool_claim_action(self):
        from handoffrail.integrations.crewai import HandoffRailCrewAITool

        client = _make_client()
        tool = HandoffRailCrewAITool(client=client)
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "claimed"

        respx.post(f"{BASE_URL}/packets/{packet_id}/claim").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = tool._run(action="claim", packet_id=packet_id, agent_id="billing-01", agent_name="BillingBot")
        parsed = json.loads(result)
        assert parsed["status"] == "claimed"

    @respx.mock
    def test_tool_complete_action(self):
        from handoffrail.integrations.crewai import HandoffRailCrewAITool

        client = _make_client()
        tool = HandoffRailCrewAITool(client=client)
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "completed"

        respx.patch(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = tool._run(action="complete", packet_id=packet_id)
        parsed = json.loads(result)
        assert parsed["status"] == "completed"

    @respx.mock
    def test_tool_get_action(self):
        from handoffrail.integrations.crewai import HandoffRailCrewAITool

        client = _make_client()
        tool = HandoffRailCrewAITool(client=client)
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)

        respx.get(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = tool._run(action="get", packet_id=packet_id)
        parsed = json.loads(result)
        assert parsed["packet_id"] == packet_id

    @respx.mock
    def test_tool_update_action(self):
        from handoffrail.integrations.crewai import HandoffRailCrewAITool

        client = _make_client()
        tool = HandoffRailCrewAITool(client=client)
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "in_progress"

        respx.patch(f"{BASE_URL}/packets/{packet_id}").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = tool._run(action="update", packet_id=packet_id, status="in_progress")
        parsed = json.loads(result)
        assert parsed["status"] == "updated"

    def test_tool_unknown_action(self):
        from handoffrail.integrations.crewai import HandoffRailCrewAITool

        client = _make_client()
        tool = HandoffRailCrewAITool(client=client)

        result = tool._run(action="invalid")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Unknown action" in parsed["error"]

    def test_tool_create_missing_params(self):
        from handoffrail.integrations.crewai import HandoffRailCrewAITool

        client = _make_client()
        tool = HandoffRailCrewAITool(client=client)

        result = tool._run(action="create")
        parsed = json.loads(result)
        assert "error" in parsed

    @respx.mock
    def test_tool_error_handling(self):
        from handoffrail.integrations.crewai import HandoffRailCrewAITool

        client = _make_client()
        tool = HandoffRailCrewAITool(client=client)

        respx.get(f"{BASE_URL}/packets/nonexistent").mock(
            return_value=httpx.Response(404, json={"detail": "Not found"}),
        )

        result = tool._run(action="get", packet_id="nonexistent")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "NotFoundError" in parsed.get("error_type", "")


# ── Integration without crewai installed ────────────────────────────────────────


class TestCrewAINotInstalled:
    """Verify graceful behavior when crewai is not installed."""

    def test_adapter_always_available(self):
        """CrewAIAdapter should always be importable (no crewai dependency)."""
        adapter = _make_adapter()
        assert adapter.framework == "crewai"

    def test_tool_stub_when_no_crewai(self):
        """If crewai not installed, tool should raise ImportError."""
        if _CREWAI_AVAILABLE:
            pytest.skip("crewai is installed, testing stub is not applicable")

        from handoffrail.integrations.crewai import HandoffRailCrewAITool
        with pytest.raises(ImportError, match="CrewAI is required"):
            HandoffRailCrewAITool(client=_make_client())


# ── Poll for handoff ──────────────────────────────────────────────────────────


class TestCrewAIPollForHandoff:
    @respx.mock
    def test_poll_for_handoff(self):
        adapter = _make_adapter()
        response_data = {
            "packets": [_sample_packet_response()],
            "total": 1,
            "limit": 10,
            "offset": 0,
        }

        route = respx.get(f"{BASE_URL}/packets").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = adapter.poll_for_handoff(status="created", limit=10)
        assert len(result) == 1

        # Verify target_agent defaults to agent_id
        request = route.calls[0].request
        assert "target_agent=billing-01" in str(request.url)


# ── Respond to HITL ────────────────────────────────────────────────────────────


class TestCrewAIRespondToHITL:
    @respx.mock
    def test_respond_to_hitl(self):
        adapter = _make_adapter()
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "claimed"
        response_data["hitl"] = {
            "required": True,
            "reason": "Needs approval",
            "question": "Approve?",
            "response": "Approved",
            "responded_at": "2026-05-13T22:00:00Z",
            "responded_by": "manager",
        }

        respx.post(f"{BASE_URL}/packets/{packet_id}/respond").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = adapter.respond_to_hitl(packet_id, response="Approved")
        assert result.hitl is not None
        assert result.hitl.response == "Approved"

    @respx.mock
    def test_respond_to_hitl_defaults_agent_id(self):
        adapter = _make_adapter()
        packet_id = str(uuid4())
        response_data = _sample_packet_response(packet_id)
        response_data["status"] = "claimed"
        response_data["hitl"] = {
            "required": True,
            "reason": "Needs approval",
            "question": "Approve?",
            "response": "Yes",
            "responded_at": "2026-05-13T22:00:00Z",
            "responded_by": "billing-01",
        }

        route = respx.post(f"{BASE_URL}/packets/{packet_id}/respond").mock(
            return_value=httpx.Response(200, json=response_data),
        )

        result = adapter.respond_to_hitl(packet_id, response="Yes")
        # Verify the responded_by defaults to agent_id
        request_body = json.loads(route.calls[0].request.content.decode())
        assert request_body["responded_by"] == "billing-01"
