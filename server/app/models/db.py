"""HandoffRail API Server — SQLAlchemy database models."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class Packet(Base):
    """Persistent storage for handoff packets."""

    __tablename__ = "packets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    parent_packet_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created", index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="default", index=True)

    # Stored as JSON blobs for flexibility — the Pydantic models validate structure
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    decisions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    actions_json: Mapped[str] = mapped_column(Text, nullable=False, default='{"pending":[],"completed":[],"failed":[]}')
    dependencies_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    hitl_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def get_metadata(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.metadata_json)
        return result

    def set_metadata(self, value: dict[str, Any]) -> None:
        self.metadata_json = json.dumps(value, default=str)

    def get_context(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.context_json)
        return result

    def set_context(self, value: dict[str, Any]) -> None:
        self.context_json = json.dumps(value, default=str)

    def get_decisions(self) -> list[Any]:
        result: list[Any] = json.loads(self.decisions_json)
        return result

    def set_decisions(self, value: list[Any]) -> None:
        self.decisions_json = json.dumps(value, default=str)

    def get_actions(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.actions_json)
        return result

    def set_actions(self, value: dict[str, Any]) -> None:
        self.actions_json = json.dumps(value, default=str)

    def get_dependencies(self) -> list[Any]:
        result: list[Any] = json.loads(self.dependencies_json)
        return result

    def set_dependencies(self, value: list[Any]) -> None:
        self.dependencies_json = json.dumps(value, default=str)

    def get_hitl(self) -> dict[str, Any] | None:
        if self.hitl_json is None:
            return None
        result: dict[str, Any] = json.loads(self.hitl_json)
        return result

    def set_hitl(self, value: dict[str, Any] | None) -> None:
        self.hitl_json = json.dumps(value, default=str) if value is not None else None


class PacketEvent(Base):
    """Audit trail for packet lifecycle events."""

    __tablename__ = "packet_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    packet_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    def get_details(self) -> dict[str, Any] | None:
        if self.details_json is None:
            return None
        result: dict[str, Any] = json.loads(self.details_json)
        return result

    def set_details(self, value: dict[str, Any] | None) -> None:
        self.details_json = json.dumps(value, default=str) if value is not None else None


class Webhook(Base):
    """Webhook registration for packet status change notifications."""

    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    events: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of event types
    secret: Mapped[str] = mapped_column(String(128), nullable=False)  # HMAC signing secret
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True, default="default")
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    def get_events(self) -> list[str]:
        result: list[str] = json.loads(self.events)
        return result

    def set_events(self, value: list[str]) -> None:
        self.events = json.dumps(value)


class ApiKey(Base):
    """API key for authentication and tenant scoping."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True, default="default")
    tier: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rotated_from: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WebhookDelivery(Base):
    """Webhook delivery attempt log — tracks retries and dead letter queue."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    webhook_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True, default="default")
    packet_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    # pending → delivering → delivered → failed → dead_letter
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
