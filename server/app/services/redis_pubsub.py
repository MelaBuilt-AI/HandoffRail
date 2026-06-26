"""HandoffRail API Server — Redis pub/sub manager for real-time event broadcasting.

Publishes packet events to Redis channels and subscribes to relay them
to WebSocket connections. Falls back to in-process broadcasting when
Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()

# Redis channel prefix
CHANNEL_PREFIX = "handoffrail:events"


class RedisPubSubManager:
    """Manages Redis pub/sub for broadcasting events across processes.

    When Redis is available, events are published to Redis channels
    and each process subscribes to relay them to local WebSocket connections.

    When Redis is unavailable, falls back to in-process broadcasting only
    (events only reach WebSocket connections in the same process).
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self.redis_url = redis_url
        self._redis = None
        self._pubsub = None
        self._connected = False
        self._listener_task: asyncio.Task | None = None
        self._on_event_callback: Any = None  # Called when an event is received from Redis

    async def connect(self) -> bool:
        """Try to connect to Redis. Returns True if connected, False if unavailable."""
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            # Test connection
            await self._redis.ping()
            self._connected = True
            logger.info("redis_connected", url=self.redis_url)
            return True
        except Exception as exc:
            logger.warning(
                "redis_unavailable",
                message="Redis not available, falling back to in-process broadcasting",
                error=str(exc),
            )
            self._connected = False
            self._redis = None
            return False

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

        if self._pubsub:
            try:
                await self._pubsub.unsubscribe()
                await self._pubsub.close()
            except Exception:
                pass
            self._pubsub = None

        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass
            self._redis = None

        self._connected = False
        logger.info("redis_disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        return self._connected and self._redis is not None

    def set_event_callback(self, callback: Any) -> None:
        """Set the callback to invoke when an event is received from Redis.

        The callback receives the event dict and should broadcast it to
        local WebSocket connections.
        """
        self._on_event_callback = callback

    async def publish(self, event_type: str, data: dict, packet_id: str = "") -> None:
        """Publish an event to Redis.

        Falls back to in-process broadcast if Redis is unavailable.

        Args:
            event_type: Event type string (e.g. "packet.created").
            data: Event payload data.
            packet_id: Related packet ID.
        """
        event = {
            "type": event_type,
            "packet_id": packet_id,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if not self.is_connected or self._redis is None:
            # In-process fallback — call the event callback directly
            logger.debug("redis_publish_fallback", event_type=event_type)
            if self._on_event_callback:
                await self._on_event_callback(event)
            return

        try:
            # Publish to a general channel
            channel = f"{CHANNEL_PREFIX}:all"
            message = json.dumps(event, default=str)
            await self._redis.publish(channel, message)

            # Also publish to specific channels
            if packet_id:
                await self._redis.publish(f"{CHANNEL_PREFIX}:packet:{packet_id}", message)

            # Publish to status-specific channel
            new_status = data.get("status", "")
            if new_status:
                await self._redis.publish(f"{CHANNEL_PREFIX}:status:{new_status}", message)

            logger.debug("redis_published", event_type=event_type, packet_id=packet_id)
        except Exception as exc:
            logger.warning("redis_publish_error", error=str(exc))
            # Fall back to in-process
            if self._on_event_callback:
                await self._on_event_callback(event)

    async def subscribe(self, channels: list[str] | None = None) -> None:
        """Subscribe to Redis channels for receiving events.

        Args:
            channels: Specific channels to subscribe to. Defaults to all events.
        """
        if not self.is_connected or self._redis is None:
            return

        try:
            self._pubsub = self._redis.pubsub()
            if channels:
                redis_channels = [f"{CHANNEL_PREFIX}:{ch}" for ch in channels]
            else:
                redis_channels = [f"{CHANNEL_PREFIX}:all"]

            await self._pubsub.subscribe(*redis_channels)
            logger.info("redis_subscribed", channels=redis_channels)

            # Start listener task
            self._listener_task = asyncio.create_task(self._listen())
        except Exception as exc:
            logger.warning("redis_subscribe_error", error=str(exc))

    async def _listen(self) -> None:
        """Listen for messages from Redis pub/sub and relay to callback."""
        if not self._pubsub:
            return

        try:
            async for message in self._pubsub.listen():
                if message["type"] == "message":
                    try:
                        event = json.loads(message["data"])
                        if self._on_event_callback:
                            await self._on_event_callback(event)
                    except json.JSONDecodeError:
                        logger.warning("redis_invalid_message", data=message.get("data", ""))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("redis_listen_error", error=str(exc))


# ── Module-level singleton ──────────────────────────────────────────────────────
_pubsub_manager: RedisPubSubManager | None = None


def get_pubsub_manager(redis_url: str = "redis://localhost:6379/0") -> RedisPubSubManager:
    """Get the global RedisPubSubManager instance (lazy singleton)."""
    global _pubsub_manager
    if _pubsub_manager is None:
        _pubsub_manager = RedisPubSubManager(redis_url=redis_url)
    return _pubsub_manager


def reset_pubsub_manager() -> None:
    """Reset the global RedisPubSubManager — useful for tests."""
    global _pubsub_manager
    _pubsub_manager = None
