"""HandoffRail SDK — WebSocket client for real-time event streaming.

Provides an async context manager that connects to HandoffRail's /ws endpoint
and dispatches typed events to callback handlers.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any
from urllib.parse import quote

logger = logging.getLogger("handoffrail.ws")

# ── Event type constants ───────────────────────────────────────────────────────
EVENT_PACKET_CREATED = "packet.created"
EVENT_PACKET_CLAIMED = "packet.claimed"
EVENT_PACKET_UPDATED = "packet.updated"  # generic update
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
# Callbacks receive the event dict as the only argument
EventCallback = Callable[[dict], Coroutine[Any, Any, None]]


class HandoffRailWSClient:
    """Async WebSocket client for HandoffRail real-time events.

    Usage::

        async with HandoffRailWSClient("ws://localhost:8080/ws") as client:
            client.on_packet_created = lambda e: print(f"New packet: {e['packet_id']}")
            await client.subscribe("status:created")
            await asyncio.sleep(60)  # listen for events

    With API key authentication::

        async with HandoffRailWSClient(
            "ws://localhost:8080/ws", api_key="hr_abc123..."
        ) as client:
            ...
    """

    def __init__(
        self,
        url: str = "ws://localhost:8080/ws",
        api_key: str | None = None,
        reconnect: bool = True,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
        reconnect_multiplier: float = 2.0,
    ) -> None:
        """Initialize the WebSocket client.

        Args:
            url: WebSocket endpoint URL.
            api_key: Optional API key for authentication.
            reconnect: Whether to auto-reconnect on disconnect.
            reconnect_delay: Initial reconnect delay in seconds.
            max_reconnect_delay: Maximum reconnect delay in seconds.
            reconnect_multiplier: Multiplier for exponential backoff.
        """
        # Normalize URL
        self._base_url = url
        self._api_key = api_key
        self._reconnect = reconnect
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._reconnect_multiplier = reconnect_multiplier

        self._ws = None
        self._connected = False
        self._running = False
        self._task: asyncio.Task | None = None
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

        # Generic callback for all events
        self.on_event: EventCallback | None = None

    @property
    def connected(self) -> bool:
        """Whether the client is currently connected."""
        return self._connected

    def _build_url(self) -> str:
        """Build the full WebSocket URL with optional API key query param."""
        url = self._base_url
        if self._api_key:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}api_key={quote(self._api_key, safe='')}"
        return url

    async def __aenter__(self) -> HandoffRailWSClient:
        """Connect to the WebSocket server."""
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Disconnect from the WebSocket server."""
        await self.disconnect()

    async def connect(self) -> None:
        """Connect to the WebSocket server and start listening."""
        if importlib.util.find_spec("websockets") is None:
            raise ImportError(
                "websockets package is required for WebSocket support. "
                "Install it with: pip install handoffrail[ws]"
            )

        self._running = True
        self._current_delay = self._reconnect_delay
        await self._connect_and_listen()

    async def _connect_and_listen(self) -> None:
        """Connect and start the message loop."""
        import websockets

        url = self._build_url()

        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    self._connected = True
                    self._current_delay = self._reconnect_delay
                    logger.info("ws_client_connected", url=self._base_url)

                    if self.on_connected:
                        await self.on_connected()

                    # Message loop
                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            event = json.loads(message)
                            await self._dispatch(event)
                        except json.JSONDecodeError:
                            logger.warning("ws_client_invalid_json", message=message[:200])

            except websockets.ConnectionClosed:
                self._connected = False
                self._ws = None
                logger.info("ws_client_disconnected")
                if self.on_disconnected:
                    await self.on_disconnected()

                if self._reconnect and self._running:
                    logger.info("ws_client_reconnecting", delay=self._current_delay)
                    await asyncio.sleep(self._current_delay)
                    self._current_delay = min(
                        self._current_delay * self._reconnect_multiplier,
                        self._max_reconnect_delay,
                    )
                else:
                    break

            except Exception as exc:
                self._connected = False
                self._ws = None
                logger.error("ws_client_error", error=str(exc))
                if self.on_error:
                    await self.on_error(exc)

                if self._reconnect and self._running:
                    await asyncio.sleep(self._current_delay)
                    self._current_delay = min(
                        self._current_delay * self._reconnect_multiplier,
                        self._max_reconnect_delay,
                    )
                else:
                    break

    async def disconnect(self) -> None:
        """Disconnect from the WebSocket server."""
        self._running = False
        self._connected = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("ws_client_disconnected_by_user")

    async def subscribe(self, channel: str) -> None:
        """Subscribe to a channel.

        Channel format:
        - "status:{status}" — e.g. "status:created", "status:completed"
        - "packet:{id}" — subscribe to events for a specific packet
        - "agent:{id}" — subscribe to events for a specific agent
        """
        if self._ws and self._connected:
            await self._ws.send(json.dumps({"action": "subscribe", "channel": channel}))
        else:
            logger.warning("ws_client_not_connected_subscribe", channel=channel)

    async def unsubscribe(self, channel: str) -> None:
        """Unsubscribe from a channel."""
        if self._ws and self._connected:
            await self._ws.send(json.dumps({"action": "unsubscribe", "channel": channel}))
        else:
            logger.warning("ws_client_not_connected_unsubscribe", channel=channel)

    async def ping(self) -> None:
        """Send a ping to the server."""
        if self._ws and self._connected:
            await self._ws.send(json.dumps({"action": "ping"}))

    async def _dispatch(self, event: dict) -> None:
        """Dispatch an event to the appropriate callback."""
        event_type = event.get("type", "")

        # Call generic event callback
        if self.on_event:
            await self.on_event(event)

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
                logger.error("ws_callback_error", event_type=event_type, error=str(exc))
