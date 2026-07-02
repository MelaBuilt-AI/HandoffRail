"""HandoffRail API Server — Packet expiry background task.

Uses asyncio to periodically check for and expire packets that have exceeded
their TTL (time-to-live). Packets past their TTL are transitioned to 'expired'
status via soft delete.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.db import Packet, PacketEvent
from app.services.state_machine import StatusTransition, validate_transition

logger = logging.getLogger("handoffrail.expiry")

# Default TTL: 24 hours in seconds
DEFAULT_TTL_SECONDS = 86400

# How often the expiry task checks for stale packets (seconds)
CHECK_INTERVAL_SECONDS = 60


async def _expire_packet(packet: Packet, session: AsyncSession) -> None:
    """Transition a single packet to expired status."""
    try:
        validate_transition(packet.status, "expired")
    except Exception:
        # Already terminal or invalid state — skip
        logger.debug("skip_expire", packet_id=packet.id, status=packet.status)  # type: ignore[call-arg]
        return

    previous_status = packet.status
    packet.status = "expired"
    packet.updated_at = datetime.now(UTC)

    event = PacketEvent(
        id=str(__import__("uuid").uuid4()),
        packet_id=packet.id,
        event_type=StatusTransition.EXPIRE.value,
        actor="system:expiry_task",
        details_json=json.dumps({"previous_status": previous_status, "reason": "ttl_exceeded"}, default=str),
        timestamp=datetime.now(UTC),
    )
    session.add(event)
    logger.info("packet_expired", packet_id=packet.id, previous_status=previous_status)  # type: ignore[call-arg]


async def check_and_expire_packets() -> int:
    """Check all non-terminal packets for TTL expiry and expire stale ones.

    Uses default TTL as the primary filter via SQL for scalability — only
    packets older than DEFAULT_TTL_SECONDS are loaded from the database.
    After loading, packets with custom HITL timeouts are further checked
    in Python (higher-resolution check for the smaller subset).

    Returns the number of packets expired.
    """
    now = datetime.now(UTC)
    expired_count = 0

    # Cutoff based on default TTL — most packets use this, so SQL filter
    # eliminates the vast majority of non-expired rows.
    from datetime import timedelta
    cutoff = now - timedelta(seconds=DEFAULT_TTL_SECONDS)

    async with async_session() as session:
        # Find packets in non-terminal states created before the cutoff
        result = await session.execute(
            select(Packet).where(
                Packet.status.not_in(["completed", "expired"]),
                Packet.created_at < cutoff,
            )
        )
        packets = result.scalars().all()

        for packet in packets:
            # Already filtered by default TTL via SQL above.
            # Now check custom HITL timeout — if the HITL timeout is SHORTER
            # than the default, the SQL filter may have missed it. But if longer,
            # the SQL filter already handled it correctly.
            hitl = packet.get_hitl()
            if hitl and hitl.get("timeout_seconds"):
                custom_ttl = hitl["timeout_seconds"]
                # Only need further check if custom TTL is shorter than default
                # (shorter means it might not be old enough yet)
                if custom_ttl < DEFAULT_TTL_SECONDS:
                    age_seconds = (now - packet.created_at).total_seconds()
                    if age_seconds <= custom_ttl:
                        continue  # Not expired yet per custom TTL

            await _expire_packet(packet, session)
            expired_count += 1

        if expired_count > 0:
            await session.commit()

    return expired_count


async def expiry_task() -> None:
    """Background task that periodically checks for expired packets."""
    logger.info("expiry_task_started", check_interval=CHECK_INTERVAL_SECONDS)  # type: ignore[call-arg]

    while True:
        try:
            count = await check_and_expire_packets()
            if count > 0:
                logger.info("expiry_task_run", expired_count=count)  # type: ignore[call-arg]
        except Exception:
            logger.exception("expiry_task_error")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def start_expiry_task() -> None:
    """Start the expiry background task. Call during app startup."""
    asyncio.create_task(expiry_task())
    logger.info("expiry_task_scheduled")
