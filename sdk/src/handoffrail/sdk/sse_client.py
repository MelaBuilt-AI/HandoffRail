"""HandoffRail SDK — SSE client for real-time event streaming.

Provides an async context manager that connects to HandoffRail's /events
SSE endpoint and dispatches typed events to callback handlers.

SSE is an alternative to WebSocket for environments where WebSocket is
unavailable (e.g., behind certain proxies or CDNs that don't support
WebSocket upgrades).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

logger = logging.getLogger("handoffrail.sse")

# ── Event type constants ───────────────────────────────────────────────────────
EVENT_PACKET_CREATED = "packet.created"
EVENT_PACKET_CLAIMED = "packet.claimed"
EVENT_PACKET_UPDATED = "packet.updated"
EVENT_PACKET_IN_PROGRESS = "packet.in_progress"
EVENT_PACKET_AWAITING_HUMAN = "packet.awaiting_human"
EVENT_PACKET_COMPLETED = "packet.completed"
EVENT_PACKET_FAILED = "packet.failed"
EVENT_PACKET_EXPIRED = "packet.expired"
EVENT_PACKET_CHAINED = "packet.chained"
EVENT_HITL_RESPONSE_READY = "hitl.response_ready"

ALL_EVENTS = {
    EVENT_PACKET_CREATED,
    EVENT_PACKET_CLAIMED,
    EVENT_PACKET_UPDATED,
    EVENT_PACKET_IN_PROGRESS,
    EVENT_PACKET_AWAITING_HUMAN,
    EVENT_PACKET_COMPLETED,
    EVENT_PACKET_FAILED,
    EVENT_PACKET_EXPIRED,
    EVENT_PACKET_CHAINED,
    EVENT_HITL_RESPONSE_READY,
}

# ── Callback type ──────────────────────────────────────────────────────────────
EventCallback = Callable[[dict], Coroutine[Any, Any, None]]


@dataclass
class _SSEBuffer:
    """Internal buffer for parsing SSE messages."""
    event_type: str = ""
    data_lines: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.event_type = ""
        self.data_lines = []

    def is_complete(self) -> bool:
        return bool(self.data_lines)

    def to_event(self) -> dict[str, Any] | None:
        if not self.data_lines:
            return None
        data_str = "\n".join(self.data_lines)
        try:
            event = json.loads(data_str)
            return event
        except json.JSONDecodeError:
            return None


class HandoffRailSSEClient:
    """Async SSE client for HandoffRail real-time events.

    Connects to the /events SSE endpoint and dispatches typed events
    to callback handlers. Supports auto-reconnect with exponential backoff
    and channel subscriptions.

    Usage::

        async with HandoffRailSSEClient(
            "http://localhost:8080",
            api_key="sk-...",
        ) as client:
            client.on_packet_created = lambda e: print(f"New packet: {e['packet_id']}")
            await asyncio.sleep(60)  # listen for events

    With subscriptions::

        async with HandoffRailSSEClient(
            "http://localhost:8080",
            api_key="sk-...",
            subscribe=["status:created", "status:completed"],
        ) as client:
            ...
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_key: str | None = None,
        subscribe: list[str] | None = None,
        reconnect: bool = True,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
        reconnect_multiplier: float = 2.0,
    ) -> None:
        """Initialize the SSE client.

        Args:
            base_url: Base HTTP URL of the HandoffRail API (e.g. ``http://localhost:8080``).
            api_key: API key for authentication.
            subscribe: List of channels to subscribe to (e.g. ``["status:created"]``).
            reconnect: Whether to auto-reconnect on disconnect.
            reconnect_delay: Initial reconnect delay in seconds.
            max_reconnect_delay: Maximum reconnect delay in seconds.
            reconnect_multiplier: Multiplier for exponential backoff.
        """
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._subscribe = subscribe or []
        self._reconnect = reconnect
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._reconnect_multiplier = reconnect_multiplier

        self._running = False
        self._current_delay = reconnect_delay

        # Event callbacks
        self.on_packet_created: EventCallback | None = None
        self.on_packet_claimed: EventCallback | None = None
        self.on_packet_updated: EventCallback | None = None
        self.on_packet_in_progress: EventCallback | None = None
        self.on_packet_awaiting_human: EventCallback | None = None
        self.on_packet_completed: EventCallback | None = None
        self.on_packet_failed: EventCallback | None = None
        self.on_packet_expired: EventCallback | None = None
        self.on_packet_chained: EventCallback | None = None
        self.on_hitl_response_ready: EventCallback | None = None
        self.on_connected: Callable[[], Coroutine[Any, Any, None]] | None = None
        self.on_disconnected: Callable[[], Coroutine[Any, Any, None]] | None = None
        self.on_error: Callable[[Exception], Coroutine[Any, Any, None]] | None = None
        self.on_event: EventCallback | None = None

    @property
    def connected(self) -> bool:
        """Whether the client is currently connected."""
        return self._running

    def _build_url(self) -> str:
        """Build the SSE endpoint URL with query parameters."""
        params: dict[str, str | list[str]] = {}
        if self._api_key:
            params["api_key"] = self._api_key
        if self._subscribe:
            params["subscribe"] = self._subscribe

        query = urlencode(params, doseq=True)
        url = f"{self._base_url}/events"
        if query:
            url = f"{url}?{query}"
        return url

    async def __aenter__(self) -> HandoffRailSSEClient:
        """Connect to the SSE endpoint."""
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Disconnect from the SSE endpoint."""
        await self.disconnect()

    async def connect(self) -> None:
        """Connect to the SSE endpoint and start listening."""
        if importlib.util.find_spec("httpx") is None:
            raise ImportError(
                "httpx package is required for SSE support. "
                "Install it with: pip install handoffrail[sse]"
            )

        self._running = True
        self._current_delay = self._reconnect_delay
        await self._connect_and_listen()

    async def _connect_and_listen(self) -> None:
        """Connect and start the message loop."""
        import httpx

        url = self._build_url()

        while self._running:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=None)) as client:
                    async with client.stream("GET", url) as response:
                        if response.status_code != 200:
                            error_text = await response.aread()
                            logger.error(
                                "sse_connection_error",
                                status_code=response.status_code,
                                body=error_text[:200],
                            )
                            if self.on_error:
                                await self.on_error(
                                    OSError(f"SSE connection failed: {response.status_code}")
                                )
                            if self._reconnect:
                                await self._reconnect_wait()
                            else:
                                self._running = False
                            continue

                        self._current_delay = self._reconnect_delay
                        logger.info("sse_connected", url=url)

                        if self.on_connected:
                            await self.on_connected()

                        # Parse SSE stream
                        buffer = _SSEBuffer()
                        async for line in response.aiter_lines():
                            if not self._running:
                                break

                            line = line.strip()

                            if line.startswith("event: "):
                                buffer.event_type = line[7:]
                            elif line.startswith("data: "):
                                buffer.data_lines.append(line[6:])
                            elif line == "":
                                # Empty line = end of event
                                if buffer.is_complete():
                                    try:
                                        event = buffer.to_event()
                                        if event:
                                            await self._dispatch(event)
                                    except Exception:
                                        pass
                                buffer.reset()
                            # Ignore comments (lines starting with ':') and other fields

            except Exception as exc:
                logger.error("sse_error", error=str(exc))
                if self.on_error:
                    try:
                        await self.on_error(exc)
                    except Exception:
                        pass

                if self._reconnect and self._running:
                    await self._reconnect_wait()
                else:
                    break

    async def _reconnect_wait(self) -> None:
        """Wait with exponential backoff before reconnecting."""
        logger.info("sse_reconnecting", delay=self._current_delay)
        await asyncio.sleep(self._current_delay)
        self._current_delay = min(
            self._current_delay * self._reconnect_multiplier,
            self._max_reconnect_delay,
        )

    async def disconnect(self) -> None:
        """Disconnect from the SSE endpoint."""
        self._running = False
        logger.info("sse_disconnected_by_user")

    async def _dispatch(self, event: dict) -> None:
        """Dispatch an event to the appropriate callback."""
        event_type = event.get("type", "")

        # Call generic event callback
        if self.on_event:
            try:
                await self.on_event(event)
            except Exception as exc:
                logger.error("sse_callback_error", event_type=event_type, error=str(exc))

        # Call type-specific callback
        callback_map = {
            EVENT_PACKET_CREATED: self.on_packet_created,
            EVENT_PACKET_CLAIMED: self.on_packet_claimed,
            EVENT_PACKET_UPDATED: self.on_packet_updated,
            EVENT_PACKET_IN_PROGRESS: self.on_packet_in_progress,
            EVENT_PACKET_AWAITING_HUMAN: self.on_packet_awaiting_human,
            EVENT_PACKET_COMPLETED: self.on_packet_completed,
            EVENT_PACKET_FAILED: self.on_packet_failed,
            EVENT_PACKET_EXPIRED: self.on_packet_expired,
            EVENT_PACKET_CHAINED: self.on_packet_chained,
            EVENT_HITL_RESPONSE_READY: self.on_hitl_response_ready,
        }

        callback = callback_map.get(event_type)
        if callback:
            try:
                await callback(event)
            except Exception as exc:
                logger.error("sse_callback_error", event_type=event_type, error=str(exc))
