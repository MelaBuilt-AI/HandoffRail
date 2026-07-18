"""HandoffRail API Server — System health dashboard.

Provides a comprehensive ops-level view of the HandoffRail system
for administrators and devops. This is NOT the basic /health endpoint.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import engine, get_db, is_postgres_url
from app.middleware.auth import require_admin
from app.middleware.rate_limit import rate_limiter_registry
from app.models.db import ApiKey, Packet, Webhook, WebhookDelivery

router = APIRouter(prefix="/api/v1/system", tags=["system"])

# ── App start time tracking ──────────────────────────────────────────────────
_START_TIME: float = time.time()


class SystemHealthResponse(BaseModel):
    """Comprehensive system health dashboard response."""

    # 1. System overview
    version: str = Field(..., description="HandoffRail server version")
    uptime_seconds: float = Field(..., description="Seconds since server start")
    environment: str = Field(..., description="Deployment environment (dev/staging/prod)")
    database_backend: str = Field(..., description="Database backend type (sqlite/postgresql)")

    # 2. Packet statistics
    total_packets: int = Field(..., description="Total packets in the system")
    packets_by_status: dict[str, int] = Field(..., description="Packet counts grouped by status")
    packets_created_last_1h: int = Field(..., description="Packets created in the last hour")
    packets_created_last_24h: int = Field(..., description="Packets created in the last 24 hours")
    avg_time_to_claim_seconds: float | None = Field(
        None, description="Average seconds from creation to claim"
    )
    avg_time_to_complete_seconds: float | None = Field(
        None, description="Average seconds from claim to completion"
    )

    # 3. Agent activity
    active_agents: int = Field(
        ..., description="Distinct agents with claimed but not completed packets"
    )
    total_agents_seen: int = Field(..., description="Total distinct agents ever seen")
    top_agents: list[dict[str, Any]] = Field(
        default_factory=list, description="Top 5 agents by packet count"
    )

    # 4. Queue depth
    packets_waiting: int = Field(..., description="Packets with status=created (waiting to be claimed)")
    oldest_waiting_packet_age_seconds: float | None = Field(
        None, description="Age in seconds of the oldest unclaimed packet"
    )
    claimed_not_completed: int = Field(
        ..., description="Packets claimed but not yet completed, failed, or expired"
    )

    # 5. Webhook health
    total_webhooks: int = Field(..., description="Total registered webhooks")
    recent_deliveries_1h: int = Field(..., description="Webhook deliveries in the last hour")
    failed_deliveries_1h: int = Field(..., description="Failed webhook deliveries in the last hour")
    avg_delivery_latency_ms: float | None = Field(
        None, description="Average webhook delivery latency in milliseconds"
    )

    # 6. Storage
    db_size_bytes: int | None = Field(
        None, description="Database size in bytes (SQLite file or PG db size)"
    )
    connection_pool: dict[str, Any] | None = Field(
        None, description="Connection pool stats (PostgreSQL only)"
    )

    # 7. Rate limiting
    active_api_keys: int = Field(..., description="Total non-revoked API keys")
    requests_last_1h_per_key: dict[str, int] = Field(
        default_factory=dict,
        description="Requests in the current hourly window per API key prefix",
    )


def _extract_agent_ids(packet: Packet) -> tuple[str | None, str | None]:
    """Extract source and target agent IDs from a packet's metadata.

    Returns (source_agent_id, target_agent_id).
    """
    try:
        metadata = json.loads(packet.metadata_json)
    except (json.JSONDecodeError, ValueError):
        return None, None
    src = None
    if isinstance(metadata.get("source_agent"), dict):
        src = metadata["source_agent"].get("id")
    tgt = None
    if isinstance(metadata.get("target_agent"), dict):
        tgt = metadata["target_agent"].get("id")
    return src, tgt


def _utc_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC).

    SQLite stores naive datetimes; this coerces them to UTC for comparison
    with aware datetimes like datetime.now(UTC).
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _compute_top_agents(packets: list[Packet], top_n: int = 5) -> list[dict[str, Any]]:
    """Extract agent IDs from packet metadata and return top N by count."""
    agent_counts: dict[str, int] = {}
    for p in packets:
        src, tgt = _extract_agent_ids(p)
        if src:
            agent_counts[src] = agent_counts.get(src, 0) + 1
        if tgt:
            agent_counts[tgt] = agent_counts.get(tgt, 0) + 1

    sorted_agents = sorted(agent_counts.items(), key=lambda x: x[1], reverse=True)
    return [
        {"agent_id": agent_id, "packet_count": count}
        for agent_id, count in sorted_agents[:top_n]
    ]


@router.get("/health", response_model=SystemHealthResponse)
async def system_health(
    db: AsyncSession = Depends(get_db),
    admin: ApiKey = Depends(require_admin),
) -> dict[str, Any]:
    """Get comprehensive system health dashboard.

    Requires admin role. Returns operational metrics covering packets,
    agents, queues, webhooks, storage, and rate limiting.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(hours=1)
    twenty_four_hours_ago = now - timedelta(hours=24)

    # ── 1. System overview ──────────────────────────────────────────────────
    uptime = time.time() - _START_TIME
    is_pg = is_postgres_url()
    db_backend = "postgresql" if is_pg else "sqlite"

    # ── 2. Packet statistics ─────────────────────────────────────────────────
    # Total packets by status
    status_counts_query = select(Packet.status, func.count(Packet.id)).group_by(Packet.status)
    result = await db.execute(status_counts_query)
    status_rows = result.all()
    packets_by_status: dict[str, int] = {row[0]: row[1] for row in status_rows}
    total_packets = sum(packets_by_status.values())

    # Packets created in last 1h and 24h
    recent_1h_result = await db.execute(
        select(func.count(Packet.id)).where(Packet.created_at >= one_hour_ago)
    )
    packets_last_1h = recent_1h_result.scalar() or 0

    recent_24h_result = await db.execute(
        select(func.count(Packet.id)).where(Packet.created_at >= twenty_four_hours_ago)
    )
    packets_last_24h = recent_24h_result.scalar() or 0

    # Average time-to-claim and time-to-complete
    claimed_packets_result = await db.execute(
        select(Packet).where(Packet.status.in_(["claimed", "in_progress", "awaiting_human", "completed"]))
    )
    claimed_packets: list[Packet] = list(claimed_packets_result.scalars().all())

    total_claim_time = 0.0
    claim_count = 0
    total_complete_time = 0.0
    complete_count = 0

    for pkt in claimed_packets:
        meta = pkt.get_metadata()
        created_str = meta.get("created_at")
        claimed_str = meta.get("claimed_at")
        completed_str = meta.get("completed_at")

        if created_str and claimed_str:
            try:
                created_dt = _utc_aware(datetime.fromisoformat(created_str.replace("Z", "+00:00")))
                claimed_dt = _utc_aware(datetime.fromisoformat(claimed_str.replace("Z", "+00:00")))
            except (ValueError, TypeError):
                pass
            else:
                total_claim_time += (claimed_dt - created_dt).total_seconds()
                claim_count += 1

        if claimed_str and completed_str:
            try:
                claimed_dt = _utc_aware(datetime.fromisoformat(claimed_str.replace("Z", "+00:00")))
                completed_dt = _utc_aware(datetime.fromisoformat(completed_str.replace("Z", "+00:00")))
            except (ValueError, TypeError):
                pass
            else:
                total_complete_time += (completed_dt - claimed_dt).total_seconds()
                complete_count += 1

    avg_claim = total_claim_time / claim_count if claim_count > 0 else None
    avg_complete = total_complete_time / complete_count if complete_count > 0 else None

    # ── 3. Agent activity ────────────────────────────────────────────────────
    # Active agents = distinct target_agent IDs with claimed but not completed packets
    active_statuses = ["claimed", "in_progress", "awaiting_human"]
    active_packets_result = await db.execute(
        select(Packet).where(Packet.status.in_(active_statuses))
    )
    active_packets: list[Packet] = list(active_packets_result.scalars().all())

    active_agent_ids: set[str] = set()
    for p in active_packets:
        _, tgt = _extract_agent_ids(p)
        if tgt:
            active_agent_ids.add(tgt)

    # Total agents seen and top agents — scan all packets
    all_packets_result = await db.execute(select(Packet))
    all_packets: list[Packet] = list(all_packets_result.scalars().all())

    all_agent_ids: set[str] = set()
    for p in all_packets:
        src, tgt = _extract_agent_ids(p)
        if src:
            all_agent_ids.add(src)
        if tgt:
            all_agent_ids.add(tgt)

    top_agents = _compute_top_agents(all_packets)

    # ── 4. Queue depth ───────────────────────────────────────────────────────
    waiting_count_result = await db.execute(
        select(func.count(Packet.id)).where(Packet.status == "created")
    )
    waiting_count = waiting_count_result.scalar() or 0

    oldest_result = await db.execute(
        select(Packet).where(Packet.status == "created").order_by(Packet.created_at.asc()).limit(1)
    )
    oldest_packet = oldest_result.scalar_one_or_none()
    oldest_age = None
    if oldest_packet is not None:
        oldest_age = (now - _utc_aware(oldest_packet.created_at)).total_seconds()

    in_flight_result = await db.execute(
        select(func.count(Packet.id)).where(Packet.status.in_(active_statuses))
    )
    in_flight_count = in_flight_result.scalar() or 0

    # ── 5. Webhook health ────────────────────────────────────────────────────
    total_webhooks_result = await db.execute(select(func.count(Webhook.id)))
    total_webhooks_count = total_webhooks_result.scalar() or 0

    recent_deliveries = await db.execute(
        select(func.count(WebhookDelivery.id)).where(WebhookDelivery.created_at >= one_hour_ago)
    )
    recent_deliveries_count = recent_deliveries.scalar() or 0

    failed_deliveries = await db.execute(
        select(func.count(WebhookDelivery.id)).where(
            WebhookDelivery.created_at >= one_hour_ago,
            WebhookDelivery.status.in_(["failed", "dead_letter"]),
        )
    )
    failed_deliveries_count = failed_deliveries.scalar() or 0

    # Average delivery latency
    delivered_rows = await db.execute(
        select(WebhookDelivery).where(
            WebhookDelivery.status == "delivered",
            WebhookDelivery.delivered_at.isnot(None),
            WebhookDelivery.created_at.isnot(None),
        )
    )
    delivered_list: list[WebhookDelivery] = list(delivered_rows.scalars().all())

    total_latency = 0.0
    latency_count = 0
    for d in delivered_list:
        if d.created_at is not None and d.delivered_at is not None:
            latency = (_utc_aware(d.delivered_at) - _utc_aware(d.created_at)).total_seconds() * 1000
            total_latency += latency
            latency_count += 1
    avg_latency = total_latency / latency_count if latency_count > 0 else None

    # ── 6. Storage ───────────────────────────────────────────────────────────
    db_size: int | None = None
    pool_stats: dict[str, Any] | None = None

    if is_pg:
        try:
            size_result = await db.execute(
                text("SELECT pg_database_size(current_database()) as bytes")
            )
            size_row = size_result.one_or_none()
            if size_row is not None:
                db_size = size_row.bytes

            pool = engine.pool
            pool_stats = {
                "size": pool.size(),
                "checked_in": pool.checkedin(),
                "overflow": pool.overflow(),
                "checked_out": pool.checkedout(),
            }
        except Exception:
            pass
    else:
        db_url = settings.database_url
        if db_url.startswith("sqlite+aiosqlite:///"):
            db_path = db_url.replace("sqlite+aiosqlite:///", "")
        elif db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
        else:
            db_path = None

        if db_path is not None:
            if not os.path.isabs(db_path):
                db_path = os.path.join(os.getcwd(), db_path)
            if os.path.isfile(db_path):
                try:
                    db_size = os.path.getsize(db_path)
                except OSError:
                    pass

    # ── 7. Rate limiting ─────────────────────────────────────────────────────
    active_keys_result = await db.execute(
        select(func.count(ApiKey.id)).where(ApiKey.revoked == False)  # noqa: E712
    )
    active_api_keys_count = active_keys_result.scalar() or 0

    # Get current rate limit window
    current_hour_start = int(time.time() // 3600) * 3600
    requests_per_key: dict[str, int] = {}
    try:
        for key_id, windows in rate_limiter_registry._windows.items():
            if current_hour_start in windows:
                if key_id.startswith("key:"):
                    display = key_id[4:20]
                elif key_id.startswith("tenant:"):
                    display = key_id
                else:
                    display = key_id
                requests_per_key[display] = windows[current_hour_start]
    except Exception:
        pass

    return SystemHealthResponse(
        # 1 — System overview
        version="0.2.0",
        uptime_seconds=uptime,
        environment=settings.environment,
        database_backend=db_backend,
        # 2 — Packet statistics
        total_packets=total_packets,
        packets_by_status=packets_by_status,
        packets_created_last_1h=packets_last_1h,
        packets_created_last_24h=packets_last_24h,
        avg_time_to_claim_seconds=avg_claim,
        avg_time_to_complete_seconds=avg_complete,
        # 3 — Agent activity
        active_agents=len(active_agent_ids),
        total_agents_seen=len(all_agent_ids),
        top_agents=top_agents,
        # 4 — Queue depth
        packets_waiting=waiting_count,
        oldest_waiting_packet_age_seconds=oldest_age,
        claimed_not_completed=in_flight_count,
        # 5 — Webhook health
        total_webhooks=total_webhooks_count,
        recent_deliveries_1h=recent_deliveries_count,
        failed_deliveries_1h=failed_deliveries_count,
        avg_delivery_latency_ms=avg_latency,
        # 6 — Storage
        db_size_bytes=db_size,
        connection_pool=pool_stats,
        # 7 — Rate limiting
        active_api_keys=active_api_keys_count,
        requests_last_1h_per_key=requests_per_key,
    )
