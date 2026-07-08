"""Initial schema — all tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-26

Creates all HandoffRail tables: packets, packet_events, webhooks,
api_keys, webhook_deliveries.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── packets ──────────────────────────────────────────────────────────────
    op.create_table(
        "packets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(16), nullable=False, server_default="1.0.0"),
        sa.Column("parent_packet_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default"),
        sa.Column("metadata_json", sa.Text, nullable=False),
        sa.Column("context_json", sa.Text, nullable=False),
        sa.Column("decisions_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("actions_json", sa.Text, nullable=False,
                  server_default='{"pending":[],"completed":[],"failed":[]}'),
        sa.Column("dependencies_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("hitl_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_packets_parent_packet_id", "packets", ["parent_packet_id"])
    op.create_index("ix_packets_status", "packets", ["status"])
    op.create_index("ix_packets_tenant_id", "packets", ["tenant_id"])

    # ── packet_events ────────────────────────────────────────────────────────
    op.create_table(
        "packet_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("packet_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("details_json", sa.Text, nullable=True),
        sa.Column("timestamp", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_packet_events_packet_id", "packet_events", ["packet_id"])
    op.create_index("ix_packet_events_event_type", "packet_events", ["event_type"])

    # ── webhooks ─────────────────────────────────────────────────────────────
    op.create_table(
        "webhooks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("events", sa.Text, nullable=False),
        sa.Column("secret", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_webhooks_tenant_id", "webhooks", ["tenant_id"])

    # ── api_keys ─────────────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default"),
        sa.Column("tier", sa.String(32), nullable=False, server_default="free"),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("rotated_from", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_rotated_from", "api_keys", ["rotated_from"])

    # ── webhook_deliveries ───────────────────────────────────────────────────
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("webhook_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default"),
        sa.Column("packet_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("last_status_code", sa.Integer, nullable=True),
        sa.Column("next_retry_at", sa.DateTime, nullable=True),
        sa.Column("delivered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_webhook_deliveries_webhook_id", "webhook_deliveries", ["webhook_id"])
    op.create_index("ix_webhook_deliveries_tenant_id", "webhook_deliveries", ["tenant_id"])
    op.create_index("ix_webhook_deliveries_packet_id", "webhook_deliveries", ["packet_id"])
    op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status"])
    op.create_index("ix_webhook_deliveries_next_retry_at", "webhook_deliveries", ["next_retry_at"])


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("api_keys")
    op.drop_table("webhooks")
    op.drop_table("packet_events")
    op.drop_table("packets")
