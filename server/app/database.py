"""HandoffRail API Server — Database setup.

Supports both SQLite (dev) and PostgreSQL (prod) via DATABASE_URL env var.
URL scheme detection:
  - sqlite+aiosqlite://... → SQLite (default for dev)
  - postgresql+asyncpg://... → PostgreSQL (prod)
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine

from app.models.db import Base

# Detect database URL from environment or default to SQLite
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./handoffrail.db")


def _build_database_url(url: str | None = None) -> str:
    """Build the database URL, converting plain postgres:// to asyncpg scheme.

    If a raw DATABASE_URL like 'postgresql://user:pass@host/db' is provided,
    convert it to 'postgresql+asyncpg://user:pass@host/db' for SQLAlchemy async.

    Args:
        url: Database URL string. Falls back to DATABASE_URL env var or SQLite default.

    Returns:
        Properly formatted async database URL.
    """
    resolved = url or os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./handoffrail.db")

    # Convert plain postgresql:// to asyncpg scheme
    if resolved.startswith("postgresql://") and "+asyncpg" not in resolved:
        resolved = resolved.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Convert postgres:// shorthand
    if resolved.startswith("postgres://"):
        resolved = resolved.replace("postgres://", "postgresql+asyncpg://", 1)

    return resolved


def _get_engine_kwargs(url: str) -> dict[str, Any]:
    """Get engine kwargs based on database type.

    SQLite needs check_same_thread=False for async; PostgreSQL gets pool settings.
    """
    if url.startswith("sqlite"):
        return {"echo": False}
    # PostgreSQL / other — production pool settings
    return {
        "echo": False,
        "pool_size": 20,
        "max_overflow": 10,
        "pool_pre_ping": True,
    }


def is_postgres_url(url: str | None = None) -> bool:
    """Check if the database URL points to PostgreSQL.

    Args:
        url: URL to check. Falls back to DATABASE_URL env var or default.

    Returns:
        True if the URL is a PostgreSQL connection string.
    """
    resolved = url or os.environ.get("DATABASE_URL", "")
    return resolved.startswith("postgresql") or resolved.startswith("postgres")


# Build the engine using URL detection
_resolved_url = _build_database_url(DATABASE_URL)
engine = create_async_engine(_resolved_url, **_get_engine_kwargs(_resolved_url))
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async database session."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables. Used during app startup for SQLite dev mode.

    In production with PostgreSQL, Alembic migrations should be used instead.
    This is safe to call regardless — create_all is idempotent.
    Also sets up full-text search indexes (FTS5 for SQLite, tsvector for PostgreSQL)
    and seeds the default tenant for dev mode.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _init_fts(conn)
        await _seed_default_tenant(conn)


async def _init_fts(conn: AsyncConnection) -> None:
    """Initialize full-text search tables/indexes.

    SQLite: creates an FTS5 virtual table with triggers to keep it in sync.
    PostgreSQL: creates a tsvector generated column with a GIN index.
    """
    if is_postgres_url():
        # PostgreSQL tsvector + GIN index
        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'packets' AND column_name = 'search_vector'
                ) THEN
                    ALTER TABLE packets ADD COLUMN search_vector tsvector
                    GENERATED ALWAYS AS (
                        to_tsvector('english',
                            coalesce(context_json::jsonb->>'summary', '') || ' ' ||
                            coalesce(context_json, '')
                        )
                    ) STORED;
                END IF;
            END $$;
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_packets_search
            ON packets USING GIN(search_vector);
        """))
    else:
        # SQLite FTS5 virtual table
        await conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS packet_fts USING fts5(
                packet_id UNINDEXED,
                summary,
                tenant_id UNINDEXED,
                tokenize='porter unicode61'
            );
        """))
        # Triggers to keep FTS table in sync
        await conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS packet_fts_ai AFTER INSERT ON packets BEGIN
                INSERT INTO packet_fts(packet_id, summary, tenant_id)
                VALUES (
                    new.id,
                    coalesce(json_extract(new.context_json, '$.summary'), ''),
                    new.tenant_id
                );
            END;
        """))
        await conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS packet_fts_ad AFTER DELETE ON packets BEGIN
                DELETE FROM packet_fts WHERE packet_id = old.id;
            END;
        """))
        await conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS packet_fts_au AFTER UPDATE ON packets BEGIN
                DELETE FROM packet_fts WHERE packet_id = old.id;
                INSERT INTO packet_fts(packet_id, summary, tenant_id)
                VALUES (
                    new.id,
                    coalesce(json_extract(new.context_json, '$.summary'), ''),
                    new.tenant_id
                );
            END;
        """))


async def _seed_default_tenant(conn: AsyncConnection) -> None:
    """Seed the default tenant for dev mode if it doesn't exist.

    This is only used when tables are created from scratch (SQLite dev mode).
    In production, the Alembic migration handles this.
    """
    # Check if the tenants table exists and has data
    try:
        result = await conn.execute(text("SELECT 1 FROM tenants WHERE id = 'default'"))
        if result.scalar_one_or_none() is not None:
            return  # Already seeded
    except Exception:
        return  # Table might not exist yet

    # Insert default tenant
    await conn.execute(
        text(
            "INSERT OR IGNORE INTO tenants (id, name, tier, handoffs_per_day, max_api_keys, created_at, updated_at) "
            "VALUES ('default', 'Default Tenant', 'free', 10000, 25, datetime('now'), datetime('now'))"
        )
    )


async def check_db_connection() -> bool:
    """Check if the database connection is working.

    Returns:
        True if the connection is healthy, False otherwise.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            return True
    except Exception:
        return False
