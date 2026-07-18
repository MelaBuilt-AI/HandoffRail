"""HandoffRail API Server — RBAC (Role-Based Access Control) middleware.

Enforces minimum required roles for API endpoints based on the
authenticated API key's role field.

Role hierarchy (higher = more privileged):
    4 = admin  — all operations including key management
    3 = writer — create/update/claim/complete packets
    2 = agent  — claim/complete packets only (no create)
    1 = reader — list/get/search only

The middleware extracts the API key from the X-API-Key header, looks up
its role from the database (with in-memory caching), and checks it against
the endpoint's permission rule. This is self-contained and does not depend
on the auth dependency (which runs in the route handler).
"""

from __future__ import annotations

import os
import re
import time

import structlog
from fastapi import Request, Response
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = structlog.get_logger()

# ── Role hierarchy (higher = more privileged) ──────────────────────────────────

ROLE_HIERARCHY: dict[str, int] = {
    "admin": 4,
    "writer": 3,
    "agent": 2,
    "reader": 1,
}

VALID_ROLES = set(ROLE_HIERARCHY.keys())


# ── Endpoint → required role mapping ──────────────────────────────────────────

_ROUTE_RULES: list[tuple[re.Pattern[str], str, set[str] | None]] = [
    # Admin-only: key management, tenants, system health
    (re.compile(r"^/api/v1/keys"), "admin", None),
    (re.compile(r"^/api/v1/tenants"), "admin", None),
    (re.compile(r"^/api/v1/system"), "admin", None),

    # Reader: GET on packets
    (re.compile(r"^/api/v1/packets/search"), "reader", {"GET"}),
    (re.compile(r"^/api/v1/packets/awaiting"), "reader", {"GET"}),
    (re.compile(r"^/api/v1/packets/[^/]+/history"), "reader", {"GET"}),
    (re.compile(r"^/api/v1/packets/[^/]+$"), "reader", {"GET"}),
    (re.compile(r"^/api/v1/packets$"), "reader", {"GET"}),

    # Agent: claim, respond, status updates
    (re.compile(r"^/api/v1/packets/[^/]+/claim"), "agent", {"POST"}),
    (re.compile(r"^/api/v1/packets/[^/]+/respond"), "agent", {"POST"}),
    (re.compile(r"^/api/v1/packets/[^/]+$"), "agent", {"PATCH"}),

    # Writer: all other packet operations
    (re.compile(r"^/api/v1/packets"), "writer", None),

    # Schemas, webhooks, audit
    (re.compile(r"^/api/v1/schemas"), "writer", None),
    (re.compile(r"^/api/v1/hooks"), "writer", None),
    (re.compile(r"^/api/v1/audit"), "reader", {"GET"}),
    (re.compile(r"^/api/v1/audit"), "writer", None),

    # Dashboard — accessible to readers+
    (re.compile(r"^/api/v1/dashboard"), "reader", None),
]

# Paths exempt from RBAC
EXEMPT_PATHS = {"/health", "/ready", "/metrics", "/docs", "/openapi.json", "/redoc", "/api/v1/health"}


# ── In-memory role cache (key_hash → role, 5 min TTL) ─────────────────────────

_ROLE_CACHE_TTL = 300
_role_cache: dict[str, tuple[str, float]] = {}  # key_hash -> (role, expiry_ts)


async def _cached_role_lookup(key_hash: str) -> str | None:
    """Look up role for a hashed API key.

    Uses a 5-minute in-memory TTL cache to avoid DB lookups.
    Returns the role string or None if the key is not found or revoked.
    """
    now = time.time()
    cached = _role_cache.get(key_hash)
    if cached and cached[1] > now:
        return cached[0]

    from app.database import async_session
    from app.models.db import ApiKey

    async with async_session() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        db_key = result.scalar_one_or_none()

    if db_key is None or db_key.revoked:
        _role_cache.pop(key_hash, None)
        return None

    role = db_key.role
    _role_cache[key_hash] = (role, now + _ROLE_CACHE_TTL)
    return role


def reset_role_cache() -> None:
    """Clear the in-memory role cache (used in tests)."""
    _role_cache.clear()


# ── Role checking helpers ──────────────────────────────────────────────────────


def get_required_role(path: str, method: str) -> str | None:
    """Determine the minimum required role for a path + method combination.

    Returns the role name (e.g. "admin", "writer") or None if the path
    is not matched by any rule.
    """
    for pattern, required_role, methods in _ROUTE_RULES:
        if pattern.search(path):
            if methods is None or method.upper() in methods:
                return required_role
    return None


def get_role_level(role: str) -> int:
    """Get the numeric level for a role name. Returns 0 for unknown roles."""
    return ROLE_HIERARCHY.get(role, 0)


def is_role_sufficient(role: str, required_role: str) -> bool:
    """Check if ``role`` meets or exceeds ``required_role``."""
    return get_role_level(role) >= get_role_level(required_role)


class RBACMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces role-based access control.

    Self-contained: extracts the API key from the X-API-Key header,
    looks up its role (with caching), and checks against endpoint
    permission rules. Returns 403 Forbidden when role is insufficient.
    Health/metrics paths are exempt.

    Also sets ``request.state.api_key_role`` for use by downstream handlers.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip RBAC if explicitly disabled (e.g. in tests)
        if os.environ.get("HR_DISABLE_RBAC"):
            return await call_next(request)

        path = request.url.path

        # Skip exempt paths
        if path in EXEMPT_PATHS:
            return await call_next(request)

        # Determine required role
        required_role = get_required_role(path, request.method)

        if required_role is None:
            # Path not matched by any rule — default to admin for safety
            required_role = "admin"

        # Try to get role from request.state first (set by an upstream auth middleware)
        api_key = getattr(request.state, "api_key", None)
        if api_key is not None:
            api_key_role = getattr(api_key, "role", "admin")
        else:
            # Extract API key from header and look up role
            raw_key = request.headers.get("X-API-Key")
            if raw_key:
                from app.middleware.auth import hash_key

                key_hash = hash_key(raw_key)
                api_key_role = await _cached_role_lookup(key_hash)
                if api_key_role is None:
                    # Key not found or revoked — let the auth dependency handle 401
                    return await call_next(request)
                # Cache the role on request.state for later use
                request.state.api_key_role = api_key_role
            else:
                # No API key — let auth dependency handle 401
                return await call_next(request)

        if not is_role_sufficient(api_key_role, required_role):
            logger.warning(
                "rbac_access_denied",
                path=path,
                method=request.method,
                required_role=required_role,
                user_role=api_key_role,
            )
            return Response(
                content=(
                    '{'
                    '"detail":"Insufficient permissions. '
                    f'Required role: {required_role}, current role: {api_key_role}"'
                    '}'
                ),
                status_code=403,
                media_type="application/json",
            )

        return await call_next(request)
