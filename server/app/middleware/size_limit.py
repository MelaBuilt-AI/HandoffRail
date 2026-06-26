"""HandoffRail API Server — Request size validation middleware.

Rejects requests with payloads exceeding the maximum allowed size.
The limit varies by tier:
  - Free: 64KB
  - Pro: 256KB
  - Business: 1MB
Default max: 256KB for unauthenticated requests.
"""

from __future__ import annotations

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.middleware.rate_limit import DEFAULT_TIER, get_tier_quota

logger = structlog.get_logger()

# Default max for unauthenticated requests / backward compat export
MAX_BODY_SIZE = 256 * 1024
DEFAULT_MAX_BODY_SIZE = 256 * 1024


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that rejects oversized request bodies based on tier."""

    def __init__(self, app, max_body_size: int = DEFAULT_MAX_BODY_SIZE):
        super().__init__(app)
        self.max_body_size = max_body_size

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Only check requests with a body
        if request.method in ("POST", "PUT", "PATCH"):
            # Determine tier-based size limit
            api_key = getattr(request.state, "api_key", None)
            if api_key is not None:
                tier = getattr(api_key, "tier", DEFAULT_TIER)
                tier_max = get_tier_quota(tier, "max_packet_size")
            else:
                tier = DEFAULT_TIER
                tier_max = get_tier_quota(DEFAULT_TIER, "max_packet_size")

            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > tier_max:
                logger.warning(
                    "request_too_large",
                    content_length=int(content_length),
                    max_size=tier_max,
                    tier=tier,
                    path=str(request.url.path),
                )
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"Request body too large: {int(content_length):,} bytes "
                            f"(max {tier_max:,} bytes for {tier} tier)"
                        ),
                        "tier": tier,
                    },
                )

        return await call_next(request)
