"""Tests for HandoffRail SDK — Data models.

Validates that SDK models correctly serialize/deserialize, support from_dict/to_dict,
and enforce validation rules matching the server's Pydantic models.
"""

from __future__ import annotations

import pytest
from handoffrail.sdk.models import (
    Actions,
    AgentInfo,
    Artifact,
    ChainHandoffRequest,
    ContextEntry,
    Decision,
    Dependency,
    DependencyType,
    HitlCheckpoint,
    HitlRespondRequest,
    Metadata,
    PacketContext,
    PacketCreate,
    PacketEvent,
    PacketListResponse,
    PacketResponse,
    PacketStatus,
    PacketUpdate,
    PendingAction,
    Priority,
    TargetAgentInfo,
    WebhookCreate,
    WebhookResponse,
)

# ── Enum tests ────────────────────────────────────────────────────────────────


class TestEnums:
    def test_priority_values(self):
        assert Priority.low == "low"
        assert Priority.normal == "normal"
        assert Priority.high == "high"
        assert Priority.critical == "critical"

    def test_packet_status_values(self):
        assert PacketStatus.created == "created"
        assert PacketStatus.claimed == "claimed"
        assert PacketStatus.in_progress == "in_progress"
        assert PacketStatus.awaiting_human == "awaiting_human"
        assert PacketStatus.completed == "completed"
        assert PacketStatus.failed == "failed"
        assert PacketStatus.expired == "expired"

    def test_dependency_type_values(self):
        assert DependencyType.api == "api"
        assert DependencyType.human_approval == "human_approval"


# ── AgentInfo ─────────────────────────────────────────────────────────────────


class TestAgentInfo:
    def test_from_dict(self):
        data = {"id": "agent-1", "name": "TestAgent", "framework": "langchain"}
        agent = AgentInfo.from_dict(data)
        assert agent.id == "agent-1"
        assert agent.name == "TestAgent"
        assert agent.framework == "langchain"
        assert agent.version is None

    def test_to_dict(self):
        agent = AgentInfo(id="agent-1", name="TestAgent", framework="langchain")
        d = agent.to_dict()
        assert d["id"] == "agent-1"
        assert "version" not in d  # excluded when None

    def test_roundtrip(self):
        data = {"id": "agent-1", "name": "TestAgent", "framework": "langchain", "version": "1.0"}
        agent = AgentInfo.from_dict(data)
        result = agent.to_dict()
        assert result["id"] == data["id"]
        assert result["version"] == "1.0"


# ── TargetAgentInfo ───────────────────────────────────────────────────────────


class TestTargetAgentInfo:
    def test_minimal(self):
        target = TargetAgentInfo(id="billing-01", name="BillingBot")
        assert target.framework is None

    def test_with_framework(self):
        target = TargetAgentInfo(id="billing-01", name="BillingBot", framework="crewai")
        d = target.to_dict()
        assert d["framework"] == "crewai"


# ── ContextEntry ─────────────────────────────────────────────────────────────


class TestContextEntry:
    def test_from_dict(self):
        data = {"role": "user", "content": "Hello", "timestamp": "2026-05-13T21:00:00Z"}
        entry = ContextEntry.from_dict(data)
        assert entry.role == "user"
        assert entry.content == "Hello"


# ── Decision ──────────────────────────────────────────────────────────────────


class TestDecision:
    def test_from_dict(self):
        data = {
            "id": "d1",
            "decision": "Proceed with upgrade",
            "rationale": "Customer eligible",
            "alternatives": ["defer"],
            "decided_by": "sales-01",
        }
        dec = Decision.from_dict(data)
        assert dec.id == "d1"
        assert len(dec.alternatives) == 1


# ── Actions ───────────────────────────────────────────────────────────────────


class TestActions:
    def test_default_empty(self):
        actions = Actions()
        assert actions.pending == []
        assert actions.completed == []
        assert actions.failed == []

    def test_with_pending(self):
        actions = Actions(
            pending=[PendingAction(id="a1", description="Do thing", assignee="bot-1")],
        )
        d = actions.to_dict()
        assert len(d["pending"]) == 1


# ── HitlCheckpoint ────────────────────────────────────────────────────────────


class TestHitlCheckpoint:
    def test_from_dict(self):
        data = {
            "required": True,
            "reason": "Approval needed",
            "question": "Approve?",
            "options": ["Yes", "No"],
        }
        hitl = HitlCheckpoint.from_dict(data)
        assert hitl.required is True
        assert hitl.question == "Approve?"
        assert len(hitl.options) == 2

    def test_validation_required_without_reason(self):
        """HITL required=True with empty reason raises on PacketCreate (field validator)."""
        from pydantic import ValidationError as PydanticValidationError
        with pytest.raises(PydanticValidationError):
            PacketCreate(
                metadata=Metadata(
                    source_agent=AgentInfo(id="s1", name="Source"),
                    target_agent=TargetAgentInfo(id="t1", name="Target"),
                ),
                context=PacketContext(summary="Test"),
                hitl=HitlCheckpoint(required=True, reason=""),
            )


# ── PacketCreate ─────────────────────────────────────────────────────────────


class TestPacketCreate:
    def test_minimal_from_dict(self):
        data = {
            "metadata": {
                "source_agent": {"id": "s1", "name": "Source"},
                "target_agent": {"id": "t1", "name": "Target"},
                "priority": "normal",
                "tags": [],
            },
            "context": {
                "summary": "Test",
                "conversation_state": [],
                "artifacts": [],
                "custom": {},
            },
            "decisions": [],
            "actions": {"pending": [], "completed": [], "failed": []},
            "dependencies": [],
        }
        packet = PacketCreate.from_dict(data)
        assert packet.metadata.source_agent.id == "s1"
        assert packet.context.summary == "Test"

    def test_to_dict_roundtrip(self):
        source = AgentInfo(id="s1", name="Source", framework="langchain")
        target = TargetAgentInfo(id="t1", name="Target")
        metadata = Metadata(source_agent=source, target_agent=target)
        context = PacketContext(summary="Test packet")
        packet = PacketCreate(metadata=metadata, context=context)

        d = packet.to_dict()
        assert d["metadata"]["source_agent"]["id"] == "s1"
        assert d["context"]["summary"] == "Test packet"

    def test_hitl_validation(self):
        """HITL checkpoint with required=True but no reason should fail."""
        from handoffrail.sdk.models import HitlCheckpoint
        with pytest.raises(ValueError):
            PacketCreate(
                metadata=Metadata(
                    source_agent=AgentInfo(id="s1", name="Source"),
                    target_agent=TargetAgentInfo(id="t1", name="Target"),
                ),
                context=PacketContext(summary="Test"),
                hitl=HitlCheckpoint(required=True, reason=""),
            )


# ── PacketResponse ───────────────────────────────────────────────────────────


class TestPacketResponse:
    def test_from_dict(self):
        data = {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "version": "1.0.0",
            "parent_packet_id": None,
            "metadata": {
                "source_agent": {"id": "s1", "name": "Source"},
                "target_agent": {"id": "t1", "name": "Target"},
                "created_at": "2026-05-13T21:00:00Z",
                "claimed_at": None,
                "completed_at": None,
                "priority": "high",
                "tags": ["test"],
            },
            "context": {"summary": "Test", "conversation_state": [], "artifacts": [], "custom": {}},
            "decisions": [],
            "actions": {"pending": [], "completed": [], "failed": []},
            "dependencies": [],
            "hitl": None,
            "status": "created",
            "created_at": "2026-05-13T21:00:00Z",
            "updated_at": "2026-05-13T21:00:00Z",
        }
        response = PacketResponse.from_dict(data)
        assert str(response.id) == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert response.status == PacketStatus.created
        assert response.metadata.priority == Priority.high
        assert response.metadata.tags == ["test"]


# ── PacketUpdate ───────────────────────────────────────────────────────────────


class TestPacketUpdate:
    def test_status_only(self):
        update = PacketUpdate(status=PacketStatus.in_progress)
        d = update.to_dict()
        assert d["status"] == "in_progress"
        # None fields should be excluded
        assert "context" not in d
        assert "decisions" not in d

    def test_all_none(self):
        update = PacketUpdate()
        d = update.to_dict()
        # All None fields excluded
        assert d == {}


# ── PacketListResponse ────────────────────────────────────────────────────────


class TestPacketListResponse:
    def test_from_dict(self):
        data = {
            "packets": [],
            "total": 0,
            "limit": 50,
            "offset": 0,
        }
        result = PacketListResponse.from_dict(data)
        assert result.total == 0
        assert result.limit == 50


# ── WebhookCreate ─────────────────────────────────────────────────────────────


class TestWebhookCreate:
    def test_valid_webhook(self):
        wh = WebhookCreate(
            url="https://example.com/webhook",
            events=["packet.created", "packet.completed"],
            secret="a" * 16,
        )
        assert wh.url == "https://example.com/webhook"

    def test_invalid_url(self):
        with pytest.raises(ValueError):
            WebhookCreate(url="ftp://bad.com", events=["packet.created"], secret="a" * 16)

    def test_invalid_event(self):
        with pytest.raises(ValueError):
            WebhookCreate(url="https://example.com", events=["packet.invalid_event"], secret="a" * 16)

    def test_secret_too_short(self):
        with pytest.raises(ValueError):
            WebhookCreate(url="https://example.com", events=["packet.created"], secret="short")


# ── WebhookResponse ───────────────────────────────────────────────────────────


class TestWebhookResponse:
    def test_from_dict(self):
        data = {
            "id": "wh-1",
            "url": "https://example.com/webhook",
            "events": ["packet.created"],
            "tenant_id": "tenant-1",
            "active": True,
            "created_at": "2026-05-13T21:00:00Z",
        }
        wh = WebhookResponse.from_dict(data)
        assert wh.id == "wh-1"
        assert wh.active is True


# ── PacketEvent ───────────────────────────────────────────────────────────────


class TestPacketEvent:
    def test_from_dict(self):
        data = {
            "id": "evt-1",
            "packet_id": "pkt-1",
            "event_type": "created",
            "actor": "agent:sales-01",
            "details": {"key": "value"},
            "timestamp": "2026-05-13T21:00:00Z",
        }
        event = PacketEvent.from_dict(data)
        assert event.event_type == "created"
        assert event.details == {"key": "value"}


# ── HitlRespondRequest ────────────────────────────────────────────────────────


class TestHitlRespondRequest:
    def test_to_dict(self):
        req = HitlRespondRequest(response="Approved", responded_by="manager@test.com")
        d = req.to_dict()
        assert d["response"] == "Approved"
        assert d["responded_by"] == "manager@test.com"

    def test_to_dict_with_notes(self):
        req = HitlRespondRequest(response="Denied", responded_by="admin", notes="Not enough info")
        d = req.to_dict()
        assert d["notes"] == "Not enough info"


# ── ChainHandoffRequest ──────────────────────────────────────────────────────


class TestChainHandoffRequest:
    def test_from_dict(self):
        data = {
            "metadata": {
                "source_agent": {"id": "s1", "name": "Source"},
                "target_agent": {"id": "t1", "name": "Target"},
                "priority": "normal",
                "tags": [],
            },
            "context": {"summary": "Chain", "conversation_state": [], "artifacts": [], "custom": {}},
            "decisions": [],
            "actions": {"pending": [], "completed": [], "failed": []},
            "dependencies": [],
        }
        req = ChainHandoffRequest.from_dict(data)
        assert req.metadata.source_agent.id == "s1"
        assert req.context.summary == "Chain"

    def test_to_dict(self):
        req = ChainHandoffRequest(
            metadata=Metadata(
                source_agent=AgentInfo(id="s1", name="Source"),
                target_agent=TargetAgentInfo(id="t1", name="Target"),
            ),
            context=PacketContext(summary="Chain test"),
        )
        d = req.to_dict()
        assert d["metadata"]["source_agent"]["id"] == "s1"


# ── Dependency ────────────────────────────────────────────────────────────────


class TestDependency:
    def test_from_dict(self):
        data = {"id": "dep1", "type": "api", "description": "Payment gateway", "status": "available"}
        dep = Dependency.from_dict(data)
        assert dep.id == "dep1"
        assert dep.type == DependencyType.api

    def test_to_dict(self):
        dep = Dependency(id="dep1", type=DependencyType.api, description="Payment gateway")
        d = dep.to_dict()
        assert d["type"] == "api"


# ── Artifact ──────────────────────────────────────────────────────────────────


class TestArtifact:
    def test_from_dict(self):
        data = {"key": "draft", "value": "Hello world", "content_type": "text/plain"}
        art = Artifact.from_dict(data)
        assert art.key == "draft"

    def test_complex_value(self):
        data = {"key": "profile", "value": {"id": "cust-1", "tier": "pro"}}
        art = Artifact.from_dict(data)
        assert isinstance(art.value, dict)
