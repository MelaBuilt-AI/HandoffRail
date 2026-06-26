"""HandoffRail API Server — Pydantic models for v1 packet schema."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ── Enums ──────────────────────────────────────────────────────────────────────


class Priority(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"
    critical = "critical"


class PacketStatus(str, Enum):
    created = "created"
    claimed = "claimed"
    in_progress = "in_progress"
    awaiting_human = "awaiting_human"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class ConversationRole(str, Enum):
    user = "user"
    agent = "agent"
    system = "system"
    human = "human"


class DependencyType(str, Enum):
    data = "data"
    api = "api"
    human_approval = "human_approval"
    external_event = "external_event"
    resource = "resource"


class DependencyStatus(str, Enum):
    blocked = "blocked"
    available = "available"
    unknown = "unknown"


# ── Nested Models ──────────────────────────────────────────────────────────────


class AgentInfo(BaseModel):
    """Agent identity information."""

    id: str
    name: str
    framework: str | None = None
    version: str | None = None


class TargetAgentInfo(BaseModel):
    """Target agent identity — framework is optional."""

    id: str
    name: str
    framework: str | None = None


class ContextEntry(BaseModel):
    """A single conversation turn in the packet context."""

    role: ConversationRole
    content: str
    timestamp: datetime | None = None
    metadata: dict[str, Any] | None = None


class Artifact(BaseModel):
    """A named artifact produced during the session."""

    key: str
    value: str | dict[str, Any] | list[Any]
    content_type: str | None = None


class Decision(BaseModel):
    """A decision made during the session."""

    id: str
    decision: str
    rationale: str
    alternatives: list[str] = Field(default_factory=list)
    decided_by: str | None = None
    timestamp: datetime | None = None


class PendingAction(BaseModel):
    """A pending action to be handled by the target agent."""

    id: str
    description: str
    assignee: str
    priority: Priority | None = None
    depends_on: list[str] = Field(default_factory=list)
    deadline: datetime | None = None


class CompletedAction(BaseModel):
    """A completed action."""

    id: str
    description: str
    result: str
    completed_by: str | None = None
    completed_at: datetime | None = None


class FailedAction(BaseModel):
    """A failed action."""

    id: str
    description: str
    error: str
    retries_remaining: int | None = None


class Actions(BaseModel):
    """All actions associated with the packet."""

    pending: list[PendingAction] = Field(default_factory=list)
    completed: list[CompletedAction] = Field(default_factory=list)
    failed: list[FailedAction] = Field(default_factory=list)


class Dependency(BaseModel):
    """An external dependency the receiving agent should know about."""

    id: str
    type: DependencyType
    description: str
    status: DependencyStatus = DependencyStatus.unknown
    source: str | None = None


class HitlCheckpoint(BaseModel):
    """Human-in-the-loop checkpoint."""

    required: bool = True
    reason: str
    question: str | None = None
    options: list[str] | None = None
    response: str | None = None
    responded_at: datetime | None = None
    responded_by: str | None = None
    notes: str | None = None
    timeout_seconds: int | None = None


class Metadata(BaseModel):
    """Packet metadata — source/target agents, timestamps, priority."""

    source_agent: AgentInfo
    target_agent: TargetAgentInfo
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    priority: Priority = Priority.normal
    tags: list[str] = Field(default_factory=list)


class PacketContext(BaseModel):
    """The context section of a handoff packet."""

    summary: str
    conversation_state: list[ContextEntry] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    custom: dict[str, Any] = Field(default_factory=dict)


# ── Create / Update / Response Models ──────────────────────────────────────────


class HandoffPacketCreate(BaseModel):
    """Request body for creating a new handoff packet."""

    parent_packet_id: UUID | None = None
    metadata: Metadata
    context: PacketContext
    decisions: list[Decision] = Field(default_factory=list)
    actions: Actions = Field(default_factory=Actions)
    dependencies: list[Dependency] = Field(default_factory=list)
    hitl: HitlCheckpoint | None = None

    @field_validator("hitl")
    @classmethod
    def validate_hitl(cls, v: HitlCheckpoint | None, info: Any) -> HitlCheckpoint | None:
        """If HITL is provided and required, ensure reason is present."""
        if v is not None and v.required and not v.reason:
            msg = "HITL checkpoint with required=true must include a reason"
            raise ValueError(msg)
        return v


class HandoffPacketUpdate(BaseModel):
    """Request body for partially updating a packet."""

    status: PacketStatus | None = None
    context: PacketContext | None = None
    decisions: list[Decision] | None = None
    actions: Actions | None = None
    dependencies: list[Dependency] | None = None
    hitl: HitlCheckpoint | None = None


class HandoffPacketResponse(BaseModel):
    """Full packet response returned from the API."""

    id: UUID
    version: str = "1.0.0"
    parent_packet_id: UUID | None = None
    metadata: Metadata
    context: PacketContext
    decisions: list[Decision] = Field(default_factory=list)
    actions: Actions = Field(default_factory=Actions)
    dependencies: list[Dependency] = Field(default_factory=list)
    hitl: HitlCheckpoint | None = None
    status: PacketStatus = PacketStatus.created
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PacketLinks(BaseModel):
    """HATEOAS links for a packet response."""

    self: str
    claim: str
    history: str


class HandoffPacketResponseWithLinks(HandoffPacketResponse):
    """Packet response with HATEOAS links."""

    _links: PacketLinks


class PacketListResponse(BaseModel):
    """Paginated list of packet summaries."""

    packets: list[HandoffPacketResponse]
    total: int
    limit: int
    offset: int


class ClaimRequest(BaseModel):
    """Request body for claiming a packet."""

    agent_id: str
    agent_name: str
    framework: str | None = None


class ClaimResponse(BaseModel):
    """Response after successfully claiming a packet."""

    id: UUID
    status: PacketStatus
    claimed_by: AgentInfo
    claimed_at: datetime


class HitlRespondRequest(BaseModel):
    """Request body for responding to a HITL checkpoint."""

    response: str
    responded_by: str
    notes: str | None = None


class ApiKeyCreate(BaseModel):
    """Request body for creating a new API key."""

    name: str
    tenant_id: str | None = None


class ApiKeyResponse(BaseModel):
    """Response for an API key (includes the plain key only on creation)."""

    id: str
    name: str
    key_prefix: str
    tenant_id: str
    revoked: bool
    created_at: datetime
    key: str | None = None  # Only populated on creation


class WebhookCreate(BaseModel):
    """Request body for registering a webhook."""

    url: str = Field(..., description="Webhook callback URL")
    events: list[str] = Field(
        default_factory=lambda: ["packet.created", "packet.claimed", "packet.completed", "packet.failed"],
        description="Event types to subscribe to",
    )
    secret: str = Field(..., min_length=16, max_length=256, description="Secret for HMAC-SHA256 signing")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            msg = "Webhook URL must start with http:// or https://"
            raise ValueError(msg)
        # SSRF protection — block private/internal/metadata endpoints
        from app.services.ssrf import is_url_safe
        is_safe, reason = is_url_safe(v)
        if not is_safe:
            msg = f"Webhook URL blocked: {reason}"
            raise ValueError(msg)
        return v

    @field_validator("events")
    @classmethod
    def validate_events(cls, v: list[str]) -> list[str]:
        valid_events = {
            "packet.created",
            "packet.claimed",
            "packet.in_progress",
            "packet.awaiting_human",
            "packet.completed",
            "packet.failed",
            "packet.expired",
            "hitl.response_ready",
        }
        for event in v:
            if event not in valid_events:
                msg = f"Invalid event type: {event}. Valid events: {sorted(valid_events)}"
                raise ValueError(msg)
        return v


class WebhookResponse(BaseModel):
    """Response for a registered webhook."""

    id: str
    url: str
    events: list[str]
    tenant_id: str
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PacketEventResponse(BaseModel):
    """Response for a single packet event in the history."""

    id: str
    packet_id: str
    event_type: str
    actor: str
    details: dict[str, Any] | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class PacketHistoryResponse(BaseModel):
    """Response for packet event history."""

    packet_id: str
    events: list[PacketEventResponse]


class ChainRequest(BaseModel):
    """Request body for creating a chained follow-up packet."""

    metadata: Metadata
    context: PacketContext
    decisions: list[Decision] = Field(default_factory=list)
    actions: Actions = Field(default_factory=Actions)
    dependencies: list[Dependency] = Field(default_factory=list)
    hitl: HitlCheckpoint | None = None


class RateLimitInfo(BaseModel):
    """Rate limit information for response headers."""

    limit: int
    remaining: int
    reset: int  # seconds until reset
    tier: str


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
    field: str | None = None
