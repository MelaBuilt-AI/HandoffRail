"""HandoffRail API Server — Packet CRUD + Query + History + Chain endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_api_key_from_request
from app.models.db import ApiKey, Packet, PacketEvent
from app.models.packet import (
    ChainRequest,
    ClaimRequest,
    HandoffPacketCreate,
    HandoffPacketResponse,
    HandoffPacketUpdate,
    HitlRespondRequest,
    PacketHistoryResponse,
    PacketListResponse,
    PacketStatus,
)
from app.services.state_machine import InvalidTransitionError, validate_transition
from app.routers.websocket import publish_event
from app.services.tracing import trace_packet_operation

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/packets", tags=["packets"])


def _packet_to_response(packet: Packet) -> HandoffPacketResponse:
    """Convert an ORM Packet to a Pydantic response model."""
    return HandoffPacketResponse(
        id=UUID(packet.id),
        version=packet.version,
        parent_packet_id=UUID(packet.parent_packet_id) if packet.parent_packet_id else None,
        metadata=packet.get_metadata(),
        context=packet.get_context(),
        decisions=packet.get_decisions(),
        actions=packet.get_actions(),
        dependencies=packet.get_dependencies(),
        hitl=packet.get_hitl(),
        status=PacketStatus(packet.status),
        created_at=packet.created_at,
        updated_at=packet.updated_at,
    )


async def _get_packet_or_404(packet_id: UUID, db: AsyncSession, tenant_id: str | None = None) -> Packet:
    """Fetch a packet by ID or raise 404.
    
    If tenant_id is provided, scopes the query to that tenant.
    """
    query = select(Packet).where(Packet.id == str(packet_id))
    if tenant_id is not None:
        query = query.where(Packet.tenant_id == tenant_id)
    result = await db.execute(query)
    packet = result.scalar_one_or_none()
    if packet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Packet {packet_id} not found",
        )
    return packet


async def _add_event(
    db: AsyncSession,
    packet_id: str,
    event_type: str,
    actor: str,
    details: dict | None = None,
) -> None:
    """Record a packet event for the audit trail."""
    event = PacketEvent(
        id=str(uuid4()),
        packet_id=packet_id,
        event_type=event_type,
        actor=actor,
        details_json=json.dumps(details or {}, default=str),
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)


# ── List with Filtering ─────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=PacketListResponse,
)
async def list_packets(
    status_filter: str | None = Query(None, alias="status", description="Comma-separated statuses"),
    source_agent: str | None = Query(None, description="Filter by source agent ID"),
    target_agent: str | None = Query(None, description="Filter by target agent ID"),
    tags: str | None = Query(None, description="Comma-separated tags (all must match)"),
    priority: str | None = Query(None, description="Filter by priority"),
    created_after: datetime | None = Query(None, description="ISO 8601 — packets created after this time"),
    created_before: datetime | None = Query(None, description="ISO 8601 — packets created before this time"),
    limit: int = Query(50, ge=1, le=200, description="Max results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> PacketListResponse:
    """List packets with filtering and pagination.

    Supports filtering by status, source_agent, target_agent, tags,
    priority, and date range. Returns paginated results with total count.
    Results are scoped to the authenticated tenant.
    """
    query = select(Packet).where(Packet.tenant_id == api_key.tenant_id)

    # Status filter (comma-separated for multiple)
    if status_filter:
        statuses = [s.strip() for s in status_filter.split(",")]
        query = query.where(Packet.status.in_(statuses))

    # Source agent filter — stored in metadata_json
    if source_agent:
        # SQLite JSON query fallback: filter in Python after fetch
        pass  # Handled below in post-processing

    # Priority filter — stored in metadata_json
    if priority:
        pass  # Handled below in post-processing

    # Date range filters
    if created_after:
        query = query.where(Packet.created_at >= created_after)
    if created_before:
        query = query.where(Packet.created_at <= created_before)

    # Count total matching
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Apply pagination
    query = query.order_by(Packet.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    packets = result.scalars().all()

    # Post-fetch filtering for JSON-embedded fields
    filtered = []
    for p in packets:
        metadata = p.get_metadata()

        # Source agent filter
        if source_agent:
            src = metadata.get("source_agent", {})
            if src.get("id") != source_agent:
                continue

        # Target agent filter
        if target_agent:
            tgt = metadata.get("target_agent", {})
            if tgt.get("id") != target_agent:
                continue

        # Tags filter (all must match)
        if tags:
            tag_list = [t.strip() for t in tags.split(",")]
            packet_tags = metadata.get("tags", [])
            if not all(t in packet_tags for t in tag_list):
                continue

        # Priority filter
        if priority:
            if metadata.get("priority") != priority:
                continue

        filtered.append(p)

    # Recalculate total if we did post-fetch filtering
    if source_agent or target_agent or tags or priority:
        # Need full count for accuracy
        full_result = await db.execute(select(Packet).where(Packet.tenant_id == api_key.tenant_id))
        all_packets = full_result.scalars().all()
        total_filtered = 0
        for p in all_packets:
            metadata = p.get_metadata()
            if source_agent and metadata.get("source_agent", {}).get("id") != source_agent:
                continue
            if target_agent and metadata.get("target_agent", {}).get("id") != target_agent:
                continue
            if tags:
                tag_list = [t.strip() for t in tags.split(",")]
                packet_tags = metadata.get("tags", [])
                if not all(t in packet_tags for t in tag_list):
                    continue
            if priority and metadata.get("priority") != priority:
                continue
            total_filtered += 1
        total = total_filtered

    return PacketListResponse(
        packets=[_packet_to_response(p) for p in filtered],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── Awaiting Human ──────────────────────────────────────────────────────────────


@router.get(
    "/awaiting",
    response_model=PacketListResponse,
)
async def list_awaiting_human(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> PacketListResponse:
    """Convenience endpoint: returns all packets in 'awaiting_human' status."""
    count_query = select(func.count()).where(Packet.status == "awaiting_human", Packet.tenant_id == api_key.tenant_id)
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    query = (
        select(Packet)
        .where(Packet.status == "awaiting_human", Packet.tenant_id == api_key.tenant_id)
        .order_by(Packet.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    packets = result.scalars().all()

    return PacketListResponse(
        packets=[_packet_to_response(p) for p in packets],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── Create ──────────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=HandoffPacketResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Validation error"},
    },
)
async def create_packet(
    payload: HandoffPacketCreate,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> HandoffPacketResponse:
    """Create a new handoff packet with full v1 schema validation."""
    packet_id = str(uuid4())
    now = datetime.now(timezone.utc)

    with trace_packet_operation("create_packet", packet_id=packet_id, tenant_id=api_key.tenant_id) as span:
        span.set_attribute("packet.source_agent", payload.metadata.source_agent.id)
        span.set_attribute("packet.target_agent", payload.metadata.target_agent.id)
        span.set_attribute("packet.priority", payload.metadata.priority.value)

        # Determine initial status
        initial_status = "created"
        if payload.hitl is not None and payload.hitl.required:
            initial_status = "awaiting_human"

        span.set_attribute("packet.initial_status", initial_status)

        # Build metadata dict
        metadata_dict = payload.metadata.model_dump(mode="json")
        if metadata_dict.get("created_at") is None:
            metadata_dict["created_at"] = now.isoformat()

        # Build context dict
        context_dict = payload.context.model_dump(mode="json")

        # Build decisions, actions, dependencies dicts
        decisions_list = [d.model_dump(mode="json") for d in payload.decisions]
        actions_dict = payload.actions.model_dump(mode="json")
        dependencies_list = [d.model_dump(mode="json") for d in payload.dependencies]
        hitl_dict = payload.hitl.model_dump(mode="json") if payload.hitl else None

        db_packet = Packet(
            id=packet_id,
            version="1.0.0",
            parent_packet_id=str(payload.parent_packet_id) if payload.parent_packet_id else None,
            status=initial_status,
            tenant_id=api_key.tenant_id,
            metadata_json=json.dumps(metadata_dict, default=str),
            context_json=json.dumps(context_dict, default=str),
            decisions_json=json.dumps(decisions_list, default=str),
            actions_json=json.dumps(actions_dict, default=str),
            dependencies_json=json.dumps(dependencies_list, default=str),
            hitl_json=json.dumps(hitl_dict, default=str) if hitl_dict else None,
            created_at=now,
            updated_at=now,
        )

        db.add(db_packet)
        await _add_event(db, packet_id, "created", f"agent:{payload.metadata.source_agent.id}")
        await db.commit()
        await db.refresh(db_packet)

        logger.info(
            "packet_created",
            packet_id=packet_id,
            status=initial_status,
            source=payload.metadata.source_agent.id,
            target=payload.metadata.target_agent.id,
        )

        # Broadcast event to WebSocket subscribers
        await publish_event(
            event_type="packet.created",
            data={
                "status": initial_status,
                "metadata": metadata_dict,
            },
            packet_id=packet_id,
            tenant_id=api_key.tenant_id,
        )

        return _packet_to_response(db_packet)


# ── Read ────────────────────────────────────────────────────────────────────────


@router.get(
    "/{packet_id}",
    response_model=HandoffPacketResponse,
    responses={
        404: {"description": "Packet not found"},
    },
)
async def get_packet(
    packet_id: UUID,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> HandoffPacketResponse:
    """Get a single handoff packet by ID."""
    packet = await _get_packet_or_404(packet_id, db, tenant_id=api_key.tenant_id)
    return _packet_to_response(packet)


# ── Claim ──────────────────────────────────────────────────────────────────────


@router.post(
    "/{packet_id}/claim",
    response_model=HandoffPacketResponse,
    responses={
        404: {"description": "Packet not found"},
        409: {"description": "Packet already claimed or not claimable"},
        410: {"description": "Packet expired"},
    },
)
async def claim_packet(
    packet_id: UUID,
    payload: ClaimRequest,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> HandoffPacketResponse:
    """Claim a packet for processing.

    Only packets in 'created' or 'awaiting_human' status can be claimed.
    Conflict detection ensures only one agent can claim a packet.
    """
    packet = await _get_packet_or_404(packet_id, db, tenant_id=api_key.tenant_id)

    # Check if packet is expired
    if packet.status == "expired":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Packet {packet_id} has expired",
        )

    # Validate status transition
    try:
        transition = validate_transition(packet.status, "claimed")
    except InvalidTransitionError:
        # If already claimed, return conflict with current claimant info
        if packet.status == "claimed":
            metadata = packet.get_metadata()
            claimant = metadata.get("target_agent", {})
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": f"Packet {packet_id} is already claimed",
                    "claimed_by": claimant,
                },
            )
        raise

    now = datetime.now(timezone.utc)

    # Update status and claimant info
    packet.status = "claimed"
    packet.updated_at = now

    # Update metadata with claimant info and claimed_at timestamp
    metadata = packet.get_metadata()
    metadata["claimed_at"] = now.isoformat()
    metadata["target_agent"] = {
        "id": payload.agent_id,
        "name": payload.agent_name,
        "framework": payload.framework,
    }
    packet.set_metadata(metadata)

    await _add_event(
        db,
        packet.id,
        transition,
        f"agent:{payload.agent_id}",
        {"agent_name": payload.agent_name, "framework": payload.framework},
    )

    with trace_packet_operation("claim_packet", packet_id=str(packet_id), tenant_id=api_key.tenant_id) as span:
        span.set_attribute("claim.agent_id", payload.agent_id)
        span.set_attribute("packet.transition", transition)
        await db.commit()

    await db.refresh(packet)

    logger.info("packet_claimed", packet_id=str(packet_id), agent=payload.agent_id)

    # Broadcast event to WebSocket subscribers
    metadata = packet.get_metadata()
    await publish_event(
        event_type="packet.claimed",
        data={
            "status": "claimed",
            "metadata": metadata,
        },
        packet_id=str(packet_id),
        tenant_id=api_key.tenant_id,
    )

    return _packet_to_response(packet)


# ── Update (PATCH) ──────────────────────────────────────────────────────────────


@router.patch(
    "/{packet_id}",
    response_model=HandoffPacketResponse,
    responses={
        400: {"description": "Invalid status transition"},
        404: {"description": "Packet not found"},
    },
)
async def update_packet(
    packet_id: UUID,
    payload: HandoffPacketUpdate,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> HandoffPacketResponse:
    """Partially update a packet. Status transitions are validated against the state machine."""
    packet = await _get_packet_or_404(packet_id, db, tenant_id=api_key.tenant_id)

    now = datetime.now(timezone.utc)

    # Validate status transition if status is being changed
    if payload.status is not None and payload.status.value != packet.status:
        try:
            transition = validate_transition(packet.status, payload.status.value)
        except InvalidTransitionError:
            raise

        # Log the transition event
        actor = "system"
        metadata = packet.get_metadata()
        if metadata.get("target_agent"):
            actor = f"agent:{metadata['target_agent'].get('id', 'unknown')}"

        await _add_event(
            db,
            packet.id,
            transition,
            actor,
            {"from_status": packet.status, "to_status": payload.status.value},
        )

        packet.status = payload.status.value

        # Update timestamps based on transition
        if payload.status == PacketStatus.completed:
            metadata = packet.get_metadata()
            metadata["completed_at"] = now.isoformat()
            packet.set_metadata(metadata)

    # Update other fields if provided
    if payload.context is not None:
        packet.set_context(payload.context.model_dump(mode="json"))

    if payload.decisions is not None:
        # Merge: append new decisions to existing ones
        existing_decisions = packet.get_decisions()
        new_decisions = [d.model_dump(mode="json") for d in payload.decisions]
        existing_ids = {d["id"] for d in existing_decisions}
        for new_dec in new_decisions:
            if new_dec["id"] not in existing_ids:
                existing_decisions.append(new_dec)
            else:
                # Update existing decision by ID
                existing_decisions = [new_dec if d["id"] == new_dec["id"] else d for d in existing_decisions]
        packet.set_decisions(existing_decisions)

    if payload.actions is not None:
        # Merge actions
        existing_actions = packet.get_actions()
        new_actions = payload.actions.model_dump(mode="json")
        if "pending" in new_actions:
            existing_actions["pending"] = new_actions["pending"]
        if "completed" in new_actions:
            existing_actions["completed"] = new_actions["completed"]
        if "failed" in new_actions:
            existing_actions["failed"] = new_actions["failed"]
        packet.set_actions(existing_actions)

    if payload.dependencies is not None:
        packet.set_dependencies([d.model_dump(mode="json") for d in payload.dependencies])

    if payload.hitl is not None:
        packet.set_hitl(payload.hitl.model_dump(mode="json"))

    packet.updated_at = now

    with trace_packet_operation("update_packet", packet_id=str(packet_id), tenant_id=api_key.tenant_id) as span:
        if payload.status is not None:
            span.set_attribute("packet.new_status", payload.status.value)
        await db.commit()

    await db.refresh(packet)

    logger.info("packet_updated", packet_id=str(packet_id), status=payload.status)

    # Broadcast event to WebSocket subscribers
    await publish_event(
        event_type=f"packet.{payload.status.value if payload.status else 'updated'}",
        data={
            "status": packet.status,
            "metadata": packet.get_metadata(),
        },
        packet_id=str(packet_id),
        tenant_id=api_key.tenant_id,
    )

    return _packet_to_response(packet)


# ── Soft Delete ─────────────────────────────────────────────────────────────────


@router.delete(
    "/{packet_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"description": "Packet not found"},
        409: {"description": "Packet is already expired"},
    },
)
async def delete_packet(
    packet_id: UUID,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> None:
    """Soft-delete a packet by marking it as expired.

    The packet is not removed from the database — its status is set to 'expired'.
    """
    packet = await _get_packet_or_404(packet_id, db, tenant_id=api_key.tenant_id)

    if packet.status == "expired":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Packet {packet_id} is already expired",
        )

    # Validate transition to expired
    try:
        transition = validate_transition(packet.status, "expired")
    except InvalidTransitionError:
        raise

    now = datetime.now(timezone.utc)
    previous_status = packet.status
    packet.status = "expired"
    packet.updated_at = now

    await _add_event(
        db,
        packet.id,
        transition,
        "system:soft_delete",
        {"previous_status": previous_status, "reason": "soft_delete"},
    )

    with trace_packet_operation("delete_packet", packet_id=str(packet_id), tenant_id=api_key.tenant_id) as span:
        span.set_attribute("packet.previous_status", previous_status)
        await db.commit()

    logger.info("packet_soft_deleted", packet_id=str(packet_id), previous_status=previous_status)

    # Broadcast event to WebSocket subscribers
    await publish_event(
        event_type="packet.expired",
        data={
            "status": "expired",
            "metadata": packet.get_metadata(),
        },
        packet_id=str(packet_id),
        tenant_id=api_key.tenant_id,
    )


# ── HITL Respond ────────────────────────────────────────────────────────────────


@router.post(
    "/{packet_id}/respond",
    response_model=HandoffPacketResponse,
    responses={
        400: {"description": "Invalid request"},
        404: {"description": "Packet not found"},
        409: {"description": "Packet not in awaiting_human status"},
    },
)
async def respond_to_hitl(
    packet_id: UUID,
    payload: HitlRespondRequest,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> HandoffPacketResponse:
    """Submit a human response to a HITL checkpoint.

    Only works on packets in 'awaiting_human' status.
    After response, the packet transitions to 'claimed' or 'in_progress'.
    """
    packet = await _get_packet_or_404(packet_id, db, tenant_id=api_key.tenant_id)

    if packet.status != "awaiting_human":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Packet is in '{packet.status}' status, not 'awaiting_human'. Cannot respond.",
        )

    hitl = packet.get_hitl()
    if hitl is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Packet has no HITL checkpoint",
        )

    now = datetime.now(timezone.utc)

    # Update HITL checkpoint with the response
    hitl["response"] = payload.response
    hitl["responded_at"] = now.isoformat()
    hitl["responded_by"] = payload.responded_by
    if payload.notes:
        hitl["notes"] = payload.notes
    packet.set_hitl(hitl)

    # Transition status: awaiting_human -> claimed (agent picks up) or in_progress
    # Default to "claimed" so the next agent can pick it up
    new_status = "claimed"
    transition = validate_transition(packet.status, new_status)
    packet.status = new_status
    packet.updated_at = now

    # Update metadata with responded_by
    metadata = packet.get_metadata()
    metadata["claimed_at"] = now.isoformat()
    packet.set_metadata(metadata)

    await _add_event(
        db,
        packet.id,
        "hitl_responded",
        f"human:{payload.responded_by}",
        {
            "response": payload.response,
            "notes": payload.notes,
            "transition_to": new_status,
        },
    )

    with trace_packet_operation("hitl_respond", packet_id=str(packet_id), tenant_id=api_key.tenant_id) as span:
        span.set_attribute("hitl.responded_by", payload.responded_by)
        span.set_attribute("packet.new_status", "claimed")
        await db.commit()

    await db.refresh(packet)

    logger.info("hitl_responded", packet_id=str(packet_id), responded_by=payload.responded_by)

    # Broadcast event to WebSocket subscribers
    await publish_event(
        event_type="hitl.response_ready",
        data={
            "status": packet.status,
            "metadata": packet.get_metadata(),
            "hitl_response": payload.response,
        },
        packet_id=str(packet_id),
        tenant_id=api_key.tenant_id,
    )

    return _packet_to_response(packet)


# ── Event History ────────────────────────────────────────────────────────────────


@router.get(
    "/{packet_id}/history",
    response_model=PacketHistoryResponse,
    responses={
        404: {"description": "Packet not found"},
    },
)
async def get_packet_history(
    packet_id: UUID,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> PacketHistoryResponse:
    """Return all status transitions and events for a packet.

    Returns timestamps and actor information for each event.
    """
    # Verify packet exists (tenant-scoped)
    await _get_packet_or_404(packet_id, db, tenant_id=api_key.tenant_id)

    result = await db.execute(
        select(PacketEvent)
        .where(PacketEvent.packet_id == str(packet_id))
        .order_by(PacketEvent.timestamp.asc())
    )
    events = result.scalars().all()

    from app.models.packet import PacketEventResponse

    return PacketHistoryResponse(
        packet_id=str(packet_id),
        events=[
            PacketEventResponse(
                id=e.id,
                packet_id=e.packet_id,
                event_type=e.event_type,
                actor=e.actor,
                details=e.get_details(),
                timestamp=e.timestamp,
            )
            for e in events
        ],
    )


# ── Chain ───────────────────────────────────────────────────────────────────────


@router.post(
    "/{packet_id}/chain",
    response_model=HandoffPacketResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Parent packet not found"},
    },
)
async def chain_packet(
    packet_id: UUID,
    payload: ChainRequest,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> HandoffPacketResponse:
    """Create a new packet that continues from the current one.

    Automatically sets parent_packet_id to the current packet's ID
    and links context from the parent.
    """
    # Verify parent packet exists (tenant-scoped)
    parent = await _get_packet_or_404(packet_id, db, tenant_id=api_key.tenant_id)

    new_id = str(uuid4())
    now = datetime.now(timezone.utc)

    # Determine initial status
    initial_status = "created"
    if payload.hitl is not None and payload.hitl.required:
        initial_status = "awaiting_human"

    # Build metadata dict
    metadata_dict = payload.metadata.model_dump(mode="json")
    if metadata_dict.get("created_at") is None:
        metadata_dict["created_at"] = now.isoformat()

    # Build context dict — inherit parent's conversation state as prefix
    context_dict = payload.context.model_dump(mode="json")
    parent_context = parent.get_context()
    if parent_context.get("conversation_state"):
        # Merge parent conversation into the new packet's context
        existing_conv = context_dict.get("conversation_state", [])
        parent_conv = parent_context.get("conversation_state", [])
        # Only add parent conversations that aren't already referenced
        merged_conv = parent_conv + existing_conv
        context_dict["conversation_state"] = merged_conv

    # Build decisions, actions, dependencies dicts
    decisions_list = [d.model_dump(mode="json") for d in payload.decisions]
    actions_dict = payload.actions.model_dump(mode="json")
    dependencies_list = [d.model_dump(mode="json") for d in payload.dependencies]
    hitl_dict = payload.hitl.model_dump(mode="json") if payload.hitl else None

    db_packet = Packet(
        id=new_id,
        version="1.0.0",
        parent_packet_id=str(packet_id),
        status=initial_status,
        tenant_id=api_key.tenant_id,
        metadata_json=json.dumps(metadata_dict, default=str),
        context_json=json.dumps(context_dict, default=str),
        decisions_json=json.dumps(decisions_list, default=str),
        actions_json=json.dumps(actions_dict, default=str),
        dependencies_json=json.dumps(dependencies_list, default=str),
        hitl_json=json.dumps(hitl_dict, default=str) if hitl_dict else None,
        created_at=now,
        updated_at=now,
    )

    db.add(db_packet)
    await _add_event(
        db,
        new_id,
        "created",
        f"agent:{payload.metadata.source_agent.id}",
        {"parent_packet_id": str(packet_id), "chain": True},
    )
    # Also add an event on the parent packet
    await _add_event(
        db,
        str(packet_id),
        "chained",
        f"agent:{payload.metadata.source_agent.id}",
        {"child_packet_id": new_id},
    )

    with trace_packet_operation("chain_packet", packet_id=new_id, tenant_id=api_key.tenant_id) as span:
        span.set_attribute("packet.parent_packet_id", str(packet_id))
        span.set_attribute("packet.initial_status", initial_status)
        await db.commit()

    await db.refresh(db_packet)

    logger.info(
        "packet_chained",
        parent_packet_id=str(packet_id),
        child_packet_id=new_id,
        status=initial_status,
    )

    # Broadcast event to WebSocket subscribers
    await publish_event(
        event_type="packet.chained",
        data={
            "status": initial_status,
            "metadata": metadata_dict,
            "parent_packet_id": str(packet_id),
        },
        packet_id=new_id,
        tenant_id=api_key.tenant_id,
    )

    return _packet_to_response(db_packet)
