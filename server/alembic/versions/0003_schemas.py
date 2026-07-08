"""Add schemas table for JSON Schema registry.

Revision ID: 0003_schemas
Revises: 0002_tenants
Create Date: 2026-07-08

Creates the schemas table for registering named JSON Schema documents
that can be used to validate packet context fields during creation.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_schemas"
down_revision = "0002_tenants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schemas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("json_schema", sa.Text, nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_schemas_name", "schemas", ["name"])
    op.create_index("ix_schemas_tenant_id", "schemas", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("schemas")
