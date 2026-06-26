"""HandoffRail API Server — Tier-based rate limiting and quota enforcement middleware.

Per API key rate limiting with tier-based limits:
  - Free: 100 req/hr
  - Pro: 1000 req/hr
  - Business: 10000 req/hr

Tier quotas (enforced on resource creation):
  - Free: 5 handoffs/day, 2 agents, 1 API key, 64KB packets
  - Pro: unlimited handoffs, 10 agents, 5 API keys, 256KB packets
  - Business: unlimited handoffs, 50 agents, 25 API keys, 1MB packets

Adds X-RateLimit-* headers to all responses.
Unauthenticated requests are rate-limited at the Free tier per client IP.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = structlog.get_logger()

# ── Tier definitions: requests per hour ────────────────────────────────────────
TIER_LIMITS: dict[str, int] = {
    "free": 100,
    "pro": 1000,
    "business": 10000,
}

DEFAULT_TIER = "free"
RATE_LIMIT_WINDOW_SECONDS = 3600  # 1 hour

# ── Tier quota definitions ─────────────────────────────────────────────────────
TIER_QUOTAS: dict[str, dict[str, int | bool]] = {
    "free": {
        "handoffs_per_day": 5,
        "max_agents": 2,
        "max_api_keys": 1,
        "max_packet_size": 64 * 1024,  # 64KB
        "unlimited_handoffs": False,
    },
    "pro": {
        "handoffs_per_day": 0,  # unlimited
        "max_agents": 10,
        "max_api_keys": 5,
        "max_packet_size": 256 * 1024,  # 256KB
        "unlimited_handoffs": True,
    },
    "business": {
        "handoffs_per_day": 0,  # unlimited
        "max_agents": 50,
        "max_api_keys": 25,
        "max_packet_size": 1024 * 1024,  # 1MB
        "unlimited_handoffs": True,
    },
}


def get_tier_quota(tier: str, quota_name: str) -> int | bool:
    """Get a specific quota value for a tier.

    Args:
        tier: Tier name (free, pro, business).
        quota_name: Quota key (handoffs_per_day, max_agents, etc.).

    Returns:
        The quota value, or the free-tier default if tier is unknown.
    """
    quotas = TIER_QUOTAS.get(tier, TIER_QUOTAS[DEFAULT_TIER])
    return quotas.get(quota_name, TIER_QUOTAS[DEFAULT_TIER].get(quota_name, 0))


# Paths exempt from rate limiting
EXEMPT_PATHS = {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/redoc"}


class RateLimitRegistry:
    """Thread-safe in-memory rate limit counter registry.

    Shared between the middleware and tests to allow resetting between test runs.
    """

    def __init__(self) -> None:
        self._windows: dict[str, dict[float, int]] = defaultdict(dict)
        self._lock = Lock()

    def get_count(self, key_id: str, window_start: float) -> int:
        with self._lock:
            return self._windows.get(key_id, {}).get(window_start, 0)

    def increment(self, key_id: str, window_start: float) -> int:
        with self._lock:
            key_windows = self._windows[key_id]
            current = key_windows.get(window_start, 0)
            key_windows[window_start] = current + 1
            return current + 1

    def cleanup_old(self, key_id: str, window_start: float, max_age: float) -> None:
        with self._lock:
            key_windows = self._windows.get(key_id, {})
            old_keys = [k for k in key_windows if k < window_start - max_age]
            for k in old_keys:
                del key_windows[k]

    def reset(self) -> None:
        """Reset all counters. Used between tests."""
        with self._lock:
            self._windows.clear()


# Module-level registry — shared instance for tests to reset
rate_limiter_registry = RateLimitRegistry()


class DailyHandoffCounter:
    """Thread-safe in-memory daily handoff counter per tenant.

    Tracks handoff packet creation counts per tenant per day to enforce
    tier-based daily handoff limits.
    """

    def __init__(self) -> None:
        self._counts: dict[str, dict[str, int]] = defaultdict(dict)
        self._lock = Lock()

    def get_count(self, tenant_id: str, day_key: str) -> int:
        with self._lock:
            return self._counts.get(tenant_id, {}).get(day_key, 0)

    def increment(self, tenant_id: str, day_key: str) -> int:
        with self._lock:
            tenant_counts = self._counts[tenant_id]
            current = tenant_counts.get(day_key, 0)
            tenant_counts[day_key] = current + 1
            return current + 1

    def cleanup_old(self, tenant_id: str, current_day: str) -> None:
        with self._lock:
            tenant_counts = self._counts.get(tenant_id, {})
            old_keys = [k for k in tenant_counts if k < current_day]
            for k in old_keys:
                del tenant_counts[k]

    def reset(self) -> None:
        """Reset all counters. Used between tests."""
        with self._lock:
            self._counts.clear()


# Module-level daily counter
daily_handoff_counter = DailyHandoffCounter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-API-key, tier-based rate limiting middleware.

    Tracks request counts per API key in memory using fixed time windows.
    Adds X-RateLimit-* headers to all responses.
    """

    def __init__(self, app: object, tier_limits: dict[str, int] | None = None) -> None:
        super().__init__(app)
        self.tier_limits = tier_limits or TIER_LIMITS
        self.registry = rate_limiter_registry

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Exempt health/docs paths from rate limiting
        path = request.url.path
        if path in EXEMPT_PATHS:
            response = await call_next(request)
            return response

        # Try to get the API key info from the request state (set by auth middleware)
        # or directly from the X-API-Key header
        api_key = getattr(request.state, "api_key", None)

        if api_key is not None:
            tier = getattr(api_key, "tier", DEFAULT_TIER)
            key_id = api_key.id
        else:
            # Try to look up the API key from the header for rate limiting purposes
            # This allows rate limiting to work even on unauthenticated endpoints
            raw_key = request.headers.get("X-API-Key")
            if raw_key:
                # Hash the key and look it up in the DB would require async,
                # so we use the key hash prefix as a rate limit key
                from app.middleware.auth import hash_key

                key_hash = hash_key(raw_key)
                key_id = f"key:{key_hash[:16]}"
                # We can't know the tier without DB lookup, so default to free
                tier = DEFAULT_TIER
            else:
                # Use client IP as key for unauthenticated requests
                tier = DEFAULT_TIER
                key_id = f"ip:{request.client.host if request.client else 'unknown'}"

        limit = self.tier_limits.get(tier, self.tier_limits[DEFAULT_TIER])

        # Check rate limit
        current_time = time.time()
        window_key = int(current_time // RATE_LIMIT_WINDOW_SECONDS)
        window_start = float(window_key * RATE_LIMIT_WINDOW_SECONDS)

        # Cleanup old windows
        self.registry.cleanup_old(key_id, window_start, RATE_LIMIT_WINDOW_SECONDS * 2)

        current_count = self.registry.get_count(key_id, window_start)
        remaining = max(0, limit - current_count)
        reset_seconds = int(window_start + RATE_LIMIT_WINDOW_SECONDS - current_time)

        if current_count >= limit:
            logger.warning(
                "rate_limit_exceeded",
                key_id=key_id,
                tier=tier,
                limit=limit,
                count=current_count,
            )
            response = Response(
                content='{"detail":"Rate limit exceeded","field":"rate_limit"}',
                status_code=429,
                media_type="application/json",
            )
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = "0"
            response.headers["X-RateLimit-Reset"] = str(reset_seconds)
            response.headers["X-RateLimit-Tier"] = tier
            return response

        # Increment counter
        self.registry.increment(key_id, window_start)

        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining - 1)
        response.headers["X-RateLimit-Reset"] = str(reset_seconds)
        response.headers["X-RateLimit-Tier"] = tier

        return response
