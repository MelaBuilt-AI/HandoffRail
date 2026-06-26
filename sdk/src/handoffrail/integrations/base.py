"""HandoffRail integrations — adapter base class.

Provides the abstract interface that every framework adapter must implement.
This reduces duplication between the LangChain and CrewAI adapters and
makes it easy to add support for new frameworks.

Usage::

    from handoffrail.integrations.base import BaseAdapter

    class MyAdapter(BaseAdapter):
        def extract_conversation(self, context) -> list[dict]:
            ...
        def resume_conversation(self, packet) -> Any:
            ...

    adapter = MyAdapter(client=my_client, agent_id="my-agent", agent_name="MyBot")
    packet = adapter.create_handoff(target_agent_id="other-01", target_agent_name="OtherBot", summary="...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from handoffrail.sdk.client import HandoffRailClient
from handoffrail.sdk.models import (
    Actions,
    AgentInfo,
    Artifact,
    ContextEntry,
    Decision,
    Dependency,
    HitlCheckpoint,
    Metadata,
    PacketContext,
    PacketCreate,
    PacketResponse,
    PacketStatus,
    PendingAction,
    Priority,
    TargetAgentInfo,
)


class BaseAdapter(ABC):
    """Abstract base class for HandoffRail framework adapters.

    Subclasses must implement ``extract_conversation`` and
    ``resume_conversation``.  All other methods (create_handoff,
    claim_handoff, update_handoff, complete_handoff, get_handoff) are
    provided with sensible defaults that delegate to the SDK client.

    Args:
        client: An initialized HandoffRailClient (sync).
        agent_id: Unique identifier for this agent.
        agent_name: Human-readable name for this agent.
        framework: Framework identifier (e.g. ``"langchain"``, ``"crewai"``).
    """

    def __init__(
        self,
        client: HandoffRailClient,
        agent_id: str,
        agent_name: str,
        framework: str | None = None,
    ) -> None:
        self.client = client
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.framework = framework or self._default_framework()

    # ── Abstract methods (framework-specific) ──────────────────────────────

    @abstractmethod
    def extract_conversation(self, context: Any) -> list[dict[str, Any]]:
        """Extract conversation turns from a framework-specific context.

        Args:
            context: Framework-specific conversation or message history object.

        Returns:
            A list of dicts with at least ``role`` and ``content`` keys,
            suitable for constructing :class:`ContextEntry` objects.
        """

    @abstractmethod
    def resume_conversation(self, packet: PacketResponse) -> Any:
        """Convert a handoff packet back into a framework-specific input format.

        Args:
            packet: The received handoff packet.

        Returns:
            A framework-specific object (e.g. a LangChain message list
            or a CrewAI task input dict) that the agent can use to
            resume work from where the previous agent left off.
        """

    def _default_framework(self) -> str:
        """Return a default framework identifier. Override in subclasses."""
        return "custom"

    # ── Shared handoff methods ────────────────────────────────────────────

    def create_handoff(
        self,
        target_agent_id: str,
        target_agent_name: str,
        summary: str,
        *,
        target_framework: str | None = None,
        priority: str | Priority = "normal",
        tags: list[str] | None = None,
        conversation_state: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        decisions: list[dict[str, Any]] | None = None,
        pending_actions: list[dict[str, Any]] | None = None,
        dependencies: list[dict[str, Any]] | None = None,
        hitl: dict[str, Any] | None = None,
        custom: dict[str, Any] | None = None,
    ) -> PacketResponse:
        """Create a handoff packet from this agent to another agent (or human).

        Args:
            target_agent_id: ID of the receiving agent.
            target_agent_name: Human-readable name of the receiving agent.
            summary: Natural-language summary of work so far.
            target_framework: Framework of the target agent (optional).
            priority: Packet priority (``"low"``, ``"normal"``, ``"high"``, ``"critical"``).
            tags: Freeform tags for filtering.
            conversation_state: Conversation turns (list of dicts with role/content).
            artifacts: Named artifacts produced during the session.
            decisions: Decisions made during the session.
            pending_actions: Actions still pending for the target agent.
            dependencies: External dependencies the target should know about.
            hitl: HITL checkpoint dict (required, reason, question, etc.).
            custom: Framework-specific custom context fields.

        Returns:
            The created :class:`PacketResponse`.
        """
        if isinstance(priority, str):
            priority = Priority(priority)

        source_agent = AgentInfo(
            id=self.agent_id,
            name=self.agent_name,
            framework=self.framework,
        )
        target_agent = TargetAgentInfo(
            id=target_agent_id,
            name=target_agent_name,
            framework=target_framework,
        )
        metadata = Metadata(
            source_agent=source_agent,
            target_agent=target_agent,
            priority=priority,
            tags=tags or [],
        )

        conv_entries = []
        if conversation_state:
            conv_entries = [ContextEntry.from_dict(m) for m in conversation_state]

        artifact_entries = []
        if artifacts:
            artifact_entries = [Artifact.from_dict(a) for a in artifacts]

        context = PacketContext(
            summary=summary,
            conversation_state=conv_entries,
            artifacts=artifact_entries,
            custom=custom or {},
        )

        decision_entries = []
        if decisions:
            decision_entries = [Decision.from_dict(d) for d in decisions]

        pending_action_entries = []
        if pending_actions:
            pending_action_entries = [PendingAction.from_dict(a) for a in pending_actions]

        actions = Actions(
            pending=pending_action_entries,
            completed=[],
            failed=[],
        )

        dep_entries = []
        if dependencies:
            dep_entries = [Dependency.from_dict(d) for d in dependencies]

        hitl_obj = HitlCheckpoint.from_dict(hitl) if hitl else None

        packet = PacketCreate(
            metadata=metadata,
            context=context,
            decisions=decision_entries,
            actions=actions,
            dependencies=dep_entries,
            hitl=hitl_obj,
        )

        return self.client.create_packet(packet)

    def claim_handoff(
        self,
        packet_id: str | UUID,
        *,
        framework: str | None = None,
    ) -> PacketResponse:
        """Claim an available handoff packet.

        Args:
            packet_id: The packet UUID to claim.
            framework: Override the framework identifier sent with the claim.

        Returns:
            The claimed packet.
        """
        return self.client.claim_packet(
            packet_id,
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            framework=framework or self.framework,
        )

    def update_handoff(
        self,
        packet_id: str | UUID,
        *,
        status: str | PacketStatus | None = None,
        decisions: list[dict[str, Any]] | None = None,
        pending_actions: list[dict[str, Any]] | None = None,
        completed_actions: list[dict[str, Any]] | None = None,
        failed_actions: list[dict[str, Any]] | None = None,
        dependencies: list[dict[str, Any]] | None = None,
        summary: str | None = None,
        custom: dict[str, Any] | None = None,
    ) -> PacketResponse:
        """Update a handoff packet with progress or new information.

        Args:
            packet_id: The packet UUID.
            status: New status for the packet.
            decisions: New decisions to add.
            pending_actions: New pending actions.
            completed_actions: Actions marked as completed.
            failed_actions: Actions that have failed.
            dependencies: New or updated dependencies.
            summary: Updated context summary.
            custom: Updated custom context fields.

        Returns:
            The updated packet.
        """
        from handoffrail.sdk.models import PacketUpdate

        update_kwargs: dict[str, Any] = {}

        if status is not None:
            if isinstance(status, str):
                status = PacketStatus(status)
            update_kwargs["status"] = status

        if decisions:
            update_kwargs["decisions"] = [Decision.from_dict(d) for d in decisions]

        if any((pending_actions, completed_actions, failed_actions)):
            actions = Actions(
                pending=[PendingAction.from_dict(a) for a in pending_actions] if pending_actions else [],
                completed=[CompletedAction.from_dict(a) for a in completed_actions] if completed_actions else [],
                failed=[FailedAction.from_dict(a) for a in failed_actions] if failed_actions else [],
            )
            update_kwargs["actions"] = actions

        if dependencies:
            update_kwargs["dependencies"] = [Dependency.from_dict(d) for d in dependencies]

        if summary is not None or custom is not None:
            # For partial context updates we need the existing packet context
            # plus the new summary/custom
            current = self.client.get_packet(packet_id)
            context = current.context
            if summary is not None:
                context = PacketContext(
                    summary=summary,
                    conversation_state=context.conversation_state,
                    artifacts=context.artifacts,
                    custom=custom if custom is not None else context.custom,
                )
            elif custom is not None:
                merged_custom = {**context.custom, **custom}
                context = PacketContext(
                    summary=context.summary,
                    conversation_state=context.conversation_state,
                    artifacts=context.artifacts,
                    custom=merged_custom,
                )
            update_kwargs["context"] = context

        update = PacketUpdate(**update_kwargs)
        return self.client.update_packet(packet_id, update)

    def complete_handoff(self, packet_id: str | UUID) -> PacketResponse:
        """Mark a handoff packet as completed.

        Args:
            packet_id: The packet UUID.

        Returns:
            The completed packet.
        """
        return self.client.complete_packet(packet_id)

    def get_handoff(self, packet_id: str | UUID) -> PacketResponse:
        """Retrieve a handoff packet by ID.

        Args:
            packet_id: The packet UUID.

        Returns:
            The packet.
        """
        return self.client.get_packet(packet_id)

    def poll_for_handoff(
        self,
        *,
        status: str = "created",
        target_agent: str | None = None,
        limit: int = 10,
    ) -> list[PacketResponse]:
        """Poll for available handoff packets matching the given criteria.

        Args:
            status: Filter by status (default ``"created"``).
            target_agent: Filter by target agent ID.
            limit: Max results to return.

        Returns:
            List of matching packets.
        """
        result = self.client.list_packets(
            status=status,
            target_agent=target_agent or self.agent_id,
            limit=limit,
        )
        return result.packets

    def respond_to_hitl(
        self,
        packet_id: str | UUID,
        response: str,
        *,
        responded_by: str | None = None,
        notes: str | None = None,
    ) -> PacketResponse:
        """Submit a human response to a HITL checkpoint.

        Args:
            packet_id: The packet UUID.
            response: The response text.
            responded_by: Identifier for the responder (defaults to agent ID).
            notes: Optional notes.

        Returns:
            The updated packet.
        """
        return self.client.respond_to_hitl(
            packet_id,
            response=response,
            responded_by=responded_by or self.agent_id,
            notes=notes,
        )

    def chain_handoff(
        self,
        parent_packet_id: str | UUID,
        target_agent_id: str,
        target_agent_name: str,
        summary: str,
        *,
        target_framework: str | None = None,
        priority: str | Priority = "normal",
        tags: list[str] | None = None,
        conversation_state: list[dict[str, Any]] | None = None,
        decisions: list[dict[str, Any]] | None = None,
        pending_actions: list[dict[str, Any]] | None = None,
    ) -> PacketResponse:
        """Create a chained follow-up handoff from an existing packet.

        Args:
            parent_packet_id: The parent packet UUID.
            target_agent_id: ID of the next agent.
            target_agent_name: Name of the next agent.
            summary: Summary for the follow-up packet.
            target_framework: Framework of the next agent.
            priority: Priority for the follow-up.
            tags: Tags for the follow-up.
            conversation_state: Conversation turns for the follow-up.
            decisions: Decisions for the follow-up.
            pending_actions: Pending actions for the follow-up.

        Returns:
            The newly created child packet.
        """
        from handoffrail.sdk.models import ChainHandoffRequest

        if isinstance(priority, str):
            priority = Priority(priority)

        source = AgentInfo(id=self.agent_id, name=self.agent_name, framework=self.framework)
        target = TargetAgentInfo(id=target_agent_id, name=target_agent_name, framework=target_framework)
        metadata = Metadata(source_agent=source, target_agent=target, priority=priority, tags=tags or [])

        conv_entries = [ContextEntry.from_dict(m) for m in conversation_state] if conversation_state else []
        context = PacketContext(summary=summary, conversation_state=conv_entries)
        decision_entries = [Decision.from_dict(d) for d in decisions] if decisions else []
        action_entries = [PendingAction.from_dict(a) for a in pending_actions] if pending_actions else []
        actions = Actions(pending=action_entries, completed=[], failed=[])

        request = ChainHandoffRequest(
            metadata=metadata,
            context=context,
            decisions=decision_entries,
            actions=actions,
        )
        return self.client.chain_handoff(parent_packet_id, request)


# Import here to avoid circular imports at module level — these are used
# inside update_handoff which may not be called in every session.
from handoffrail.sdk.models import CompletedAction, FailedAction  # noqa: E402
