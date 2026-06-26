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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
