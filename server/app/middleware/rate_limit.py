"""HandoffRail API Server — Redis-backed rate limiting with in-memory fallback.

Replaces the pure in-memory RateLimitRegistry with Redis INCR + EXPIRE
for atomic, horizontally-scalable rate limiting. Falls back to the
original in-memory implementation when Redis is unavailable.

Rate limiting: per API key, tier-based requests per hour.
Quota enforcement: per tenant, daily handoff counts.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.services.redis_pubsub import get_pubsub_manager

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
    """Get a specific quota value for a tier."""
    quotas = TIER_QUOTAS.get(tier, TIER_QUOTAS[DEFAULT_TIER])
    return quotas.get(quota_name, TIER_QUOTAS[DEFAULT_TIER].get(quota_name, 0))


# Paths exempt from rate limiting
EXEMPT_PATHS = {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/redoc"}


# ── In-memory fallback (used when Redis is unavailable) ─────────────────────────


class InMemoryRateLimitRegistry:
    """Thread-safe in-memory rate limit counter registry (fallback only)."""

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
        with self._lock:
            self._windows.clear()


class InMemoryDailyHandoffCounter:
    """Thread-safe in-memory daily handoff counter (fallback only)."""

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
        with self._lock:
            self._counts.clear()


# ── Redis-backed implementations ───────────────────────────────────────────────


REDIS_RATE_LIMIT_PREFIX = "hr:ratelimit"
REDIS_DAILY_HANDOFF_PREFIX = "hr:daily_handoff"


async def redis_increment_rate_limit(key_id: str, window_start: float, window_seconds: int) -> int | None:
    """Atomically increment rate limit counter in Redis.

    Uses INCR + EXPIRE for atomic fixed-window counting.
    Returns the new count, or None if Redis is unavailable.
    """
    pubsub = get_pubsub_manager()
    if not pubsub.is_connected or pubsub._redis is None:
        return None

    try:
        redis_key = f"{REDIS_RATE_LIMIT_PREFIX}:{key_id}:{int(window_start)}"
        count = await pubsub._redis.incr(redis_key)
        # Set expiry on first increment in the window
        if count == 1:
            await pubsub._redis.expire(redis_key, window_seconds + 60)  # +60s buffer
        return count
    except Exception as exc:
        logger.warning("redis_rate_limit_error", error=str(exc), key_id=key_id)
        return None


async def redis_get_rate_limit_count(key_id: str, window_start: float) -> int | None:
    """Get current rate limit count from Redis. Returns None if unavailable."""
    pubsub = get_pubsub_manager()
    if not pubsub.is_connected or pubsub._redis is None:
        return None

    try:
        redis_key = f"{REDIS_RATE_LIMIT_PREFIX}:{key_id}:{int(window_start)}"
        count = await pubsub._redis.get(redis_key)
        return int(count) if count is not None else 0
    except Exception as exc:
        logger.warning("redis_rate_limit_get_error", error=str(exc), key_id=key_id)
        return None


async def redis_increment_daily_handoff(tenant_id: str, day_key: str) -> int | None:
    """Atomically increment daily handoff counter in Redis. Returns None if unavailable."""
    pubsub = get_pubsub_manager()
    if not pubsub.is_connected or pubsub._redis is None:
        return None

    try:
        redis_key = f"{REDIS_DAILY_HANDOFF_PREFIX}:{tenant_id}:{day_key}"
        count = await pubsub._redis.incr(redis_key)
        if count == 1:
            # Expire after 2 days (86400 * 2 seconds)
            await pubsub._redis.expire(redis_key, 172800)
        return count
    except Exception as exc:
        logger.warning("redis_daily_handoff_error", error=str(exc), tenant_id=tenant_id)
        return None


async def redis_get_daily_handoff_count(tenant_id: str, day_key: str) -> int | None:
    """Get daily handoff count from Redis. Returns None if unavailable."""
    pubsub = get_pubsub_manager()
    if not pubsub.is_connected or pubsub._redis is None:
        return None

    try:
        redis_key = f"{REDIS_DAILY_HANDOFF_PREFIX}:{tenant_id}:{day_key}"
        count = await pubsub._redis.get(redis_key)
        return int(count) if count is not None else 0
    except Exception as exc:
        logger.warning("redis_daily_handoff_get_error", error=str(exc), tenant_id=tenant_id)
        return None


# ── Module-level fallback instances (shared for tests) ─────────────────────────

rate_limiter_registry = InMemoryRateLimitRegistry()
daily_handoff_counter = InMemoryDailyHandoffCounter()

# ── Backward-compatible aliases (used by tests and external code) ────────────────
# The original class names are preserved as aliases so existing imports
# (RateLimitRegistry, DailyHandoffCounter) continue to work.
RateLimitRegistry = InMemoryRateLimitRegistry
DailyHandoffCounter = InMemoryDailyHandoffCounter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-API-key, tier-based rate limiting middleware.

    Uses Redis for atomic counting when available, falls back to
    in-memory counters when Redis is unavailable.
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

        # Get API key info from request state or headers
        api_key = getattr(request.state, "api_key", None)

        if api_key is not None:
            tier = getattr(api_key, "tier", DEFAULT_TIER)
            key_id = api_key.id
        else:
            raw_key = request.headers.get("X-API-Key")
            if raw_key:
                from app.middleware.auth import hash_key

                key_hash = hash_key(raw_key)
                key_id = f"key:{key_hash[:16]}"
                tier = DEFAULT_TIER
            else:
                tier = DEFAULT_TIER
                key_id = f"ip:{request.client.host if request.client else 'unknown'}"

        limit = self.tier_limits.get(tier, self.tier_limits[DEFAULT_TIER])

        # Calculate window
        current_time = time.time()
        window_key = int(current_time // RATE_LIMIT_WINDOW_SECONDS)
        window_start = float(window_key * RATE_LIMIT_WINDOW_SECONDS)
        reset_seconds = int(window_start + RATE_LIMIT_WINDOW_SECONDS - current_time)

        # Try Redis first, fall back to in-memory
        current_count = await redis_get_rate_limit_count(key_id, window_start)

        if current_count is not None:
            # Redis is available — use atomic INCR
            new_count = await redis_increment_rate_limit(
                key_id, window_start, RATE_LIMIT_WINDOW_SECONDS
            )
            if new_count is not None:
                current_count = new_count - 1  # What it was before this request
            else:
                # Redis failed mid-operation — fall back to in-memory
                self.registry.cleanup_old(key_id, window_start, RATE_LIMIT_WINDOW_SECONDS * 2)
                current_count = self.registry.get_count(key_id, window_start)
                self.registry.increment(key_id, window_start)
        else:
            # Redis unavailable — use in-memory
            self.registry.cleanup_old(key_id, window_start, RATE_LIMIT_WINDOW_SECONDS * 2)
            current_count = self.registry.get_count(key_id, window_start)
            self.registry.increment(key_id, window_start)

        remaining = max(0, limit - current_count - 1)

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

        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_seconds)
        response.headers["X-RateLimit-Tier"] = tier

        return response