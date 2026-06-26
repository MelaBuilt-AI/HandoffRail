"""HandoffRail API Server — SQLAlchemy database models."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, String, Text, func
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

    # Stored as JSON blobs for flexibility — the Pydantic models validate structure
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    decisions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    actions_json: Mapped[str] = mapped_column(Text, nullable=False, default='{"pending":[],"completed":[],"failed":[]}')
    dependencies_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    hitl_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    def get_metadata(self) -> dict:
        return json.loads(self.metadata_json)

    def set_metadata(self, value: dict) -> None:
        self.metadata_json = json.dumps(value, default=str)

    def get_context(self) -> dict:
        return json.loads(self.context_json)

    def set_context(self, value: dict) -> None:
        self.context_json = json.dumps(value, default=str)

    def get_decisions(self) -> list:
        return json.loads(self.decisions_json)

    def set_decisions(self, value: list) -> None:
        self.decisions_json = json.dumps(value, default=str)

    def get_actions(self) -> dict:
        return json.loads(self.actions_json)

    def set_actions(self, value: dict) -> None:
        self.actions_json = json.dumps(value, default=str)

    def get_dependencies(self) -> list:
        return json.loads(self.dependencies_json)

    def set_dependencies(self, value: list) -> None:
        self.dependencies_json = json.dumps(value, default=str)

    def get_hitl(self) -> dict | None:
        if self.hitl_json is None:
            return None
        return json.loads(self.hitl_json)

    def set_hitl(self, value: dict | None) -> None:
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

    def get_details(self) -> dict | None:
        if self.details_json is None:
            return None
        return json.loads(self.details_json)

    def set_details(self, value: dict | None) -> None:
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
        return json.loads(self.events)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
