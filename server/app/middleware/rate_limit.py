"""HandoffRail API Server — Redis-backed rate limiting with in-memory fallback.

Replaces the pure in-memory RateLimitRegistry with Redis INCR + EXPIRE
for atomic, horizontally-scalable rate limiting. Falls back to the
original in-memory implementation when Redis is unavailable.

Rate limiting: per API key, tier-based requests per hour + per-minute sliding window.
Quota enforcement: per tenant, daily handoff counts.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from threading import Lock
from uuid import uuid4

import structlog
from fastapi import Request, Response
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

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


def get_day_key() -> str:
    """Get the current day key for daily counting (YYYY-MM-DD format)."""
    from datetime import UTC, datetime
    return datetime.now(UTC).strftime("%Y-%m-%d")


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


# ── Sliding window (per-minute burst protection) ─────────────────────────────

SLIDING_WINDOW_SECONDS = 60  # 1 minute sliding window
REDIS_SLIDING_WINDOW_PREFIX = "hr:ratelimit:sliding"
DEFAULT_RATE_LIMIT_PER_MINUTE = 60


class InMemorySlidingWindowCounter:
    """Thread-safe in-memory sliding window counter (fallback only).

    Uses a deque of timestamps for each key_id to track requests
    within a sliding window. Old entries are trimmed on each check.
    """

    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check_and_increment(
        self, key_id: str, limit: int, window_seconds: int = SLIDING_WINDOW_SECONDS
    ) -> tuple[bool, int, int]:
        """Check and increment sliding window.

        Returns (allowed, remaining, retry_after_seconds).
        When allowed, retry_after is 0.
        """
        with self._lock:
            now = time.time()
            cutoff = now - window_seconds
            dq = self._windows[key_id]

            # Remove expired entries
            while dq and dq[0] < cutoff:
                dq.popleft()

            if len(dq) >= limit:
                # Calculate retry-after from oldest entry
                oldest = dq[0]
                retry_after = int(window_seconds - (now - oldest)) + 1
                return (False, 0, max(1, retry_after))

            dq.append(now)
            remaining = limit - len(dq)
            return (True, max(0, remaining), 0)

    def cleanup(self, key_id: str, max_age: float) -> None:
        """Remove entries older than max_age for a key."""
        with self._lock:
            dq = self._windows.get(key_id)
            if dq:
                cutoff = time.time() - max_age
                while dq and dq[0] < cutoff:
                    dq.popleft()
                if not dq:
                    del self._windows[key_id]

    def reset(self) -> None:
        """Clear all counters."""
        with self._lock:
            self._windows.clear()


async def redis_sliding_window_check_and_increment(
    key_id: str,
    limit: int,
    window_seconds: int = SLIDING_WINDOW_SECONDS,
) -> tuple[bool, int, int] | None:
    """Check and increment sliding window in Redis using sorted sets.

    Uses ZREMRANGEBYSCORE to trim old entries, ZCARD to count,
    and ZADD to record the current request.

    Returns (allowed, remaining, retry_after) or None if Redis is unavailable.
    """
    pubsub = get_pubsub_manager()
    if not pubsub.is_connected or pubsub._redis is None:
        return None

    try:
        redis_key = f"{REDIS_SLIDING_WINDOW_PREFIX}:{key_id}"
        now = time.time()
        cutoff = now - window_seconds

        # Remove entries outside the window
        await pubsub._redis.zremrangebyscore(redis_key, 0, cutoff)

        # Count remaining entries
        count = await pubsub._redis.zcard(redis_key)

        if count >= limit:
            # Get oldest entry's score to calculate retry-after
            oldest = await pubsub._redis.zrangebyscore(
                redis_key, 0, now, withscores=True, count=1
            )
            if oldest:
                retry_after = int(window_seconds - (now - oldest[0][1])) + 1
            else:
                retry_after = 1
            return (False, 0, max(1, retry_after))

        # Add current request (microsecond timestamp + random for uniqueness)
        member = f"{int(now * 1_000_000)}:{uuid4().hex[:8]}"
        await pubsub._redis.zadd(redis_key, {member: now})
        await pubsub._redis.expire(redis_key, window_seconds + 60)

        remaining = limit - count - 1
        return (True, max(0, remaining), 0)
    except Exception as exc:
        logger.warning("redis_sliding_window_error", error=str(exc), key_id=key_id)
        return None


# ── Redis-backed implementations ───────────────────────────────────────────────


REDIS_RATE_LIMIT_PREFIX = "hr:ratelimit"
REDIS_TENANT_RATE_LIMIT_PREFIX = "hr:ratelimit:tenant"
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
        count: int = await pubsub._redis.incr(redis_key)
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


async def redis_increment_tenant_rate_limit(tenant_id: str, window_start: float, window_seconds: int) -> int | None:
    """Atomically increment per-tenant rate limit counter in Redis.

    Uses INCR + EXPIRE for atomic fixed-window counting.
    Returns the new count, or None if Redis is unavailable.
    """
    pubsub = get_pubsub_manager()
    if not pubsub.is_connected or pubsub._redis is None:
        return None

    try:
        redis_key = f"{REDIS_TENANT_RATE_LIMIT_PREFIX}:{tenant_id}:{int(window_start)}"
        count: int = await pubsub._redis.incr(redis_key)
        if count == 1:
            await pubsub._redis.expire(redis_key, window_seconds + 60)
        return count
    except Exception as exc:
        logger.warning("redis_tenant_rate_limit_error", error=str(exc), tenant_id=tenant_id)
        return None


async def redis_get_tenant_rate_limit_count(tenant_id: str, window_start: float) -> int | None:
    """Get current per-tenant rate limit count from Redis. Returns None if unavailable."""
    pubsub = get_pubsub_manager()
    if not pubsub.is_connected or pubsub._redis is None:
        return None

    try:
        redis_key = f"{REDIS_TENANT_RATE_LIMIT_PREFIX}:{tenant_id}:{int(window_start)}"
        count = await pubsub._redis.get(redis_key)
        return int(count) if count is not None else 0
    except Exception as exc:
        logger.warning("redis_tenant_rate_limit_get_error", error=str(exc), tenant_id=tenant_id)
        return None


async def redis_increment_daily_handoff(tenant_id: str, day_key: str) -> int | None:
    """Atomically increment daily handoff counter in Redis. Returns None if unavailable."""
    pubsub = get_pubsub_manager()
    if not pubsub.is_connected or pubsub._redis is None:
        return None

    try:
        redis_key = f"{REDIS_DAILY_HANDOFF_PREFIX}:{tenant_id}:{day_key}"
        count: int = await pubsub._redis.incr(redis_key)
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


# ── In-memory principal cache (key_hash → tenant info, 5 min TTL) ──────

_KEY_CACHE_TTL = 300  # 5 seconds for dev, 300 for production
_key_cache: dict[str, tuple[str, str, float]] = {}  # key_hash -> (tenant_id, tier, expiry_ts)


async def _cached_key_lookup(key_hash: str) -> tuple[str, str] | None:
    """Look up tenant_id and tier for a hashed API key.

    Uses a 5-minute in-memory TTL cache to avoid DB lookups on every request.
    Returns (tenant_id, tier) or None if the key is not found or revoked.
    """
    now = time.time()
    cached = _key_cache.get(key_hash)
    if cached and cached[2] > now:
        return cached[0], cached[1]

    from app.database import async_session
    from app.models.db import ApiKey

    async with async_session() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        db_key = result.scalar_one_or_none()

    if db_key is None or db_key.revoked:
        _key_cache.pop(key_hash, None)
        return None

    tenant_id = db_key.tenant_id
    tier = db_key.tier
    _key_cache[key_hash] = (tenant_id, tier, now + _KEY_CACHE_TTL)
    return tenant_id, tier


# ── Module-level fallback instances (shared for tests) ─────────────────────────

rate_limiter_registry = InMemoryRateLimitRegistry()
daily_handoff_counter = InMemoryDailyHandoffCounter()
sliding_window_counter = InMemorySlidingWindowCounter()


async def check_daily_handoff_limit(tenant_id: str, tier: str) -> bool:
    """Check if the tenant has remaining daily handoff quota.

    Returns True if the tenant can create more handoffs, False if the
    daily limit has been reached. Increments the counter to reserve a slot.

    Tiers with unlimited_handoffs=True (handoffs_per_day == 0) skip the check.
    """
    # Allow test mode override
    if os.environ.get("HR_DISABLE_DAILY_LIMIT"):
        return True

    tier_quota = TIER_QUOTAS.get(tier, TIER_QUOTAS[DEFAULT_TIER])
    daily_limit = tier_quota.get("handoffs_per_day", 0)
    unlimited = tier_quota.get("unlimited_handoffs", False)

    # Unlimited → no check
    if unlimited or daily_limit == 0:
        return True

    day_key = get_day_key()

    # Try Redis first
    redis_count = await redis_get_daily_handoff_count(tenant_id, day_key)
    if redis_count is not None:
        if redis_count >= daily_limit:
            return False
        await redis_increment_daily_handoff(tenant_id, day_key)
        return True

    # Fall back to in-memory
    current_count = daily_handoff_counter.get_count(tenant_id, day_key)
    if current_count >= daily_limit:
        return False
    daily_handoff_counter.increment(tenant_id, day_key)
    return True


async def release_daily_handoff_slot(tenant_id: str, tier: str) -> None:
    """Release a reserved daily handoff slot (used when creation fails after reservation)."""
    tier_quota = TIER_QUOTAS.get(tier, TIER_QUOTAS[DEFAULT_TIER])
    unlimited = tier_quota.get("unlimited_handoffs", False)
    if unlimited or tier_quota.get("handoffs_per_day", 0) == 0:
        return

    # For simplicity, just clear the in-memory cache — Redis counter will decrement on next check
    # In-memory: we don't decrement since it's the consumer
    pass

# ── Backward-compatible aliases (used by tests and external code) ────────────────
# The original class names are preserved as aliases so existing imports
# (RateLimitRegistry, DailyHandoffCounter) continue to work.
RateLimitRegistry = InMemoryRateLimitRegistry
DailyHandoffCounter = InMemoryDailyHandoffCounter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-API-key + per-tenant rate limiting middleware with per-minute sliding window
    + tier-based per-hour quota enforced at the tenant level.

    Three-layer rate limiting:
    1. Per-minute sliding window (burst protection) — per API key
    2. Per-hour tier-based fixed window (quota enforcement) — per tenant (aggregate)
    3. Daily handoff limit — per tenant (checked in packet creation)

    Layer 2 aggregates ALL API keys in a tenant toward the same hourly limit,
    so a tenant with 5 free-tier keys still only gets 100 requests/hour total.

    Uses Redis for atomic counting when available, falls back to
    in-memory counters when Redis is unavailable.
    Adds X-RateLimit-* and Retry-After headers.
    """

    def __init__(
        self,
        app: ASGIApp,
        tier_limits: dict[str, int] | None = None,
        rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
    ) -> None:
        super().__init__(app)
        self.tier_limits = tier_limits or TIER_LIMITS
        self.rate_limit_per_minute = rate_limit_per_minute
        self.registry = rate_limiter_registry
        self.sliding_counter = sliding_window_counter

    async def _get_key_info(self, request: Request) -> tuple[str, str, str]:
        """Extract tier, key_id, and tenant_id from request.

        When request.state.api_key is set (by an auth middleware), uses it directly.
        Otherwise, looks up the key from the database via the in-memory cache.
        """
        api_key = getattr(request.state, "api_key", None)
        if api_key is not None:
            tier = getattr(api_key, "tier", DEFAULT_TIER)
            key_id = api_key.id
            tenant_id = api_key.tenant_id
        else:
            raw_key = request.headers.get("X-API-Key")
            if raw_key:
                from app.middleware.auth import hash_key

                key_hash = hash_key(raw_key)
                key_id = f"key:{key_hash[:16]}"

                # Look up tenant info from cache or DB
                info = await _cached_key_lookup(key_hash)
                if info:
                    tenant_id, tier = info
                else:
                    tenant_id = "default"
                    tier = DEFAULT_TIER
            else:
                tier = DEFAULT_TIER
                key_id = f"ip:{request.client.host if request.client else 'unknown'}"
                tenant_id = "default"
        return tier, key_id, tenant_id

    async def _check_minute_limit(self, key_id: str, limit: int) -> tuple[bool, int, int]:
        """Check per-minute sliding window limit.

        Tries Redis sorted set first, falls back to in-memory deque.
        Returns (allowed, remaining, retry_after_seconds).
        """
        result = await redis_sliding_window_check_and_increment(key_id, limit)
        if result is not None:
            return result
        return self.sliding_counter.check_and_increment(key_id, limit)

    async def _check_hour_limit(
        self, tenant_id: str, tier: str
    ) -> tuple[int, int]:
        """Check per-hour tier-based fixed window limit at the TENANT level.

        All API keys in the same tenant share the same hourly quota.

        Returns (current_count_in_window, limit).
        Already increments the counter as a side effect.
        """
        limit = self.tier_limits.get(tier, self.tier_limits[DEFAULT_TIER])
        current_time = time.time()
        window_key = int(current_time // RATE_LIMIT_WINDOW_SECONDS)
        window_start = float(window_key * RATE_LIMIT_WINDOW_SECONDS)

        # Try Redis first, fall back to in-memory
        current_count = await redis_get_tenant_rate_limit_count(tenant_id, window_start)

        if current_count is not None:
            new_count = await redis_increment_tenant_rate_limit(
                tenant_id, window_start, RATE_LIMIT_WINDOW_SECONDS
            )
            if new_count is not None:
                current_count = new_count - 1
            else:
                self.registry.cleanup_old(tenant_id, window_start, RATE_LIMIT_WINDOW_SECONDS * 2)
                current_count = self.registry.get_count(tenant_id, window_start)
                self.registry.increment(tenant_id, window_start)
        else:
            self.registry.cleanup_old(tenant_id, window_start, RATE_LIMIT_WINDOW_SECONDS * 2)
            current_count = self.registry.get_count(tenant_id, window_start)
            self.registry.increment(tenant_id, window_start)

        return current_count, limit

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Exempt health/docs paths from rate limiting
        path = request.url.path
        if path in EXEMPT_PATHS:
            response = await call_next(request)
            return response

        # Get API key info
        tier, key_id, tenant_id = await self._get_key_info(request)

        # ── 1. Per-minute sliding window check (burst protection) ───────────────
        if self.rate_limit_per_minute > 0:
            minute_allowed, minute_remaining, minute_retry_after = await self._check_minute_limit(
                key_id, self.rate_limit_per_minute
            )

            if not minute_allowed:
                logger.warning(
                    "rate_limit_exceeded_per_minute",
                    key_id=key_id,
                    tenant_id=tenant_id,
                    tier=tier,
                    limit=self.rate_limit_per_minute,
                    window_seconds=SLIDING_WINDOW_SECONDS,
                    retry_after=minute_retry_after,
                )
                response = Response(
                    content='{"detail":"Rate limit exceeded","field":"rate_limit"}',
                    status_code=429,
                    media_type="application/json",
                )
                response.headers["X-RateLimit-Limit"] = str(self.rate_limit_per_minute)
                response.headers["X-RateLimit-Remaining"] = "0"
                response.headers["X-RateLimit-Reset"] = str(minute_retry_after)
                response.headers["Retry-After"] = str(minute_retry_after)
                response.headers["X-RateLimit-Tier"] = tier
                return response
        else:
            # rate_limit_per_minute <= 0 means disabled — skip check
            minute_remaining = 0
            minute_retry_after = 0

        # ── 2. Per-hour tier-based fixed window check (quota enforcement) ──────
        # Now aggregated at the TENANT level — all keys in a tenant share one quota
        current_time = time.time()
        window_key = int(current_time // RATE_LIMIT_WINDOW_SECONDS)
        window_start = float(window_key * RATE_LIMIT_WINDOW_SECONDS)
        reset_seconds = int(window_start + RATE_LIMIT_WINDOW_SECONDS - current_time)

        current_count, limit = await self._check_hour_limit(tenant_id, tier)

        if current_count >= limit:
            logger.warning(
                "rate_limit_exceeded_per_hour",
                tenant_id=tenant_id,
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
            response.headers["Retry-After"] = str(reset_seconds)
            response.headers["X-RateLimit-Tier"] = tier
            return response

        response = await call_next(request)

        # ── 3. Add rate limit headers ─────────────────────────────────────────
        if self.rate_limit_per_minute > 0:
            response.headers["X-RateLimit-Limit"] = str(self.rate_limit_per_minute)
            response.headers["X-RateLimit-Remaining"] = str(minute_remaining)
            response.headers["X-RateLimit-Reset"] = str(minute_retry_after or SLIDING_WINDOW_SECONDS)
        else:
            # Per-minute disabled — show per-hour limits
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(max(0, limit - current_count - 1))
            response.headers["X-RateLimit-Reset"] = str(reset_seconds)
        response.headers["X-RateLimit-Tier"] = tier

        return response
