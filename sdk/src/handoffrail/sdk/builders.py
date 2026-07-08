"""HandoffRail SDK — Fluent builder pattern for constructing packets and chains.

Usage:
    packet_data = (
        PacketBuilder()
        .to("billing-01", "BillingBot", framework="crewai")
        .from_("sales-01", "SalesBot", framework="langchain")
        .with_summary("Customer wants Business tier")
        .with_priority("high")
        .with_tags(["upgrade", "business"])
        .with_conversation([{"role": "user", "content": "I want to upgrade"}])
        .with_decision("Proceed", rationale="Customer is eligible")
        .with_action("Process payment", assignee="billing-01", priority="high")
        .with_dependency("stripe", type="api", description="Payment gateway")
        .with_hitl(reason="High-value upgrade needs approval", question="Approve?")
        .build()
    )

    chain_data = (
        ChainBuilder(parent_packet_id="abc-123")
        .to("followup-01", "FollowUpBot")
        .from_("billing-01", "BillingBot")
        .with_summary("Follow up on upgrade")
        .build()
    )
"""

from __future__ import annotations

from typing import Any

from handoffrail.sdk.models import (
    Actions,
    AgentInfo,
    Artifact,
    ChainHandoffRequest,
    ContextEntry,
    Decision,
    Dependency,
    HitlCheckpoint,
    Metadata,
    PacketContext,
    PacketCreate,
    PendingAction,
    Priority,
    TargetAgentInfo,
)


class PacketBuilder:
    """Fluent builder for constructing PacketCreate payloads.

    Each method returns ``self`` so calls can be chained.  Call ``build()``
    at the end to get a validated :class:`PacketCreate` instance.
    """

    def __init__(self) -> None:
        self._source_id: str | None = None
        self._source_name: str | None = None
        self._source_framework: str | None = None
        self._source_version: str | None = None
        self._target_id: str | None = None
        self._target_name: str | None = None
        self._target_framework: str | None = None
        self._summary: str | None = None
        self._priority: Priority = Priority.normal
        self._tags: list[str] = []
        self._conversation_state: list[dict[str, Any]] = []
        self._artifacts: list[dict[str, Any]] = []
        self._custom: dict[str, Any] = {}
        self._decisions: list[dict[str, Any]] = []
        self._pending_actions: list[dict[str, Any]] = []
        self._completed_actions: list[dict[str, Any]] = []
        self._failed_actions: list[dict[str, Any]] = []
        self._dependencies: list[dict[str, Any]] = []
        self._hitl: dict[str, Any] | None = None
        self._parent_packet_id: str | None = None

    # ── Agent setters ─────────────────────────────────────────────────────

    def from_(
        self,
        agent_id: str,
        agent_name: str,
        *,
        framework: str | None = None,
        version: str | None = None,
    ) -> PacketBuilder:
        """Set the source (sending) agent."""
        self._source_id = agent_id
        self._source_name = agent_name
        self._source_framework = framework
        self._source_version = version
        return self

    def to(self, agent_id: str, agent_name: str, *, framework: str | None = None) -> PacketBuilder:
        """Set the target (receiving) agent."""
        self._target_id = agent_id
        self._target_name = agent_name
        self._target_framework = framework
        return self

    # ── Context setters ───────────────────────────────────────────────────

    def with_summary(self, summary: str) -> PacketBuilder:
        """Set the context summary."""
        self._summary = summary
        return self

    def with_priority(self, priority: str | Priority) -> PacketBuilder:
        """Set the packet priority ('low', 'normal', 'high', 'critical')."""
        if isinstance(priority, str):
            priority = Priority(priority)
        self._priority = priority
        return self

    def with_tags(self, tags: list[str]) -> PacketBuilder:
        """Set tags for filtering."""
        self._tags = list(tags)
        return self

    def with_conversation(self, messages: list[dict[str, Any]]) -> PacketBuilder:
        """Set the conversation state from a list of message dicts.

        Each dict should have at least ``role`` and ``content`` keys.
        """
        self._conversation_state = list(messages)
        return self

    def with_artifacts(self, artifacts: list[dict[str, Any]]) -> PacketBuilder:
        """Set named artifacts produced during the session."""
        self._artifacts = list(artifacts)
        return self

    def with_custom(self, custom: dict[str, Any]) -> PacketBuilder:
        """Set framework-specific custom context fields."""
        self._custom = dict(custom)
        return self

    # ── Decision / Action / Dependency helpers ────────────────────────────

    def with_decision(
        self,
        decision: str,
        *,
        rationale: str = "",
        alternatives: list[str] | None = None,
        decided_by: str | None = None,
    ) -> PacketBuilder:
        """Add a decision to the packet. An auto-incrementing ID is assigned."""
        decision_id = f"d{len(self._decisions) + 1}"
        entry: dict[str, Any] = {
            "id": decision_id,
            "decision": decision,
            "rationale": rationale,
        }
        if alternatives:
            entry["alternatives"] = alternatives
        if decided_by:
            entry["decided_by"] = decided_by
        self._decisions.append(entry)
        return self

    def with_action(
        self,
        description: str,
        *,
        assignee: str,
        priority: str | Priority | None = None,
        depends_on: list[str] | None = None,
        action_id: str | None = None,
    ) -> PacketBuilder:
        """Add a pending action to the packet."""
        aid = action_id or f"a{len(self._pending_actions) + 1}"
        entry: dict[str, Any] = {
            "id": aid,
            "description": description,
            "assignee": assignee,
        }
        if priority:
            entry["priority"] = priority.value if isinstance(priority, Priority) else priority
        if depends_on:
            entry["depends_on"] = depends_on
        self._pending_actions.append(entry)
        return self

    def with_dependency(
        self,
        dep_id: str,
        *,
        type: str = "api",
        description: str = "",
        status: str = "unknown",
        source: str | None = None,
    ) -> PacketBuilder:
        """Add an external dependency."""
        entry: dict[str, Any] = {
            "id": dep_id,
            "type": type,
            "description": description,
            "status": status,
        }
        if source:
            entry["source"] = source
        self._dependencies.append(entry)
        return self

    # ── HITL ──────────────────────────────────────────────────────────────

    def with_hitl(
        self,
        *,
        reason: str,
        question: str | None = None,
        options: list[str] | None = None,
        timeout_seconds: int | None = None,
    ) -> PacketBuilder:
        """Add a human-in-the-loop checkpoint."""
        self._hitl = {
            "required": True,
            "reason": reason,
        }
        if question:
            self._hitl["question"] = question
        if options:
            self._hitl["options"] = options
        if timeout_seconds is not None:
            self._hitl["timeout_seconds"] = timeout_seconds
        return self

    # ── Parent ─────────────────────────────────────────────────────────────

    def with_parent(self, parent_packet_id: str) -> PacketBuilder:
        """Set the parent packet ID for chained handoffs."""
        self._parent_packet_id = parent_packet_id
        return self

    # ── Build ──────────────────────────────────────────────────────────────

    def build(self) -> PacketCreate:
        """Validate accumulated data and return a PacketCreate instance.

        Raises:
            ValueError: If required fields (source agent, target agent, summary) are missing.
        """
        if self._source_id is None or self._source_name is None:
            msg = "Source agent is required. Call .from_() before .build()."
            raise ValueError(msg)
        if self._target_id is None or self._target_name is None:
            msg = "Target agent is required. Call .to() before .build()."
            raise ValueError(msg)
        if self._summary is None:
            msg = "Summary is required. Call .with_summary() before .build()."
            raise ValueError(msg)

        source_agent = AgentInfo(
            id=self._source_id,
            name=self._source_name,
            framework=self._source_framework,
            version=self._source_version,
        )
        target_agent = TargetAgentInfo(
            id=self._target_id,
            name=self._target_name,
            framework=self._target_framework,
        )
        metadata = Metadata(
            source_agent=source_agent,
            target_agent=target_agent,
            priority=self._priority,
            tags=self._tags,
        )

        conversation_state = [ContextEntry.from_dict(m) for m in self._conversation_state]
        artifacts = [Artifact.from_dict(a) for a in self._artifacts]

        context = PacketContext(
            summary=self._summary,
            conversation_state=conversation_state,
            artifacts=artifacts,
            custom=self._custom,
        )

        decisions = [Decision.from_dict(d) for d in self._decisions]
        actions = Actions(
            pending=[PendingAction.from_dict(a) for a in self._pending_actions],
            completed=[],
            failed=[],
        )
        dependencies = [Dependency.from_dict(d) for d in self._dependencies]
        hitl = HitlCheckpoint.from_dict(self._hitl) if self._hitl else None

        return PacketCreate(
            parent_packet_id=self._parent_packet_id,
            metadata=metadata,
            context=context,
            decisions=decisions,
            actions=actions,
            dependencies=dependencies,
            hitl=hitl,
        )


class ChainBuilder:
    """Fluent builder for constructing ChainHandoffRequest payloads.

    Similar to PacketBuilder but produces a ChainHandoffRequest (no
    ``parent_packet_id`` — that is provided as a separate argument to
    the client method).
    """

    def __init__(self) -> None:
        self._source_id: str | None = None
        self._source_name: str | None = None
        self._source_framework: str | None = None
        self._target_id: str | None = None
        self._target_name: str | None = None
        self._target_framework: str | None = None
        self._summary: str | None = None
        self._priority: Priority = Priority.normal
        self._tags: list[str] = []
        self._conversation_state: list[dict[str, Any]] = []
        self._artifacts: list[dict[str, Any]] = []
        self._custom: dict[str, Any] = {}
        self._decisions: list[dict[str, Any]] = []
        self._pending_actions: list[dict[str, Any]] = []
        self._dependencies: list[dict[str, Any]] = []
        self._hitl: dict[str, Any] | None = None

    def from_(self, agent_id: str, agent_name: str, *, framework: str | None = None) -> ChainBuilder:
        self._source_id = agent_id
        self._source_name = agent_name
        self._source_framework = framework
        return self

    def to(self, agent_id: str, agent_name: str, *, framework: str | None = None) -> ChainBuilder:
        self._target_id = agent_id
        self._target_name = agent_name
        self._target_framework = framework
        return self

    def with_summary(self, summary: str) -> ChainBuilder:
        self._summary = summary
        return self

    def with_priority(self, priority: str | Priority) -> ChainBuilder:
        if isinstance(priority, str):
            priority = Priority(priority)
        self._priority = priority
        return self

    def with_tags(self, tags: list[str]) -> ChainBuilder:
        self._tags = list(tags)
        return self

    def with_conversation(self, messages: list[dict[str, Any]]) -> ChainBuilder:
        self._conversation_state = list(messages)
        return self

    def with_decision(
        self,
        decision: str,
        *,
        rationale: str = "",
        decided_by: str | None = None,
    ) -> ChainBuilder:
        decision_id = f"d{len(self._decisions) + 1}"
        entry: dict[str, Any] = {
            "id": decision_id,
            "decision": decision,
            "rationale": rationale,
        }
        if decided_by:
            entry["decided_by"] = decided_by
        self._decisions.append(entry)
        return self

    def with_action(
        self,
        description: str,
        *,
        assignee: str,
        priority: str | Priority | None = None,
    ) -> ChainBuilder:
        aid = f"a{len(self._pending_actions) + 1}"
        entry: dict[str, Any] = {
            "id": aid,
            "description": description,
            "assignee": assignee,
        }
        if priority:
            entry["priority"] = priority.value if isinstance(priority, Priority) else priority
        self._pending_actions.append(entry)
        return self

    def with_dependency(
        self,
        dep_id: str,
        *,
        type: str = "api",
        description: str = "",
    ) -> ChainBuilder:
        entry = {"id": dep_id, "type": type, "description": description, "status": "unknown"}
        self._dependencies.append(entry)
        return self

    def with_hitl(
        self,
        *,
        reason: str,
        question: str | None = None,
        options: list[str] | None = None,
    ) -> ChainBuilder:
        self._hitl = {"required": True, "reason": reason}
        if question:
            self._hitl["question"] = question
        if options:
            self._hitl["options"] = options
        return self

    def build(self) -> ChainHandoffRequest:
        """Validate and return a ChainHandoffRequest."""
        if self._source_id is None or self._source_name is None:
            msg = "Source agent is required. Call .from_() before .build()."
            raise ValueError(msg)
        if self._target_id is None or self._target_name is None:
            msg = "Target agent is required. Call .to() before .build()."
            raise ValueError(msg)
        if self._summary is None:
            msg = "Summary is required. Call .with_summary() before .build()."
            raise ValueError(msg)

        source = AgentInfo(id=self._source_id, name=self._source_name, framework=self._source_framework)
        target = TargetAgentInfo(id=self._target_id, name=self._target_name, framework=self._target_framework)
        metadata = Metadata(source_agent=source, target_agent=target, priority=self._priority, tags=self._tags)

        context = PacketContext(
            summary=self._summary,
            conversation_state=[ContextEntry.from_dict(m) for m in self._conversation_state],
            artifacts=[Artifact.from_dict(a) for a in self._artifacts],
            custom=self._custom,
        )

        decisions = [Decision.from_dict(d) for d in self._decisions]
        actions = Actions(
            pending=[PendingAction.from_dict(a) for a in self._pending_actions],
            completed=[],
            failed=[],
        )
        dependencies = [Dependency.from_dict(d) for d in self._dependencies]
        hitl = HitlCheckpoint.from_dict(self._hitl) if self._hitl else None

        return ChainHandoffRequest(
            metadata=metadata,
            context=context,
            decisions=decisions,
            actions=actions,
            dependencies=dependencies,
            hitl=hitl,
        )
