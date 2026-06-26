"""HandoffRail API Server — Dashboard stats API endpoint.

Provides aggregate statistics for the web dashboard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db import Packet
from app.services.websocket import get_connection_manager

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("")
async def get_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """Get aggregate statistics for the dashboard.

    Returns packet counts by status, recent activity, HITL queue depth,
    and active WebSocket connections.
    """
    # Total packets by status
    status_counts_query = select(
        Packet.status,
        func.count(Packet.id),
    ).group_by(Packet.status)

    result = await db.execute(status_counts_query)
    status_rows = result.all()
    packets_by_status = {row[0]: row[1] for row in status_rows}
    total_packets = sum(packets_by_status.values())

    # Packets created in last 24h
    twenty_four_hours_ago = datetime.now(UTC) - timedelta(hours=24)
    recent_count_query = select(
        func.count(Packet.id),
    ).where(Packet.created_at >= twenty_four_hours_ago)
    recent_result = await db.execute(recent_count_query)
    packets_last_24h = recent_result.scalar() or 0

    # Average time to claim (for claimed/completed packets with claimed_at in metadata)
    # This is an approximation — we look at packets that have been claimed
    claimed_packets_query = select(Packet).where(
        Packet.status.in_(["claimed", "in_progress", "completed"])
    )
    claimed_result = await db.execute(claimed_packets_query)
    claimed_packets = claimed_result.scalars().all()

    total_claim_time_seconds = 0.0
    claim_count = 0
    for packet in claimed_packets:
        metadata = packet.get_metadata()
        created_at_str = metadata.get("created_at")
        claimed_at_str = metadata.get("claimed_at")
        if created_at_str and claimed_at_str:
            try:
                # Parse ISO timestamps
                created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                claimed = datetime.fromisoformat(claimed_at_str.replace("Z", "+00:00"))
                total_claim_time_seconds += (claimed - created).total_seconds()
                claim_count += 1
            except (ValueError, TypeError):
                pass

    avg_claim_time_seconds = total_claim_time_seconds / claim_count if claim_count > 0 else None

    # HITL queue depth
    hitl_count_query = select(
        func.count(Packet.id),
    ).where(Packet.status == "awaiting_human")
    hitl_result = await db.execute(hitl_count_query)
    hitl_queue_depth = hitl_result.scalar() or 0

    # Active WebSocket connections
    manager = get_connection_manager()
    ws_connections = manager.active_connection_count

    return {
        "total_packets": total_packets,
        "packets_by_status": packets_by_status,
        "packets_last_24h": packets_last_24h,
        "avg_claim_time_seconds": avg_claim_time_seconds,
        "hitl_queue_depth": hitl_queue_depth,
        "active_ws_connections": ws_connections,
    }
