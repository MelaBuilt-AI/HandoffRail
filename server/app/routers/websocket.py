"""HandoffRail API Server — WebSocket endpoint for real-time event streaming.

Provides a /ws endpoint that pushes packet events in real-time to connected
clients. Supports channel subscriptions and tier-gated connection limits.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.middleware.auth import hash_key
from app.models.db import ApiKey
from app.services.redis_pubsub import get_pubsub_manager
from app.services.websocket import ConnectionManager, get_connection_manager

logger = structlog.get_logger()

router = APIRouter(tags=["websocket"])


async def _authenticate_ws(
    ws: WebSocket,
    api_key_str: str | None,
) -> tuple[str, str, str | None]:
    """Authenticate a WebSocket connection via query param API key.

    Returns:
        Tuple of (tier, tenant_id, api_key_id).
        Defaults to "free" tier if no API key provided (dev mode).
    """
    if not api_key_str:
        # No auth — dev mode, default to free tier
        return "free", "default", None

    # Look up the API key in the database
    from sqlalchemy import select

    from app.database import async_session

    key_hash = hash_key(api_key_str)
    async with async_session() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        db_key = result.scalar_one_or_none()

    if db_key is None or db_key.revoked:
        return "free", "default", None

    return db_key.tier, db_key.tenant_id, db_key.id


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    api_key: str | None = Query(None, description="API key for authentication"),
) -> None:
    """WebSocket endpoint for real-time event streaming.

    Accepts connections with optional API key auth. Supports:
    - Subscribing to channels: {"action": "subscribe", "channel": "status:created"}
    - Unsubscribing: {"action": "unsubscribe", "channel": "status:created"}
    - Ping/pong heartbeat (server sends every 30s)
    - Receiving real-time events: {"type": "packet.created", "packet_id": "...", "data": {...}}

    Tier limits:
    - Free: 1 concurrent connection
    - Pro: 5 concurrent connections
    - Business: 25 concurrent connections
    """
    manager = get_connection_manager()

    # Authenticate
    tier, tenant_id, api_key_id = await _authenticate_ws(ws, api_key)

    # Generate connection ID
    connection_id = str(uuid4())

    # Try to connect (checks tier limits)
    connected = await manager.connect(
        websocket=ws,
        connection_id=connection_id,
        tier=tier,
        tenant_id=tenant_id,
        api_key_id=api_key_id,
    )

    if not connected:
        # Tier limit exceeded — send error and close
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Connection limit exceeded for your tier")
        return

    try:
        # Send welcome message
        await ws.send_json({
            "type": "connected",
            "connection_id": connection_id,
            "tier": tier,
            "message": "HandoffRail WebSocket connected. Subscribe to channels to receive events.",
        })

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(_heartbeat_loop(manager, connection_id))

        try:
            # Main message loop
            while True:
                data = await ws.receive_text()
                try:
                    message = json.loads(data)
                    action = message.get("action", "")

                    if action == "subscribe":
                        channel = message.get("channel", "")
                        if channel:
                            await manager.subscribe(connection_id, channel)
                            await ws.send_json({
                                "type": "subscribed",
                                "channel": channel,
                            })

                    elif action == "unsubscribe":
                        channel = message.get("channel", "")
                        if channel:
                            await manager.unsubscribe(connection_id, channel)
                            await ws.send_json({
                                "type": "unsubscribed",
                                "channel": channel,
                            })

                    elif action == "ping":
                        await ws.send_json({
                            "type": "pong",
                            "timestamp": datetime.now(UTC).isoformat(),
                        })

                    else:
                        await ws.send_json({
                            "type": "error",
                            "message": f"Unknown action: {action}",
                        })

                except json.JSONDecodeError:
                    await ws.send_json({
                        "type": "error",
                        "message": "Invalid JSON",
                    })

        except WebSocketDisconnect:
            logger.info("ws_client_disconnected", connection_id=connection_id)

    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        await manager.disconnect(connection_id)


async def _heartbeat_loop(manager: ConnectionManager, connection_id: str) -> None:
    """Send periodic heartbeat pings to a WebSocket connection."""
    from app.services.websocket import HEARTBEAT_INTERVAL_SECONDS

    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        await manager.send_heartbeat(connection_id)


async def publish_event(
    event_type: str,
    data: dict[str, Any],
    packet_id: str = "",
    tenant_id: str = "default",
) -> None:
    """Publish a packet event to all relevant subscribers.

    Publishes via Redis pub/sub (if available) and falls back to
    in-process broadcasting. Also broadcasts locally to WebSocket
    connections via the ConnectionManager.

    This is the main integration point — call this from packet endpoints
    after any state change.
    """
    manager = get_connection_manager()
    pubsub = get_pubsub_manager()

    # Build the event
    event = {
        "type": event_type,
        "packet_id": packet_id,
        "data": data,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # Broadcast locally (always)
    await manager.broadcast(event, tenant_id=tenant_id)

    # Publish to Redis (for multi-process)
    await pubsub.publish(event_type, data, packet_id)
