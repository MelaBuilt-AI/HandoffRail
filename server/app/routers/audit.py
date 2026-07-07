"""HandoffRail API Server — Structured audit log endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_api_key_from_request
from app.models.db import ApiKey, Packet, PacketEvent
from app.models.packet import AuditLogEntry, AuditLogResponse

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


def _event_to_audit_entry(event: PacketEvent) -> AuditLogEntry:
    """Convert a packet event row into a structured audit response."""
    return AuditLogEntry(
        id=event.id,
        packet_id=event.packet_id,
        actor=event.actor,
        action=event.event_type,
        resource="packet",
        details=event.get_details() or {},
        timestamp=event.timestamp,
    )


@router.get("", response_model=AuditLogResponse)
async def list_audit_log(
    actor: str | None = Query(None, description="Filter by actor"),
    action: str | None = Query(None, description="Filter by action/event type"),
    packet_id: str | None = Query(None, description="Filter by packet ID"),
    created_after: datetime | None = Query(None, description="Only entries at or after this timestamp"),
    created_before: datetime | None = Query(None, description="Only entries at or before this timestamp"),
    limit: int = Query(50, ge=1, le=200, description="Max audit entries per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> AuditLogResponse:
    """List tenant-scoped packet lifecycle events as a structured audit log."""
    query = (
        select(PacketEvent)
        .join(Packet, Packet.id == PacketEvent.packet_id)
        .where(Packet.tenant_id == api_key.tenant_id)
    )

    if actor:
        query = query.where(PacketEvent.actor == actor)
    if action:
        query = query.where(PacketEvent.event_type == action)
    if packet_id:
        query = query.where(PacketEvent.packet_id == packet_id)
    if created_after:
        query = query.where(PacketEvent.timestamp >= created_after)
    if created_before:
        query = query.where(PacketEvent.timestamp <= created_before)

    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    result = await db.execute(
        query.order_by(PacketEvent.timestamp.desc())
        .offset(offset)
        .limit(limit)
    )
    events = result.scalars().all()

    return AuditLogResponse(
        entries=[_event_to_audit_entry(event) for event in events],
        total=total,
        limit=limit,
        offset=offset,
    )
