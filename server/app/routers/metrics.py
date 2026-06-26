"""HandoffRail API Server — Prometheus metrics endpoint.

Exposes /metrics with request count, request latency, active packets,
and handoffs per tenant. Uses prometheus-client directly for custom metrics.
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.responses import Response

logger = structlog.get_logger()

# ── Metric definitions ─────────────────────────────────────────────────────────

# Request count by method, endpoint, status
REQUEST_COUNT = Counter(
    "handoffrail_requests_total",
    "Total count of requests",
    ["method", "endpoint", "status_code"],
)

# Request latency histogram
REQUEST_LATENCY = Histogram(
    "handoffrail_request_latency_seconds",
    "Request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# Active packets gauge
ACTIVE_PACKETS = Gauge(
    "handoffrail_active_packets",
    "Number of active (non-terminal) packets",
)

# Handoffs per tenant counter
HANDOFFS_PER_TENANT = Counter(
    "handoffrail_handoffs_total",
    "Total handoff packets created",
    ["tenant_id"],
)

# ── Middleware for automatic request tracking ──────────────────────────────────


class PrometheusMiddleware:
    """ASGI middleware that tracks request count and latency.

    Not using BaseHTTPMiddleware to avoid the overhead of creating a Response
    object — we track at the ASGI level instead.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")

        # Skip metrics endpoint itself to avoid self-referencing
        if path == "/metrics":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()

        # Intercept the send to capture status code
        status_code = 200

        async def send_with_status(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            latency = time.perf_counter() - start_time
            REQUEST_COUNT.labels(method=method, endpoint=path, status_code=str(status_code)).inc()
            REQUEST_LATENCY.labels(method=method, endpoint=path).observe(latency)


# ── Router for /metrics endpoint ───────────────────────────────────────────────

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics_endpoint() -> Response:
    """Expose Prometheus metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def record_handoff(tenant_id: str) -> None:
    """Record a handoff packet creation for a tenant."""
    HANDOFFS_PER_TENANT.labels(tenant_id=tenant_id).inc()


def update_active_packets(count: int) -> None:
    """Update the active packets gauge."""
    ACTIVE_PACKETS.set(count)
