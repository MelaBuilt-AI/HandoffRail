"""HandoffRail API Server — Health and readiness endpoints.

/health — Liveness probe (always returns ok if the process is running)
/ready  — Readiness probe (checks DB connection)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import async_session

logger = structlog.get_logger()

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness probe — returns ok if the process is running."""
    return {"status": "ok", "service": "handoffrail"}


@router.get("/ready", response_model=None)
async def readiness_check() -> dict[str, str | bool] | JSONResponse:
    """Readiness probe — checks if the database connection is working."""
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.error("readiness_check_failed", error=str(exc))
        db_ok = False

    if db_ok:
        return {"status": "ready", "service": "handoffrail", "db": True}
    else:
        # Return 503 Service Unavailable
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "service": "handoffrail", "db": False},
        )
