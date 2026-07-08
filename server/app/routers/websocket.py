"""HandoffRail API Server — WebSocket endpoint for real-time event streaming.

Provides a /ws endpoint that pushes packet events in real-time to connected
clients. Supports channel subscriptions and tier-gated connection limits.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog
from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse

from app.middleware.auth import hash_key
from app.models.db import ApiKey
from app.services.redis_pubsub import get_pubsub_manager
from app.services.websocket import ConnectionManager, get_connection_manager, get_sse_manager

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


# ── SSE Event Stream Endpoint ──────────────────────────────────────────────────


@router.get("/events")
async def sse_event_stream(
    request: Request,
    api_key: str | None = Query(None, description="API key for authentication"),
    subscribe: list[str] = Query(
        default=[],
        alias="subscribe",
        description="Channel to subscribe to (repeatable, e.g. ?subscribe=status:created&subscribe=agent:agent-01)",
    ),
) -> StreamingResponse:
    """Server-Sent Events endpoint for real-time event streaming.

    Alternative to the WebSocket endpoint for environments where WebSocket
    is unavailable (e.g., behind certain proxies, load balancers, or CDNs
    that don't support WebSocket upgrades).

    Supports:
    - Channel subscriptions via query parameters: ``?subscribe=status:created``
    - Multi-channel: ``?subscribe=status:created&subscribe=agent:agent-01``
    - Standard SSE format: ``event: packet.created\ndata: {\"type\": \"...\"}\n\n``
    - API key authentication via query parameter
    - Automatic keepalive pings every 30 seconds

    Channel format:
    - ``status:{status}`` — events for a specific packet status
    - ``packet:{id}`` — events for a specific packet
    - ``agent:{id}`` — events involving a specific agent

    Omitting ``subscribe`` receives all events for the authenticated tenant.

    Returns:
        ``text/event-stream`` SSE response.
    """
    sse_manager = get_sse_manager()

    # Authenticate
    tenant_id = await _authenticate_sse(api_key)

    # Create SSE connection
    connection_id = await sse_manager.connect(tenant_id=tenant_id)

    # Apply subscriptions
    for channel in subscribe:
        if channel:
            await sse_manager.subscribe(connection_id, channel)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Send initial connected event
            yield _format_sse(
                event_type="connected",
                data=json.dumps({
                    "connection_id": connection_id,
                    "message": (
                        "HandoffRail SSE connected. Subscribed channels: "
                        + (", ".join(subscribe) if subscribe else "all")
                    ),
                }),
            )

            # Keepalive ping timer
            last_ping = time.time()

            while True:
                # Check for disconnect
                if await request.is_disconnected():
                    break

                # Send keepalive every 30 seconds
                now = time.time()
                if now - last_ping >= 30:
                    yield _format_sse(event_type="ping", data=json.dumps({"timestamp": datetime.now(UTC).isoformat()}))
                    last_ping = now

                # Wait for events with timeout
                try:
                    conn = sse_manager._connections.get(connection_id)
                    if conn is None:
                        break

                    message = await asyncio.wait_for(conn.queue.get(), timeout=15.0)
                    if message is None:
                        # Sentinel — connection was closed
                        break

                    # Parse and reformat as SSE
                    event_data = json.loads(message)
                    yield _format_sse(
                        event_type=event_data.get("type", "event"),
                        data=message,
                    )
                except TimeoutError:
                    # Timeout is normal — just loop to check disconnect and send keepalive
                    continue

        except asyncio.CancelledError:
            pass
        finally:
            await sse_manager.disconnect(connection_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _authenticate_sse(api_key_str: str | None) -> str:
    """Authenticate an SSE request via query param API key.

    Returns:
        The tenant_id for the connection.
        Defaults to "default" if no API key provided (dev mode).
    """
    if not api_key_str:
        return "default"

    from sqlalchemy import select

    from app.database import async_session

    key_hash = hash_key(api_key_str)
    async with async_session() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        db_key = result.scalar_one_or_none()

    if db_key is None or db_key.revoked:
        return "default"

    return db_key.tenant_id


def _format_sse(event_type: str, data: str) -> str:
    """Format an event as an SSE message string."""
    lines = data.split("\n")
    result = f"event: {event_type}\n"
    for line in lines:
        result += f"data: {line}\n"
    result += "\n"
    return result


async def publish_event(
    event_type: str,
    data: dict[str, Any],
    packet_id: str = "",
    tenant_id: str = "default",
) -> None:
    """Publish a packet event to all relevant subscribers.

    Publishes via Redis pub/sub (if available) and falls back to
    in-process broadcasting. Broadcasts locally to WebSocket connections
    via the ConnectionManager and to SSE connections via the SSEManager.

    This is the main integration point — call this from packet endpoints
    after any state change.
    """
    manager = get_connection_manager()
    sse_manager = get_sse_manager()
    pubsub = get_pubsub_manager()

    # Build the event
    event = {
        "type": event_type,
        "packet_id": packet_id,
        "data": data,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # Broadcast to WebSocket connections (always)
    await manager.broadcast(event, tenant_id=tenant_id)

    # Broadcast to SSE connections (always)
    await sse_manager.broadcast(event, tenant_id=tenant_id)

    # Publish to Redis (for multi-process, fans out via pubsub listener)
    await pubsub.publish(event_type, data, packet_id)
