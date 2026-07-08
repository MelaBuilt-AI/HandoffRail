"""HandoffRail SDK — Data models that mirror the server's Pydantic schemas.

These models are standalone (no dependency on the server package) and provide
from_dict / to_dict helpers for serialization. They use Pydantic v2 for
validation but are intentionally kept simple so they can also be used as
plain data-transfer objects.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# ── Enums ──────────────────────────────────────────────────────────────────────


class Priority(StrEnum):
    low = "low"
    normal = "normal"
    high = "high"
    critical = "critical"


class PacketStatus(StrEnum):
    created = "created"
    claimed = "claimed"
    in_progress = "in_progress"
    awaiting_human = "awaiting_human"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class ConversationRole(StrEnum):
    user = "user"
    agent = "agent"
    system = "system"
    human = "human"


class DependencyType(StrEnum):
    data = "data"
    api = "api"
    human_approval = "human_approval"
    external_event = "external_event"
    resource = "resource"


class DependencyStatus(StrEnum):
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentInfo:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class TargetAgentInfo(BaseModel):
    """Target agent identity — framework is optional."""

    id: str
    name: str
    framework: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetAgentInfo:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class ContextEntry(BaseModel):
    """A single conversation turn in the packet context."""

    role: ConversationRole
    content: str
    timestamp: datetime | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextEntry:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class Artifact(BaseModel):
    """A named artifact produced during the session."""

    key: str
    value: str | dict[str, Any] | list[Any]
    content_type: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Artifact:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class Decision(BaseModel):
    """A decision made during the session."""

    id: str
    decision: str
    rationale: str
    alternatives: list[str] = Field(default_factory=list)
    decided_by: str | None = None
    timestamp: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Decision:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class PendingAction(BaseModel):
    """A pending action to be handled by the target agent."""

    id: str
    description: str
    assignee: str
    priority: Priority | None = None
    depends_on: list[str] = Field(default_factory=list)
    deadline: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingAction:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class CompletedAction(BaseModel):
    """A completed action."""

    id: str
    description: str
    result: str
    completed_by: str | None = None
    completed_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompletedAction:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class FailedAction(BaseModel):
    """A failed action."""

    id: str
    description: str
    error: str
    retries_remaining: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailedAction:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class Actions(BaseModel):
    """All actions associated with the packet."""

    pending: list[PendingAction] = Field(default_factory=list)
    completed: list[CompletedAction] = Field(default_factory=list)
    failed: list[FailedAction] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Actions:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class Dependency(BaseModel):
    """An external dependency the receiving agent should know about."""

    id: str
    type: DependencyType
    description: str
    status: DependencyStatus = DependencyStatus.unknown
    source: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Dependency:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HitlCheckpoint:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class Metadata(BaseModel):
    """Packet metadata — source/target agents, timestamps, priority."""

    source_agent: AgentInfo
    target_agent: TargetAgentInfo
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    priority: Priority = Priority.normal
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Metadata:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class PacketContext(BaseModel):
    """The context section of a handoff packet."""

    summary: str
    conversation_state: list[ContextEntry] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    custom: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PacketContext:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


# ── Request / Response Models ──────────────────────────────────────────────────


class PacketCreate(BaseModel):
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
    def validate_hitl(cls, v: HitlCheckpoint | None) -> HitlCheckpoint | None:
        if v is not None and v.required and not v.reason:
            msg = "HITL checkpoint with required=true must include a reason"
            raise ValueError(msg)
        return v

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PacketCreate:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class PacketResponse(BaseModel):
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PacketResponse:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class PacketListResponse(BaseModel):
    """Paginated list of packet responses."""

    packets: list[PacketResponse]
    total: int
    limit: int
    offset: int
    next_cursor: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PacketListResponse:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class PacketClaim(BaseModel):
    """Request body for claiming a packet."""

    agent_id: str
    agent_name: str
    framework: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PacketClaim:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class PacketUpdate(BaseModel):
    """Request body for partially updating a packet."""

    status: PacketStatus | None = None
    context: PacketContext | None = None
    decisions: list[Decision] | None = None
    actions: Actions | None = None
    dependencies: list[Dependency] | None = None
    hitl: HitlCheckpoint | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PacketUpdate:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        data_out = self.model_dump(mode="json", exclude_none=True)
        return data_out


class WebhookCreate(BaseModel):
    """Request body for registering a webhook."""

    url: str
    events: list[str] = Field(
        default_factory=lambda: ["packet.created", "packet.claimed", "packet.completed", "packet.failed"],
    )
    secret: str = Field(..., min_length=16)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            msg = "Webhook URL must start with http:// or https://"
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebhookCreate:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class WebhookResponse(BaseModel):
    """Response for a registered webhook."""

    id: str
    url: str
    events: list[str]
    tenant_id: str
    active: bool
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebhookResponse:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class PacketEvent(BaseModel):
    """A single event in the packet history audit trail."""

    id: str
    packet_id: str
    event_type: str
    actor: str
    details: dict[str, Any] | None = None
    timestamp: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PacketEvent:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class PacketHistoryResponse(BaseModel):
    """Response for packet event history."""

    packet_id: str
    events: list[PacketEvent]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PacketHistoryResponse:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class AuditLogEntry(BaseModel):
    """Structured audit log entry."""

    id: str
    packet_id: str
    actor: str
    action: str
    resource: str = "packet"
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class AuditLogResponse(BaseModel):
    """Paginated structured audit log response."""

    entries: list[AuditLogEntry]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditLogResponse:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class HitlRespondRequest(BaseModel):
    """Request body for responding to a HITL checkpoint."""

    response: str
    responded_by: str
    notes: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HitlRespondRequest:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class ChainHandoffRequest(BaseModel):
    """Request body for creating a chained follow-up packet."""

    metadata: Metadata
    context: PacketContext
    decisions: list[Decision] = Field(default_factory=list)
    actions: Actions = Field(default_factory=Actions)
    dependencies: list[Dependency] = Field(default_factory=list)
    hitl: HitlCheckpoint | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChainHandoffRequest:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


# ── Batch Operations ───────────────────────────────────────────────────────────


class BatchCreateError(BaseModel):
    """Error entry for a single packet in a batch create response."""

    index: int
    error: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchCreateError:
        return cls.model_validate(data)


class BatchCreateResponse(BaseModel):
    """Response for batch packet creation."""

    created: list[PacketResponse]
    errors: list[BatchCreateError] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchCreateResponse:
        return cls(
            created=[PacketResponse.from_dict(p) for p in data.get("created", [])],
            errors=[BatchCreateError.from_dict(e) for e in data.get("errors", [])],
        )


class BatchClaimRequest(BaseModel):
    """Request body for batch packet claiming."""

    packet_ids: list[str]
    agent_id: str
    agent_name: str
    framework: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class BatchClaimError(BaseModel):
    """Error entry for a single packet in a batch claim response."""

    packet_id: str
    error: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchClaimError:
        return cls.model_validate(data)


class BatchClaimResponse(BaseModel):
    """Response for batch packet claiming."""

    claimed: list[PacketResponse]
    errors: list[BatchClaimError] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchClaimResponse:
        return cls(
            claimed=[PacketResponse.from_dict(p) for p in data.get("claimed", [])],
            errors=[BatchClaimError.from_dict(e) for e in data.get("errors", [])],
        )


class BatchCompleteRequest(BaseModel):
    """Request body for batch packet completion."""

    packet_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class BatchCompleteError(BaseModel):
    """Error entry for a single packet in a batch complete response."""

    packet_id: str
    error: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchCompleteError:
        return cls.model_validate(data)


class BatchCompleteResponse(BaseModel):
    """Response for batch packet completion."""

    completed: list[PacketResponse]
    errors: list[BatchCompleteError] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchCompleteResponse:
        return cls(
            completed=[PacketResponse.from_dict(p) for p in data.get("completed", [])],
            errors=[BatchCompleteError.from_dict(e) for e in data.get("errors", [])],
        )


# ── Search ─────────────────────────────────────────────────────────────────────


class SearchOptions(BaseModel):
    """Options for packet search."""

    limit: int = 50
    offset: int = 0
    status: str | None = None
    priority: str | None = None

    def to_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": self.limit, "offset": self.offset}
        if self.status:
            params["status"] = self.status
        if self.priority:
            params["priority"] = self.priority
        return params


# ── API Keys ─────────────────────────────────────────────────────────────────────


class ApiKeyCreate(BaseModel):
    """Request body for creating a new API key."""

    name: str
    tenant_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApiKeyCreate:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class ApiKeyResponse(BaseModel):
    """Response for an API key (includes the plain key only on creation)."""

    id: str
    name: str
    key_prefix: str
    tenant_id: str
    revoked: bool
    created_at: datetime
    key: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApiKeyResponse:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


# ── Tenant Management ───────────────────────────────────────────────────────────


class TenantCreate(BaseModel):
    """Request body for creating a new tenant."""

    name: str
    tier: str = "free"
    handoffs_per_day: int | None = None
    max_api_keys: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TenantCreate:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class TenantUpdate(BaseModel):
    """Request body for updating a tenant."""

    name: str | None = None
    tier: str | None = None
    handoffs_per_day: int | None = None
    max_api_keys: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TenantUpdate:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class TenantResponse(BaseModel):
    """Response from the tenant management API."""

    id: str
    name: str
    tier: str
    handoffs_per_day: int | None = None
    max_api_keys: int | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TenantResponse:
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)
