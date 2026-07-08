"""HandoffRail API Server — Application factory and lifespan."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.size_limit import RequestSizeLimitMiddleware
from app.routers import (
    audit_router,
    dashboard_router,
    health_router,
    hooks_router,
    keys_router,
    metrics_router,
    packets_router,
    schemas_router,
    tenants_router,
    websocket_router,
)
from app.routers.metrics import PrometheusMiddleware
from app.services.expiry import start_expiry_task
from app.services.redis_pubsub import get_pubsub_manager
from app.services.websocket import get_connection_manager, get_sse_manager, reset_connection_manager

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown events."""
    settings = get_settings()
    logger.info("handoffrail_starting", message="Initializing database", env=settings.environment)
    await init_db()
    logger.info("handoffrail_ready", message="Starting expiry background task")
    await start_expiry_task()

    # Initialize Redis pub/sub (graceful fallback if Redis unavailable)
    pubsub = get_pubsub_manager(settings.redis_url)
    connected = await pubsub.connect()
    if connected:
        # Wire Redis events to both WebSocket and SSE connection managers
        manager = get_connection_manager()
        sse_manager = get_sse_manager()

        async def on_redis_event(event: dict[str, Any]) -> None:
            """Relay events from Redis to local WebSocket and SSE connections."""
            # Events from the general "all" channel don't carry tenant_id
            # Tenant filtering is applied at the broadcast step
            await manager.broadcast(event)
            await sse_manager.broadcast(event)

        pubsub.set_event_callback(on_redis_event)
        await pubsub.subscribe(["all"])

    logger.info(
        "handoffrail_ready",
        message="HandoffRail API ready",
        env=settings.environment,
        port=settings.port,
        redis_connected=connected,
    )
    yield

    # Shutdown — disconnect Redis
    await pubsub.disconnect()
    reset_connection_manager()

    # Shutdown OpenTelemetry
    from app.services.tracing import shutdown_otel
    shutdown_otel()

    logger.info("handoffrail_stopping", message="Shutting down")


def create_app(
    tier_limits: dict[str, int] | None = None,
    rate_limit_per_minute: int | None = None,
) -> FastAPI:
    """Application factory — creates and configures the FastAPI app."""
    settings = get_settings()

    app = FastAPI(
        title="HandoffRail",
        description="Session-continuity middleware for multi-agent AI workflows",
        version="0.2.0",
        lifespan=lifespan,
    )

    # CORS — open for dev, restrict in prod
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Prometheus metrics middleware (ASGI-level, before other middleware)
    app.add_middleware(PrometheusMiddleware)

    # Request size limiting — tier-aware
    app.add_middleware(RequestSizeLimitMiddleware)

    # Rate limiting — per API key, tier-based + per-minute sliding window
    app.add_middleware(
        RateLimitMiddleware,
        tier_limits=tier_limits or settings.rate_limit_tiers,
        rate_limit_per_minute=(
            rate_limit_per_minute if rate_limit_per_minute is not None else settings.rate_limit_per_minute
        ),
    )

    # Register routers
    app.include_router(audit_router)
    app.include_router(packets_router)
    app.include_router(keys_router)
    app.include_router(hooks_router)
    app.include_router(schemas_router)
    app.include_router(tenants_router)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(dashboard_router)
    app.include_router(websocket_router)

    # Mount dashboard static files (if the directory exists)
    dashboard_dir = Path(__file__).parent / "dashboard"
    if dashboard_dir.is_dir():
        app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")

    return app


app = create_app()
