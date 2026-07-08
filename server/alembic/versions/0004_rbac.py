"""Add role column to api_keys table for RBAC.

Revision ID: 0004_rbac
Revises: 0003_schemas
Create Date: 2026-07-08

Adds a `role` column (String, default "admin") to the api_keys table.
Existing keys with admin=True get role="admin"; others get role="admin"
for backward compatibility (default role is admin).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_rbac"
down_revision = "0003_schemas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("role", sa.String(32), nullable=False, server_default="admin"))


def downgrade() -> None:
    op.drop_column("api_keys", "role")
