"""Add tenants table, admin column to api_keys.

Revision ID: 0002_tenants
Revises: 0001_initial
Create Date: 2026-07-07

Creates the tenants table for multi-tenant isolation, adds an `admin`
boolean column to the api_keys table, and inserts a default tenant for
existing single-tenant users.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_tenants"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Create tenants table ────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("tier", sa.String(32), nullable=False, server_default="free"),
        sa.Column("handoffs_per_day", sa.Integer, nullable=False, server_default="5"),
        sa.Column("max_api_keys", sa.Integer, nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
    )

    # ── Insert default tenant for existing single-tenant users ──────────────
    op.execute(
        sa.text(
            "INSERT OR IGNORE INTO tenants (id, name, tier, handoffs_per_day, max_api_keys, created_at, updated_at) "
            "VALUES ('default', 'Default Tenant', 'free', 10000, 25, datetime('now'), datetime('now'))"
        )
    )

    # ── Add admin column to api_keys ─────────────────────────────────────────
    op.add_column(
        "api_keys",
        sa.Column("admin", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "admin")
    op.drop_table("tenants")
