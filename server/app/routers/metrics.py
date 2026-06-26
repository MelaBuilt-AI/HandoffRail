"""HandoffRail API Server — Prometheus metrics endpoint.

Exposes /metrics with request count, request latency, active packets,
and handoffs per tenant. Uses prometheus-client directly for custom metrics.
"""

from __future__ import annotations

import time
from typing import Any

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

# Webhook deliveries
WEBHOOK_DELIVERIES_TOTAL = Counter(
    "handoffrail_webhook_deliveries_total",
    "Total webhook delivery attempts",
    ["webhook_id", "event_type", "result"],  # result: success|failed
)

WEBHOOK_DLQ_SIZE = Gauge(
    "handoffrail_webhook_dlq_size",
    "Number of deliveries in the dead letter queue",
    ["tenant_id"],
)

# Packet status distribution
PACKET_STATUS_COUNT = Gauge(
    "handoffrail_packet_status_count",
    "Number of packets by status",
    ["status"],
)

# HITL checkpoints
HITL_CHECKPOINTS_TOTAL = Counter(
    "handoffrail_hitl_checkpoints_total",
    "Total HITL checkpoints created",
    ["tenant_id"],
)

HITL_RESPONSES_TOTAL = Counter(
    "handoffrail_hitl_responses_total",
    "Total HITL responses received",
    ["tenant_id"],
)

# API key operations
API_KEY_OPERATIONS = Counter(
    "handoffrail_api_key_operations_total",
    "API key operations",
    ["operation"],  # created|revoked|rotated
)

# Chain depth (packets with parent)
CHAIN_DEPTH = Histogram(
    "handoffrail_chain_depth",
    "Chain depth of packets (number of ancestors)",
    buckets=[0, 1, 2, 5, 10, 20, 50],
)

# ── Middleware for automatic request tracking ──────────────────────────────────


class PrometheusMiddleware:
    """ASGI middleware that tracks request count and latency.

    Not using BaseHTTPMiddleware to avoid the overhead of creating a Response
    object — we track at the ASGI level instead.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
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

        async def send_with_status(message: dict[str, Any]) -> None:
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


def record_webhook_delivery(webhook_id: str, event_type: str, success: bool) -> None:
    """Record a webhook delivery attempt."""
    WEBHOOK_DELIVERIES_TOTAL.labels(
        webhook_id=webhook_id,
        event_type=event_type,
        result="success" if success else "failed",
    ).inc()


def update_dlq_size(tenant_id: str, count: int) -> None:
    """Update the DLQ size gauge for a tenant."""
    WEBHOOK_DLQ_SIZE.labels(tenant_id=tenant_id).set(count)


def record_packet_status(status: str, count: int) -> None:
    """Update packet status distribution gauge."""
    PACKET_STATUS_COUNT.labels(status=status).set(count)


def record_hitl_checkpoint(tenant_id: str) -> None:
    """Record a HITL checkpoint creation."""
    HITL_CHECKPOINTS_TOTAL.labels(tenant_id=tenant_id).inc()


def record_hitl_response(tenant_id: str) -> None:
    """Record a HITL response."""
    HITL_RESPONSES_TOTAL.labels(tenant_id=tenant_id).inc()


def record_api_key_operation(operation: str) -> None:
    """Record an API key operation (created, revoked, rotated)."""
    API_KEY_OPERATIONS.labels(operation=operation).inc()
