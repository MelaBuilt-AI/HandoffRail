"""HandoffRail API Server — OpenTelemetry tracing integration.

Provides distributed tracing spans for packet lifecycle operations,
enabling observability across multi-agent handoff chains.

Usage:
    from app.services.tracing import trace_packet_operation

    with trace_packet_operation("create_packet", packet_id=new_id) as span:
        span.set_attribute("packet.status", initial_status)
        ...

When OpenTelemetry is installed and configured, spans are exported to
the configured OTel collector. When not installed, operations are
no-ops (zero overhead).

Configuration:
    HR_OTEL_ENABLED=true          — Enable OTel export
    HR_OTEL_SERVICE_NAME=handoffrail — Service name in traces
    HR_OTEL_ENDPOINT=http://localhost:4317 — OTLP gRPC endpoint
    HR_OTEL_RESOURCE_ATTRIBUTES=deployment.environment=prod — Extra attributes
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import structlog

logger = structlog.get_logger()

# Check if OTel is enabled
_OTEL_ENABLED = os.environ.get("HR_OTEL_ENABLED", "false").lower() == "true"
_OTEL_SERVICE_NAME = os.environ.get("HR_OTEL_SERVICE_NAME", "handoffrail")
_OTEL_ENDPOINT = os.environ.get("HR_OTEL_ENDPOINT", "http://localhost:4317")

# Lazily imported OTel modules
_tracer: Any = None
_tracer_provider: Any = None


def _init_otel() -> None:
    """Initialize OpenTelemetry tracer if enabled and available."""
    global _tracer, _tracer_provider, _OTEL_ENABLED

    if not _OTEL_ENABLED:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        # Build resource attributes
        resource_attrs = {
            "service.name": _OTEL_SERVICE_NAME,
        }

        # Parse extra resource attributes from env
        extra_attrs = os.environ.get("HR_OTEL_RESOURCE_ATTRIBUTES", "")
        for pair in extra_attrs.split(","):
            if "=" in pair:
                key, value = pair.split("=", 1)
                resource_attrs[key.strip()] = value.strip()

        resource = Resource.create(resource_attrs)

        _tracer_provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=_OTEL_ENDPOINT, insecure=True)
        _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(_tracer_provider)
        _tracer = trace.get_tracer("handoffrail")

        logger.info(
            "otel_initialized",
            endpoint=_OTEL_ENDPOINT,
            service_name=_OTEL_SERVICE_NAME,
        )
    except ImportError:
        logger.info("otel_not_installed", message="OpenTelemetry package not found — tracing is no-op")
        _OTEL_ENABLED = False
    except Exception as exc:
        logger.warning("otel_init_failed", error=str(exc))
        _OTEL_ENABLED = False


def is_tracing_enabled() -> bool:
    """Check if OpenTelemetry tracing is active."""
    return _tracer is not None


@contextmanager
def trace_packet_operation(
    operation_name: str,
    packet_id: str | None = None,
    tenant_id: str | None = None,
) -> Generator[Any, None, None]:
    """Create a tracing span for a packet operation.

    Args:
        operation_name: Name of the operation (e.g. "create_packet", "claim_packet").
        packet_id: Optional packet ID to attach as span attribute.
        tenant_id: Optional tenant ID for multi-tenant tracing.

    Yields:
        A span object (or a no-op span if OTel is not enabled).
    """
    if _tracer is None:
        # No-op span when OTel is not enabled
        class NoOpSpan:
            def set_attribute(self, key: str, value: Any) -> None:
                pass

            def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
                pass

            def record_exception(self, exc: Exception) -> None:
                pass

            def set_status(self, status: Any) -> None:
                pass

            def is_recording(self) -> bool:
                return False

        yield NoOpSpan()
        return

    span_name = f"handoffrail.{operation_name}"
    with _tracer.start_as_current_span(span_name) as span:
        if packet_id:
            span.set_attribute("packet.id", packet_id)
        if tenant_id:
            span.set_attribute("tenant.id", tenant_id)
        span.set_attribute("operation", operation_name)
        yield span


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """Create a generic tracing span with optional attributes.

    Args:
        name: Span name.
        attributes: Optional dict of initial span attributes.

    Yields:
        A span object (or no-op if OTel is not enabled).
    """
    if _tracer is None:
        class NoOpSpan:
            def set_attribute(self, key: str, value: Any) -> None:
                pass

            def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
                pass

            def record_exception(self, exc: Exception) -> None:
                pass

            def set_status(self, status: Any) -> None:
                pass

            def is_recording(self) -> bool:
                return False

        yield NoOpSpan()
        return

    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span


def shutdown_otel() -> None:
    """Shut down the OTel tracer provider. Call on application shutdown."""
    global _tracer_provider
    if _tracer_provider is not None:
        try:
            _tracer_provider.shutdown()
        except Exception:
            pass


# Initialize on module import
_init_otel()
