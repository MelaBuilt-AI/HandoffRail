"""HandoffRail integration for CrewAI.

Provides:
- :class:`CrewAIAdapter` — High-level adapter for creating/receiving handoffs
  within CrewAI workflows.
- :class:`HandoffRailCrewAITool` — CrewAI BaseTool subclass that exposes handoff
  operations as agent-callable tools.

``crewai`` is an optional dependency.  Import this module only when CrewAI is
installed (``pip install handoffrail-sdk[crewai]``).
"""

from __future__ import annotations

import json
from typing import Any

try:
    from crewai.tools import BaseTool as CrewAIBaseTool

    _CREWAI_AVAILABLE = True
except ImportError:
    try:
        # Older CrewAI versions
        from crewai.tools.tool import Tool as CrewAIBaseTool  # type: ignore[no-redef]

        _CREWAI_AVAILABLE = True
    except ImportError:
        _CREWAI_AVAILABLE = False

from handoffrail.integrations.base import BaseAdapter
from handoffrail.sdk.client import HandoffRailClient
from handoffrail.sdk.exceptions import HandoffRailError
from handoffrail.sdk.models import PacketResponse


def _require_crewai() -> None:
    """Raise ImportError if CrewAI is not installed."""
    if not _CREWAI_AVAILABLE:
        msg = (
            "CrewAI is required for this integration. "
            "Install it with: pip install handoffrail-sdk[crewai]"
        )
        raise ImportError(msg)


class CrewAIAdapter(BaseAdapter):
    """HandoffRail adapter for CrewAI agents.

    Provides CrewAI-specific task completion handoff and packet-to-task
    input conversion.

    Args:
        client: An initialized :class:`HandoffRailClient`.
        agent_id: Unique identifier for this agent.
        agent_name: Human-readable name for this agent.
        framework: Framework identifier (defaults to ``"crewai"``).

    Example::

        from handoffrail.sdk import HandoffRailClient
        from handoffrail.integrations.crewai import CrewAIAdapter

        client = HandoffRailClient(base_url="http://localhost:8080/api/v1", api_key="hr_...")
        adapter = CrewAIAdapter(client=client, agent_id="billing-01", agent_name="BillingBot")

        # Create a handoff from a completed task
        packet = adapter.handoff_from_task(
            task_result="Payment processed successfully",
            target_agent_id="support-01",
            target_agent_name="SupportBot",
            summary="Billing complete, customer needs onboarding",
        )

        # Poll for available handoffs
        packets = adapter.poll_for_handoff()
        if packets:
            claimed = adapter.claim_handoff(packets[0].id)
            task_input = adapter.packet_to_task_input(claimed)
    """

    def __init__(
        self,
        client: HandoffRailClient,
        agent_id: str,
        agent_name: str,
        framework: str = "crewai",
    ) -> None:
        super().__init__(client=client, agent_id=agent_id, agent_name=agent_name, framework=framework)

    def _default_framework(self) -> str:
        return "crewai"

    def extract_conversation(self, context: Any) -> list[dict[str, Any]]:
        """Extract conversation turns from a CrewAI task or context.

        Accepts:
        - A list of dicts with ``role`` and ``content`` keys
        - A string (treated as a single agent message)
        - A CrewAI Task object (extracts description as system message)

        Returns:
            A list of dicts with ``role`` and ``content`` keys.
        """
        if isinstance(context, list):
            if len(context) == 0:
                return []
            first = context[0]
            if isinstance(first, dict):
                return self._extract_from_dicts(context)
            # List of strings
            return [{"role": "agent", "content": str(item)} for item in context]

        if isinstance(context, str):
            return [{"role": "agent", "content": context}]

        # CrewAI Task-like object
        if hasattr(context, "description"):
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": f"Task: {context.description}"}
            ]
            if hasattr(context, "expected_output") and context.expected_output:
                messages.append({"role": "system", "content": f"Expected output: {context.expected_output}"})
            return messages

        return []

    def _extract_from_dicts(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize dicts for CrewAI context."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "system")
            # Normalize CrewAI-style roles
            role_map = {
                "human": "user",
                "ai": "agent",
                "assistant": "agent",
                "task": "system",
            }
            mapped_role = role_map.get(role, role)
            entry: dict[str, Any] = {"role": mapped_role, "content": msg.get("content", "")}
            if "timestamp" in msg:
                entry["timestamp"] = msg["timestamp"]
            result.append(entry)
        return result

    def resume_conversation(self, packet: PacketResponse) -> dict[str, Any]:
        """Convert a handoff packet to a CrewAI task input dict.

        Returns a dict with keys suitable for passing as task context to
        a CrewAI agent, including ``summary``, ``conversation``, ``pending_actions``,
        and ``decisions``.

        Args:
            packet: The received handoff packet.

        Returns:
            Dict with task-relevant fields.
        """
        conversation: list[dict[str, str]] = []
        for entry in packet.context.conversation_state:
            role = entry.role.value if hasattr(entry.role, "value") else str(entry.role)
            conversation.append({"role": role, "content": entry.content})

        pending_actions: list[dict[str, str]] = []
        for action in packet.actions.pending:
            action_dict: dict[str, str] = {
                "id": action.id,
                "description": action.description,
                "assignee": action.assignee,
            }
            pending_actions.append(action_dict)

        decisions: list[dict[str, str]] = []
        for d in packet.decisions:
            decisions.append({
                "id": d.id,
                "decision": d.decision,
                "rationale": d.rationale,
            })

        result: dict[str, Any] = {
            "summary": packet.context.summary,
            "conversation": conversation,
            "pending_actions": pending_actions,
            "decisions": decisions,
            "source_agent": packet.metadata.source_agent.name,
            "source_agent_id": packet.metadata.source_agent.id,
            "priority": packet.metadata.priority.value if hasattr(packet.metadata.priority, "value") else str(packet.metadata.priority),
        }

        if packet.hitl and packet.hitl.required:
            result["hitl_required"] = True
            result["hitl_question"] = packet.hitl.question or ""
            result["hitl_options"] = packet.hitl.options or []

        if packet.context.artifacts:
            result["artifacts"] = {a.key: a.value for a in packet.context.artifacts}

        return result

    def handoff_from_task(
        self,
        task_result: str,
        target_agent_id: str,
        target_agent_name: str,
        summary: str,
        *,
        target_framework: str | None = None,
        priority: str = "normal",
        tags: list[str] | None = None,
        decisions: list[dict[str, Any]] | None = None,
        pending_actions: list[dict[str, Any]] | None = None,
    ) -> PacketResponse:
        """Create a handoff packet from a CrewAI task completion.

        Convenience method that wraps :meth:`create_handoff` with CrewAI-style
        defaults, automatically including the task result as a conversation turn.

        Args:
            task_result: The result/output of the completed task.
            target_agent_id: ID of the next agent.
            target_agent_name: Name of the next agent.
            summary: Summary of what was done and what needs to happen next.
            target_framework: Framework of the target agent.
            priority: Packet priority.
            tags: Tags for filtering.
            decisions: Decisions made during the task.
            pending_actions: Actions still pending for the next agent.

        Returns:
            The created packet.
        """
        conversation_state = [
            {"role": "agent", "content": f"Task result: {task_result}"},
        ]

        return self.create_handoff(
            target_agent_id=target_agent_id,
            target_agent_name=target_agent_name,
            summary=summary,
            target_framework=target_framework,
            priority=priority,
            tags=tags,
            conversation_state=conversation_state,
            decisions=decisions,
            pending_actions=pending_actions,
        )


if _CREWAI_AVAILABLE:

    class HandoffRailCrewAITool(CrewAIBaseTool):
        """CrewAI tool that exposes HandoffRail operations to CrewAI agents.

        Allows a CrewAI agent to create, claim, update, complete, and get
        handoff packets using the standard CrewAI tool interface.

        Args:
            client: An initialized :class:`HandoffRailClient`.
            name: Tool name (default ``"handoffrail"``).
            description: Tool description for the agent.

        Example::

            from handoffrail.integrations.crewai import HandoffRailCrewAITool

            tool = HandoffRailCrewAITool(client=my_client)
            # Add to agent's tool list
        """

        def __init__(
            self,
            client: HandoffRailClient,
            name: str = "handoffrail",
            description: str | None = None,
            **kwargs: Any,
        ) -> None:
            self._hr_client = client
            if description is None:
                description = (
                    "HandoffRail session-continuity tool. "
                    "Actions: create, claim, update, complete, get. "
                    "Use this to create handoff packets for other agents, "
                    "claim available handoffs, update handoff status, "
                    "mark handoffs as completed, or retrieve handoff details."
                )
            # CrewAI BaseTool uses different constructor patterns depending on version
            # We store our config and call super().__init__ appropriately
            try:
                super().__init__(name=name, description=description, **kwargs)
            except TypeError:
                # Some CrewAI versions don't accept name/description in __init__
                try:
                    super().__init__(**kwargs)
                except Exception:
                    super().__init__()

        def _run(self, action: str, **kwargs: Any) -> str:
            """Execute a handoff action.

            Args:
                action: One of ``create``, ``claim``, ``update``, ``complete``, ``get``.

            Returns:
                JSON string with the result.
            """
            try:
                if action == "create":
                    return self._handle_create(**kwargs)
                elif action == "claim":
                    return self._handle_claim(**kwargs)
                elif action == "update":
                    return self._handle_update(**kwargs)
                elif action == "complete":
                    return self._handle_complete(**kwargs)
                elif action == "get":
                    return self._handle_get(**kwargs)
                else:
                    return json.dumps({"error": f"Unknown action: {action}. Use: create, claim, update, complete, get"})
            except HandoffRailError as exc:
                return json.dumps({"error": str(exc), "error_type": type(exc).__name__})
            except Exception as exc:
                return json.dumps({"error": str(exc)})

        def _handle_create(self, **kwargs: Any) -> str:
            from handoffrail.sdk.models import PacketCreate

            target_agent_id = kwargs.get("target_agent_id")
            target_agent_name = kwargs.get("target_agent_name")
            summary = kwargs.get("summary")

            if not target_agent_id or not target_agent_name or not summary:
                return json.dumps({"error": "create requires target_agent_id, target_agent_name, and summary"})

            source_agent_id = kwargs.get("agent_id", "unknown")
            source_agent_name = kwargs.get("agent_name", "Unknown")
            priority = kwargs.get("priority", "normal")
            tags = kwargs.get("tags", "").split(",") if isinstance(kwargs.get("tags"), str) else kwargs.get("tags", [])

            packet = self._hr_client.create_packet(
                PacketCreate.from_dict({
                    "metadata": {
                        "source_agent": {"id": source_agent_id, "name": source_agent_name},
                        "target_agent": {"id": target_agent_id, "name": target_agent_name},
                        "priority": priority,
                        "tags": tags,
                    },
                    "context": {"summary": summary, "conversation_state": [], "artifacts": [], "custom": {}},
                    "decisions": [],
                    "actions": {"pending": [], "completed": [], "failed": []},
                    "dependencies": [],
                    "hitl": None,
                })
            )
            return json.dumps({"status": "created", "packet_id": str(packet.id)})

        def _handle_claim(self, **kwargs: Any) -> str:
            packet_id = kwargs.get("packet_id")
            if not packet_id:
                return json.dumps({"error": "claim requires packet_id"})

            result = self._hr_client.claim_packet(
                packet_id,
                agent_id=kwargs.get("agent_id", "unknown"),
                agent_name=kwargs.get("agent_name", "Unknown"),
            )
            return json.dumps({"status": "claimed", "packet_id": str(result.id)})

        def _handle_update(self, **kwargs: Any) -> str:
            from handoffrail.sdk.models import PacketUpdate

            packet_id = kwargs.get("packet_id")
            if not packet_id:
                return json.dumps({"error": "update requires packet_id"})

            update_kwargs: dict[str, Any] = {}
            status = kwargs.get("status")
            if status:
                update_kwargs["status"] = status
            summary = kwargs.get("summary")
            if summary:
                from handoffrail.sdk.models import PacketContext
                update_kwargs["context"] = PacketContext(summary=summary, conversation_state=[])

            update = PacketUpdate(**update_kwargs)
            result = self._hr_client.update_packet(packet_id, update)
            return json.dumps({"status": "updated", "packet_id": str(result.id)})

        def _handle_complete(self, **kwargs: Any) -> str:
            packet_id = kwargs.get("packet_id")
            if not packet_id:
                return json.dumps({"error": "complete requires packet_id"})

            result = self._hr_client.complete_packet(packet_id)
            return json.dumps({"status": "completed", "packet_id": str(result.id)})

        def _handle_get(self, **kwargs: Any) -> str:
            packet_id = kwargs.get("packet_id")
            if not packet_id:
                return json.dumps({"error": "get requires packet_id"})

            result = self._hr_client.get_packet(packet_id)
            status = result.status.value if hasattr(result.status, "value") else str(result.status)
            return json.dumps({"packet_id": str(result.id), "status": status})

else:

    class HandoffRailCrewAITool:  # type: ignore[no-redef]
        """CrewAI tool stub — requires crewai package."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _require_crewai()
