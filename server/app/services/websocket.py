"""HandoffRail API Server — WebSocket connection manager.

Manages WebSocket connections, subscriptions, and tier-gated
connection limits. Broadcasts events to relevant subscribers.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import WebSocket

logger = structlog.get_logger()

# ── Tier-based WS connection limits ─────────────────────────────────────────────
WS_TIER_LIMITS: dict[str, int] = {
    "free": 1,
    "pro": 5,
    "business": 25,
}

# ── Heartbeat interval ──────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL_SECONDS = 30


class Subscription:
    """A subscription filter for a WebSocket connection.

    Supports:
    - status:subscribe:{status} — e.g. "status:created"
    - packet:subscribe:{id} — e.g. "packet:abc-123"
    - agent:subscribe:{id} — e.g. "agent:sales-01"
    """

    def __init__(self) -> None:
        self.statuses: set[str] = set()
        self.packet_ids: set[str] = set()
        self.agent_ids: set[str] = set()

    def add(self, channel: str) -> None:
        """Parse a subscription channel string and add it."""
        parts = channel.split(":", 2)
        if len(parts) < 2:
            return
        kind = parts[0]
        value = parts[1] if len(parts) > 1 else ""
        if kind == "status":
            self.statuses.add(value)
        elif kind == "packet":
            self.packet_ids.add(value)
        elif kind == "agent":
            self.agent_ids.add(value)

    def remove(self, channel: str) -> None:
        """Parse a subscription channel string and remove it."""
        parts = channel.split(":", 2)
        if len(parts) < 2:
            return
        kind = parts[0]
        value = parts[1] if len(parts) > 1 else ""
        if kind == "status":
            self.statuses.discard(value)
        elif kind == "packet":
            self.packet_ids.discard(value)
        elif kind == "agent":
            self.agent_ids.discard(value)

    def matches(self, event: dict) -> bool:
        """Check if this subscription matches an event."""
        # Empty subscription = receive all events
        if not self.statuses and not self.packet_ids and not self.agent_ids:
            return True

        event_type = event.get("type", "")
        data = event.get("data", {})

        # Match by status in event type (e.g. "packet.created" → status "created")
        new_status = data.get("status", "")
        if new_status and new_status in self.statuses:
            return True

        # Match by packet ID
        packet_id = event.get("packet_id", "")
        if packet_id and packet_id in self.packet_ids:
            return True

        # Match by source or target agent
        metadata = data.get("metadata", {})
        source_agent = metadata.get("source_agent", {}).get("id", "")
        target_agent = metadata.get("target_agent", {}).get("id", "")
        if source_agent in self.agent_ids or target_agent in self.agent_ids:
            return True

        return False


class ConnectionInfo:
    """Metadata about a connected WebSocket client."""

    def __init__(
        self,
        websocket: WebSocket,
        connection_id: str,
        tier: str = "free",
        tenant_id: str = "default",
        api_key_id: str | None = None,
    ) -> None:
        self.websocket = websocket
        self.connection_id = connection_id
        self.tier = tier
        self.tenant_id = tenant_id
        self.api_key_id = api_key_id
        self.subscriptions = Subscription()
        self.connected_at = time.time()
        self.last_heartbeat = time.time()


class ConnectionManager:
    """Manages WebSocket connections, subscriptions, and broadcasting.

    Tier-gated connection limits:
    - Free: 1 concurrent connection
    - Pro: 5 concurrent connections
    - Business: 25 concurrent connections
    """

    def __init__(self) -> None:
        self._connections: dict[str, ConnectionInfo] = {}
        self._tenant_connections: dict[str, set[str]] = {}  # tenant_id → set of connection_ids
        self._lock = asyncio.Lock()

    @property
    def active_connection_count(self) -> int:
        """Total number of active WebSocket connections."""
        return len(self._connections)

    def get_connections_for_export(self) -> list[dict[str, Any]]:
        """Export connection info for the stats endpoint."""
        return [
            {
                "connection_id": info.connection_id,
                "tier": info.tier,
                "tenant_id": info.tenant_id,
                "subscriptions": {
                    "statuses": list(info.subscriptions.statuses),
                    "packet_ids": list(info.subscriptions.packet_ids),
                    "agent_ids": list(info.subscriptions.agent_ids),
                },
                "connected_at": datetime.fromtimestamp(
                    info.connected_at, tz=timezone.utc
                ).isoformat(),
            }
            for info in self._connections.values()
        ]

    async def connect(
        self,
        websocket: WebSocket,
        connection_id: str,
        tier: str = "free",
        tenant_id: str = "default",
        api_key_id: str | None = None,
    ) -> bool:
        """Accept a WebSocket connection if tier limits allow.

        Returns:
            True if connection was accepted, False if tier limit exceeded.
        """
        async with self._lock:
            # Check tier connection limit
            limit = WS_TIER_LIMITS.get(tier, 1)

            # Count connections for this tenant
            tenant_conns = self._tenant_connections.get(tenant_id, set())
            # Also check global tier limit (for free tier which uses 1 conn total)
            if tier == "free":
                # For free tier, count all connections for this tenant
                count = len(tenant_conns)
            else:
                # For paid tiers, count all connections for this tenant
                count = len(tenant_conns)

            if count >= limit:
                logger.warning(
                    "ws_connection_limit_reached",
                    connection_id=connection_id,
                    tier=tier,
                    limit=limit,
                    current=count,
                )
                return False

            # Accept the connection
            await websocket.accept()

            info = ConnectionInfo(
                websocket=websocket,
                connection_id=connection_id,
                tier=tier,
                tenant_id=tenant_id,
                api_key_id=api_key_id,
            )
            self._connections[connection_id] = info

            if tenant_id not in self._tenant_connections:
                self._tenant_connections[tenant_id] = set()
            self._tenant_connections[tenant_id].add(connection_id)

            logger.info(
                "ws_connected",
                connection_id=connection_id,
                tier=tier,
                tenant_id=tenant_id,
            )
            return True

    async def disconnect(self, connection_id: str) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            info = self._connections.pop(connection_id, None)
            if info:
                tenant_conns = self._tenant_connections.get(info.tenant_id, set())
                tenant_conns.discard(connection_id)
                if not tenant_conns and info.tenant_id in self._tenant_connections:
                    del self._tenant_connections[info.tenant_id]

                logger.info(
                    "ws_disconnected",
                    connection_id=connection_id,
                    tier=info.tier,
                    tenant_id=info.tenant_id,
                )

    async def subscribe(self, connection_id: str, channel: str) -> None:
        """Add a subscription for a connection."""
        async with self._lock:
            info = self._connections.get(connection_id)
            if info:
                info.subscriptions.add(channel)
                logger.debug(
                    "ws_subscribed",
                    connection_id=connection_id,
                    channel=channel,
                )

    async def unsubscribe(self, connection_id: str, channel: str) -> None:
        """Remove a subscription for a connection."""
        async with self._lock:
            info = self._connections.get(connection_id)
            if info:
                info.subscriptions.remove(channel)
                logger.debug(
                    "ws_unsubscribed",
                    connection_id=connection_id,
                    channel=channel,
                )

    async def broadcast(self, event: dict, tenant_id: str | None = None) -> None:
        """Broadcast an event to all matching subscribers.

        If tenant_id is provided, only broadcast to connections for that tenant.
        """
        async with self._lock:
            # Collect matching connections
            targets: list[ConnectionInfo] = []
            for info in self._connections.values():
                # Tenant filter
                if tenant_id and info.tenant_id != tenant_id:
                    continue
                # Subscription filter
                if info.subscriptions.matches(event):
                    targets.append(info)

        # Send outside the lock to avoid blocking
        message = json.dumps(event, default=str)
        for info in targets:
            try:
                await info.websocket.send_text(message)
            except Exception:
                logger.debug(
                    "ws_send_failed",
                    connection_id=info.connection_id,
                    error="connection likely closed",
                )

    async def send_heartbeat(self, connection_id: str) -> None:
        """Send a heartbeat ping to a connection."""
        info = self._connections.get(connection_id)
        if info:
            try:
                await info.websocket.send_json({"type": "ping", "timestamp": datetime.now(timezone.utc).isoformat()})
                info.last_heartbeat = time.time()
            except Exception:
                pass


# ── Module-level singleton ──────────────────────────────────────────────────────
_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    """Get the global ConnectionManager instance (lazy singleton)."""
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


def reset_connection_manager() -> None:
    """Reset the global ConnectionManager — useful for tests."""
    global _manager
    _manager = None
