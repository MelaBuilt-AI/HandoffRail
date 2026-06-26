"""Tests for HandoffRail SDK — PacketBuilder and ChainBuilder."""

from __future__ import annotations

import pytest

from handoffrail.sdk.builders import ChainBuilder, PacketBuilder
from handoffrail.sdk.models import (
    ChainHandoffRequest,
    PacketCreate,
    Priority,
)


# ── PacketBuilder ────────────────────────────────────────────────────────────


class TestPacketBuilder:
    def test_minimal_valid_build(self):
        """Builder with required fields only."""
        packet = (
            PacketBuilder()
            .from_("sales-01", "SalesBot", framework="langchain")
            .to("billing-01", "BillingBot", framework="crewai")
            .with_summary("Customer wants to upgrade")
            .build()
        )
        assert isinstance(packet, PacketCreate)
        assert packet.metadata.source_agent.id == "sales-01"
        assert packet.metadata.source_agent.framework == "langchain"
        assert packet.metadata.target_agent.id == "billing-01"
        assert packet.context.summary == "Customer wants to upgrade"
        assert packet.metadata.priority == Priority.normal  # default

    def test_full_build(self):
        """Builder with all optional fields."""
        packet = (
            PacketBuilder()
            .from_("sales-01", "SalesBot", framework="langchain", version="2.0")
            .to("billing-01", "BillingBot", framework="crewai")
            .with_summary("Customer upgrade request")
            .with_priority("high")
            .with_tags(["upgrade", "business-tier"])
            .with_conversation([
                {"role": "user", "content": "I want to upgrade"},
                {"role": "agent", "content": "Great! Let me hand you to billing."},
            ])
            .with_decision("Proceed with upgrade", rationale="Customer eligible", decided_by="sales-01")
            .with_action("Process payment", assignee="billing-01", priority="high")
            .with_dependency("stripe", type="api", description="Payment gateway", status="available")
            .with_hitl(reason="High-value upgrade needs approval", question="Approve upgrade?")
            .build()
        )

        assert packet.metadata.priority == Priority.high
        assert packet.metadata.tags == ["upgrade", "business-tier"]
        assert len(packet.context.conversation_state) == 2
        assert len(packet.decisions) == 1
        assert packet.decisions[0].decision == "Proceed with upgrade"
        assert len(packet.actions.pending) == 1
        assert packet.actions.pending[0].description == "Process payment"
        assert len(packet.dependencies) == 1
        assert packet.hitl is not None
        assert packet.hitl.required is True
        assert packet.hitl.reason == "High-value upgrade needs approval"

    def test_priority_enum(self):
        """Priority can be set with string or enum."""
        packet = (
            PacketBuilder()
            .from_("a", "A")
            .to("b", "B")
            .with_summary("Test")
            .with_priority(Priority.critical)
            .build()
        )
        assert packet.metadata.priority == Priority.critical

    def test_multiple_decisions(self):
        """Multiple decisions get auto-incrementing IDs."""
        packet = (
            PacketBuilder()
            .from_("a", "A")
            .to("b", "B")
            .with_summary("Test")
            .with_decision("First", rationale="r1")
            .with_decision("Second", rationale="r2")
            .build()
        )
        assert len(packet.decisions) == 2
        assert packet.decisions[0].id == "d1"
        assert packet.decisions[1].id == "d2"

    def test_multiple_actions(self):
        """Multiple pending actions get auto-incrementing IDs."""
        packet = (
            PacketBuilder()
            .from_("a", "A")
            .to("b", "B")
            .with_summary("Test")
            .with_action("Task 1", assignee="bot-1")
            .with_action("Task 2", assignee="bot-2")
            .build()
        )
        assert len(packet.actions.pending) == 2
        assert packet.actions.pending[0].id == "a1"
        assert packet.actions.pending[1].id == "a2"

    def test_parent_packet_id(self):
        """Can set parent_packet_id for chained handoffs."""
        from uuid import uuid4
        parent_id = str(uuid4())
        packet = (
            PacketBuilder()
            .from_("a", "A")
            .to("b", "B")
            .with_summary("Chained")
            .with_parent(parent_id)
            .build()
        )
        assert str(packet.parent_packet_id) == parent_id

    def test_missing_source_agent_raises(self):
        """Building without .from_() should raise ValueError."""
        with pytest.raises(ValueError, match="Source agent"):
            PacketBuilder().to("b", "B").with_summary("Test").build()

    def test_missing_target_agent_raises(self):
        """Building without .to() should raise ValueError."""
        with pytest.raises(ValueError, match="Target agent"):
            PacketBuilder().from_("a", "A").with_summary("Test").build()

    def test_missing_summary_raises(self):
        """Building without .with_summary() should raise ValueError."""
        with pytest.raises(ValueError, match="Summary"):
            PacketBuilder().from_("a", "A").to("b", "B").build()

    def test_with_custom_context(self):
        """Custom context fields are preserved."""
        packet = (
            PacketBuilder()
            .from_("a", "A")
            .to("b", "B")
            .with_summary("Custom test")
            .with_custom({"llm": "gpt-4", "temperature": 0.7})
            .build()
        )
        assert packet.context.custom["llm"] == "gpt-4"
        assert packet.context.custom["temperature"] == 0.7

    def test_with_artifacts(self):
        """Artifacts are correctly added."""
        packet = (
            PacketBuilder()
            .from_("a", "A")
            .to("b", "B")
            .with_summary("Test")
            .with_artifacts([{"key": "draft_email", "value": "Hello..."}])
            .build()
        )
        assert len(packet.context.artifacts) == 1
        assert packet.context.artifacts[0].key == "draft_email"

    def test_hitl_with_options_and_timeout(self):
        """HITL checkpoint with options and timeout."""
        packet = (
            PacketBuilder()
            .from_("a", "A")
            .to("b", "B")
            .with_summary("Approval needed")
            .with_hitl(
                reason="Refund approval required",
                question="Approve refund?",
                options=["Approve", "Deny"],
                timeout_seconds=86400,
            )
            .build()
        )
        assert packet.hitl is not None
        assert packet.hitl.options == ["Approve", "Deny"]
        assert packet.hitl.timeout_seconds == 86400

    def test_to_dict_roundtrip(self):
        """Build and convert to dict — should be serializable."""
        packet = (
            PacketBuilder()
            .from_("a", "A", framework="test")
            .to("b", "B")
            .with_summary("Roundtrip test")
            .with_priority("high")
            .build()
        )
        d = packet.to_dict()
        assert d["metadata"]["source_agent"]["id"] == "a"
        assert d["context"]["summary"] == "Roundtrip test"
        assert d["metadata"]["priority"] == "high"


# ── ChainBuilder ─────────────────────────────────────────────────────────────


class TestChainBuilder:
    def test_minimal_chain(self):
        """Chain builder with required fields."""
        request = (
            ChainBuilder()
            .from_("agent-a", "Agent A")
            .to("agent-b", "Agent B")
            .with_summary("Follow-up work")
            .build()
        )
        assert isinstance(request, ChainHandoffRequest)
        assert request.metadata.source_agent.id == "agent-a"
        assert request.metadata.target_agent.id == "agent-b"
        assert request.context.summary == "Follow-up work"

    def test_chain_with_extras(self):
        """Chain builder with decision, action, dependency, and HITL."""
        request = (
            ChainBuilder()
            .from_("billing-01", "BillingBot")
            .to("followup-01", "FollowUpBot")
            .with_summary("Follow-up after billing")
            .with_priority("normal")
            .with_decision("Send receipt", rationale="Customer requested it")
            .with_action("Email receipt", assignee="followup-01")
            .with_dependency("smtp", type="api", description="Email service")
            .with_hitl(reason="Confirm email address", question="Is this the right email?")
            .build()
        )
        assert len(request.decisions) == 1
        assert len(request.actions.pending) == 1
        assert len(request.dependencies) == 1
        assert request.hitl is not None

    def test_missing_source_raises(self):
        with pytest.raises(ValueError, match="Source agent"):
            ChainBuilder().to("b", "B").with_summary("Test").build()

    def test_missing_target_raises(self):
        with pytest.raises(ValueError, match="Target agent"):
            ChainBuilder().from_("a", "A").with_summary("Test").build()

    def test_missing_summary_raises(self):
        with pytest.raises(ValueError, match="Summary"):
            ChainBuilder().from_("a", "A").to("b", "B").build()

    def test_to_dict_roundtrip(self):
        """Chain builder produces serializable output."""
        request = (
            ChainBuilder()
            .from_("a", "A")
            .to("b", "B")
            .with_summary("Chain roundtrip")
            .build()
        )
        d = request.to_dict()
        assert d["metadata"]["source_agent"]["id"] == "a"
        assert d["context"]["summary"] == "Chain roundtrip"
