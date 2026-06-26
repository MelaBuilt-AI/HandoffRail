"""HandoffRail integration for LangChain.

Provides:
- :class:`LangChainAdapter` — High-level adapter for creating/receiving handoffs.
- :class:`HandoffRailCallbackHandler` — LangChain callback handler that auto-tracks
  conversation turns and can create handoff packets on chain completion.
- :class:`HandoffRailTool` — LangChain BaseTool subclass that exposes handoff
  operations as agent-callable tools.

Both ``langchain`` and ``langchain-core`` are optional dependencies.  Import this
module only when LangChain is installed (``pip install handoffrail-sdk[langchain]``).
"""

from __future__ import annotations

import json
from typing import Any

try:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.tools import BaseTool
    from pydantic import BaseModel, Field

    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False

from handoffrail.integrations.base import BaseAdapter
from handoffrail.sdk.client import HandoffRailClient
from handoffrail.sdk.exceptions import HandoffRailError
from handoffrail.sdk.models import PacketCreate, PacketContext, PacketUpdate
from handoffrail.sdk.models import PacketResponse


def _require_langchain() -> None:
    """Raise ImportError if LangChain is not installed."""
    if not _LANGCHAIN_AVAILABLE:
        msg = (
            "LangChain is required for this integration. "
            "Install it with: pip install handoffrail-sdk[langchain]"
        )
        raise ImportError(msg)


class LangChainAdapter(BaseAdapter):
    """HandoffRail adapter for LangChain agents.

    Provides LangChain-specific conversation extraction and resumption.
    Use this when your agent is built on the LangChain framework.

    Args:
        client: An initialized :class:`HandoffRailClient`.
        agent_id: Unique identifier for this agent.
        agent_name: Human-readable name for this agent.
        framework: Framework identifier (defaults to ``"langchain"``).

    Example::

        from handoffrail.sdk import HandoffRailClient
        from handoffrail.integrations.langchain import LangChainAdapter

        client = HandoffRailClient(base_url="http://localhost:8080/api/v1", api_key="hr_...")
        adapter = LangChainAdapter(client=client, agent_id="sales-01", agent_name="SalesBot")

        # Create a handoff
        packet = adapter.create_handoff(
            target_agent_id="billing-01",
            target_agent_name="BillingBot",
            summary="Customer wants to upgrade",
            conversation_state=adapter.extract_conversation(chat_history),
        )

        # Receive a handoff
        packets = adapter.poll_for_handoff()
        if packets:
            claimed = adapter.claim_handoff(packets[0].id)
            messages = adapter.resume_conversation(claimed)
    """

    def __init__(
        self,
        client: HandoffRailClient,
        agent_id: str,
        agent_name: str,
        framework: str = "langchain",
    ) -> None:
        super().__init__(client=client, agent_id=agent_id, agent_name=agent_name, framework=framework)

    def _default_framework(self) -> str:
        return "langchain"

    def extract_conversation(self, context: Any) -> list[dict[str, Any]]:
        """Extract conversation turns from a LangChain message history.

        Accepts:
        - A list of LangChain ``BaseMessage`` objects
        - A list of dicts with ``role`` and ``content`` keys
        - A LangChain ``ChatMessageHistory`` object

        Returns:
            A list of dicts with ``role`` and ``content`` keys, plus optional
            ``timestamp`` and ``metadata``.
        """
        if isinstance(context, list):
            if len(context) == 0:
                return []

            first = context[0]
            # Check if these are LangChain BaseMessage objects
            if hasattr(first, "type") and hasattr(first, "content"):
                return self._extract_from_langchain_messages(context)
            # Assume they are dicts
            if isinstance(first, dict) and ("role" in first or "type" in first):
                return self._extract_from_dicts(context)

        # LangChain ChatMessageHistory or similar
        if hasattr(context, "messages"):
            return self._extract_from_langchain_messages(context.messages)

        # Fallback: try to iterate
        if hasattr(context, "__iter__"):
            return self._extract_from_langchain_messages(list(context))

        return []

    def _extract_from_langchain_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Convert LangChain BaseMessage list to conversation dicts."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.type if hasattr(msg, "type") else "system"
            # LangChain uses "human"/"ai"/"system"/"tool"; we map to our roles
            role_map = {
                "human": "user",
                "ai": "agent",
                "system": "system",
                "tool": "system",
                "function": "system",
            }
            mapped_role = role_map.get(role, role)
            content = msg.content if hasattr(msg, "content") else str(msg)
            entry: dict[str, Any] = {"role": mapped_role, "content": content}
            if hasattr(msg, "additional_kwargs") and msg.additional_kwargs:
                entry["metadata"] = dict(msg.additional_kwargs)
            result.append(entry)
        return result

    def _extract_from_dicts(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize dicts that may use LangChain-style keys."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", msg.get("type", "system"))
            # Normalize role names
            role_map = {
                "human": "user",
                "ai": "agent",
                "assistant": "agent",
                "tool": "system",
                "function": "system",
            }
            mapped_role = role_map.get(role, role)
            entry: dict[str, Any] = {"role": mapped_role, "content": msg.get("content", "")}
            if "timestamp" in msg:
                entry["timestamp"] = msg["timestamp"]
            if "metadata" in msg:
                entry["metadata"] = msg["metadata"]
            result.append(entry)
        return result

    def resume_conversation(self, packet: PacketResponse) -> list[dict[str, str]]:
        """Convert a handoff packet back into LangChain-compatible message dicts.

        Returns a list of dicts with ``role`` and ``content`` keys, ready to
        be passed to a LangChain agent as chat history.

        Args:
            packet: The received handoff packet.

        Returns:
            List of ``{"role": ..., "content": ...}`` dicts.
        """
        messages: list[dict[str, str]] = []

        # Add summary as a system message
        messages.append({
            "role": "system",
            "content": f"Handoff context: {packet.context.summary}",
        })

        # Add conversation state
        for entry in packet.context.conversation_state:
            messages.append({
                "role": entry.role.value if hasattr(entry.role, "value") else str(entry.role),
                "content": entry.content,
            })

        # Add pending actions as a system message
        pending = packet.actions.pending
        if pending:
            action_lines = [f"- {a.description} (assignee: {a.assignee})" for a in pending]
            messages.append({
                "role": "system",
                "content": "Pending actions:\n" + "\n".join(action_lines),
            })

        return messages


if _LANGCHAIN_AVAILABLE:

    class HandoffRailCallbackHandler(BaseCallbackHandler):
        """LangChain callback handler that tracks conversation and creates handoffs.

        Use this to automatically capture conversation turns during a LangChain
        agent run and optionally create a handoff packet when the chain completes.

        Args:
            adapter: A :class:`LangChainAdapter` instance.
            auto_handoff: If ``True``, automatically creates a handoff packet
                when the chain finishes (via :meth:`on_chain_end`).

        Example::

            from handoffrail.integrations.langchain import LangChainAdapter, HandoffRailCallbackHandler

            adapter = LangChainAdapter(client=client, agent_id="sales-01", agent_name="SalesBot")
            handler = HandoffRailCallbackHandler(adapter=adapter, auto_handoff=False)

            # Use in a LangChain agent run
            result = agent.run(input, callbacks=[handler])

            # Manually create a handoff from the captured conversation
            if handler.conversation:
                packet = adapter.create_handoff(
                    target_agent_id="billing-01",
                    target_agent_name="BillingBot",
                    summary="Customer upgrade request",
                    conversation_state=handler.conversation,
                )
        """

        def __init__(
            self,
            adapter: LangChainAdapter,
            auto_handoff: bool = False,
            target_agent_id: str | None = None,
            target_agent_name: str | None = None,
            summary_template: str = "Handoff from {agent_name}",
        ) -> None:
            super().__init__()
            self.adapter = adapter
            self.auto_handoff = auto_handoff
            self.target_agent_id = target_agent_id
            self.target_agent_name = target_agent_name
            self.summary_template = summary_template
            self.conversation: list[dict[str, Any]] = []
            self._last_packet: PacketResponse | None = None

        @property
        def last_packet(self) -> PacketResponse | None:
            """The most recently created handoff packet, if any."""
            return self._last_packet

        def on_llm_start(self, serialized: Any, prompts: list[str], **kwargs: Any) -> None:
            """Called when LLM starts — not used for tracking."""

        def on_llm_end(self, response: Any, **kwargs: Any) -> None:
            """Called when LLM finishes — capture the AI response."""
            try:
                generations = response.generations
                if generations and generations[0]:
                    text = generations[0][0].text
                    self.conversation.append({"role": "agent", "content": text})
            except (AttributeError, IndexError):
                pass

        def on_llm_error(self, error: Any, **kwargs: Any) -> None:
            """Called on LLM error — not used."""

        def on_chain_start(self, serialized: Any, inputs: dict[str, Any], **kwargs: Any) -> None:
            """Called when a chain starts — capture the initial input."""
            user_input = inputs.get("input", inputs.get("question", ""))
            if user_input and isinstance(user_input, str):
                self.conversation.append({"role": "user", "content": user_input})

        def on_chain_end(self, outputs: dict[str, Any], **kwargs: Any) -> None:
            """Called when a chain ends — optionally create a handoff packet."""
            # Capture the final output
            output = outputs.get("output", outputs.get("result", ""))
            if output and isinstance(output, str):
                self.conversation.append({"role": "agent", "content": output})

            # Auto-create handoff if configured
            if self.auto_handoff and self.target_agent_id and self.target_agent_name:
                summary = self.summary_template.format(agent_name=self.adapter.agent_name)
                try:
                    self._last_packet = self.adapter.create_handoff(
                        target_agent_id=self.target_agent_id,
                        target_agent_name=self.target_agent_name,
                        summary=summary,
                        conversation_state=self.conversation,
                    )
                except HandoffRailError:
                    # Don't crash the chain if handoff fails
                    pass

        def on_chain_error(self, error: Any, **kwargs: Any) -> None:
            """Called on chain error — not used."""

        def on_tool_start(self, serialized: Any, input_str: str, **kwargs: Any) -> None:
            """Called when a tool starts — not used."""

        def on_tool_end(self, output: str, **kwargs: Any) -> None:
            """Called when a tool finishes — capture tool output."""
            self.conversation.append({"role": "system", "content": f"Tool output: {output}"})

        def on_tool_error(self, error: Any, **kwargs: Any) -> None:
            """Called on tool error — not used."""

        def on_text(self, text: str, **kwargs: Any) -> None:
            """Called on intermediate text — not used."""

        def on_agent_action(self, action: Any, **kwargs: Any) -> None:
            """Called when an agent takes an action — not used for conversation."""

        def on_agent_finish(self, finish: Any, **kwargs: Any) -> None:
            """Called when an agent finishes — capture return value."""
            try:
                return_values = finish.return_values
                output = return_values.get("output", str(return_values))
                self.conversation.append({"role": "agent", "content": output})
            except AttributeError:
                pass

    class HandoffRailTool(BaseTool):
        """LangChain tool that exposes HandoffRail operations to agents.

        Allows a LangChain agent to create, claim, update, complete, and get
        handoff packets using the standard tool interface.

        Args:
            client: An initialized :class:`HandoffRailClient`.
            name: Tool name (default ``"handoffrail"``).
            description: Tool description for the agent.

        Example::

            from handoffrail.integrations.langchain import HandoffRailTool

            tool = HandoffRailTool(client=my_client)
            # Use in an agent
            agent = initialize_agent([tool], llm, agent=AgentType.ZERO_SHOT_REACT)

            # Or call directly
            result = tool._run(action="create", target_agent_id="billing-01",
                               target_agent_name="BillingBot", summary="Customer upgrade")
        """

        name: str = "handoffrail"  # type: ignore[assignment]
        description: str = (
            "HandoffRail session-continuity tool. "
            "Actions: create, claim, update, complete, get. "
            "Use this to create handoff packets for other agents, claim available handoffs, "
            "update handoff status, mark handoffs as completed, or retrieve handoff details."
        )

        client: Any = Field(default=None)  # HandoffRailClient instance

        class Config:
            arbitrary_types_allowed = True

        def _run(
            self,
            action: str,
            *,
            packet_id: str | None = None,
            target_agent_id: str | None = None,
            target_agent_name: str | None = None,
            summary: str | None = None,
            status: str | None = None,
            agent_id: str | None = None,
            agent_name: str | None = None,
            priority: str = "normal",
            tags: str | None = None,
            **kwargs: Any,
        ) -> str:
            """Execute a handoff action synchronously.

            Args:
                action: One of ``create``, ``claim``, ``update``, ``complete``, ``get``.
                packet_id: Packet UUID (required for claim, update, complete, get).
                target_agent_id: Target agent ID (required for create).
                target_agent_name: Target agent name (required for create).
                summary: Context summary (required for create).
                status: New status for update action.
                agent_id: Claiming agent ID (for claim).
                agent_name: Claiming agent name (for claim).
                priority: Packet priority (for create).
                tags: Comma-separated tags (for create).

            Returns:
                JSON string with the result.
            """
            try:
                if action == "create":
                    if not target_agent_id or not target_agent_name or not summary:
                        return json.dumps({"error": "create requires target_agent_id, target_agent_name, and summary"})
                    tags_list = tags.split(",") if tags else []
                    packet = self.client.create_packet(
                        PacketCreate.from_dict({
                            "metadata": {
                                "source_agent": {"id": agent_id or "unknown", "name": agent_name or "Unknown"},
                                "target_agent": {"id": target_agent_id, "name": target_agent_name},
                                "priority": priority,
                                "tags": tags_list,
                            },
                            "context": {"summary": summary, "conversation_state": [], "artifacts": [], "custom": {}},
                            "decisions": [],
                            "actions": {"pending": [], "completed": [], "failed": []},
                            "dependencies": [],
                            "hitl": None,
                        })
                    )
                    return json.dumps({"status": "created", "packet_id": str(packet.id)})

                elif action == "claim":
                    if not packet_id:
                        return json.dumps({"error": "claim requires packet_id"})
                    result = self.client.claim_packet(
                        packet_id,
                        agent_id=agent_id or "unknown",
                        agent_name=agent_name or "Unknown",
                    )
                    return json.dumps({"status": "claimed", "packet_id": str(result.id)})

                elif action == "update":
                    if not packet_id:
                        return json.dumps({"error": "update requires packet_id"})
                    update_kwargs: dict[str, Any] = {}
                    if status:
                        update_kwargs["status"] = status
                    if summary:
                        update_kwargs["context"] = PacketContext(summary=summary, conversation_state=[])
                    update = PacketUpdate(**update_kwargs)
                    result = self.client.update_packet(packet_id, update)
                    return json.dumps({"status": "updated", "packet_id": str(result.id)})

                elif action == "complete":
                    if not packet_id:
                        return json.dumps({"error": "complete requires packet_id"})
                    result = self.client.complete_packet(packet_id)
                    return json.dumps({"status": "completed", "packet_id": str(result.id)})

                elif action == "get":
                    if not packet_id:
                        return json.dumps({"error": "get requires packet_id"})
                    result = self.client.get_packet(packet_id)
                    return json.dumps({"packet_id": str(result.id), "status": result.status.value if hasattr(result.status, "value") else str(result.status)})

                else:
                    return json.dumps({"error": f"Unknown action: {action}. Use: create, claim, update, complete, get"})

            except HandoffRailError as exc:
                return json.dumps({"error": str(exc), "error_type": type(exc).__name__})
            except Exception as exc:
                return json.dumps({"error": str(exc)})

        async def _arun(
            self,
            action: str,
            *,
            packet_id: str | None = None,
            target_agent_id: str | None = None,
            target_agent_name: str | None = None,
            summary: str | None = None,
            status: str | None = None,
            agent_id: str | None = None,
            agent_name: str | None = None,
            priority: str = "normal",
            tags: str | None = None,
            **kwargs: Any,
        ) -> str:
            """Async version of _run — delegates to sync client for simplicity.

            For true async support, use AsyncHandoffRailClient directly.
            """
            return self._run(
                action,
                packet_id=packet_id,
                target_agent_id=target_agent_id,
                target_agent_name=target_agent_name,
                summary=summary,
                status=status,
                agent_id=agent_id,
                agent_name=agent_name,
                priority=priority,
                tags=tags,
                **kwargs,
            )

else:
    # Stubs when LangChain is not installed — allows importing the module
    # without LangChain, but classes will raise on instantiation/use.

    class HandoffRailCallbackHandler:  # type: ignore[no-redef]
        """LangChain callback handler stub — requires langchain-core."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _require_langchain()

    class HandoffRailTool:  # type: ignore[no-redef]
        """LangChain tool stub — requires langchain-core."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _require_langchain()
