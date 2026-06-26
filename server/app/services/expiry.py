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
        transition = validate_transition(packet.status, "expired")
    except Exception:
        # Already terminal or invalid state — skip
        logger.debug("skip_expire", packet_id=packet.id, status=packet.status)
        return

    packet.status = "expired"
    packet.updated_at = datetime.now(UTC)

    event = PacketEvent(
        id=str(__import__("uuid").uuid4()),
        packet_id=packet.id,
        event_type=StatusTransition.EXPIRE.value,
        actor="system:expiry_task",
        details_json=json.dumps({"previous_status": packet.status, "reason": "ttl_exceeded"}, default=str),
        timestamp=datetime.now(UTC),
    )
    session.add(event)
    logger.info("packet_expired", packet_id=packet.id, previous_status=packet.status)


async def check_and_expire_packets() -> int:
    """Check all non-terminal packets for TTL expiry and expire stale ones.

    Returns the number of packets expired.
    """
    now = datetime.now(UTC)
    expired_count = 0

    async with async_session() as session:
        # Find packets in non-terminal states that have been around too long
        result = await session.execute(
            select(Packet).where(
                Packet.status.not_in(["completed", "expired"]),
            )
        )
        packets = result.scalars().all()

        for packet in packets:
            # Calculate age of packet
            age_seconds = (now - packet.created_at).total_seconds()
            # Determine TTL: check HITL timeout_seconds, otherwise use default
            ttl_seconds = DEFAULT_TTL_SECONDS
            hitl = packet.get_hitl()
            if hitl and hitl.get("timeout_seconds"):
                ttl_seconds = hitl["timeout_seconds"]

            if age_seconds > ttl_seconds:
                await _expire_packet(packet, session)
                expired_count += 1

        if expired_count > 0:
            await session.commit()

    return expired_count


async def expiry_task() -> None:
    """Background task that periodically checks for expired packets."""
    logger.info("expiry_task_started", check_interval=CHECK_INTERVAL_SECONDS)

    while True:
        try:
            count = await check_and_expire_packets()
            if count > 0:
                logger.info("expiry_task_run", expired_count=count)
        except Exception:
            logger.exception("expiry_task_error")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def start_expiry_task() -> None:
    """Start the expiry background task. Call during app startup."""
    asyncio.create_task(expiry_task())
    logger.info("expiry_task_scheduled")
