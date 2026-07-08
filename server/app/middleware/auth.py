"""HandoffRail API Server — Auth middleware module."""

from __future__ import annotations

import hashlib
import secrets

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db import ApiKey

# Prefix for API keys
KEY_PREFIX = "hr_"


def hash_key(key: str) -> str:
    """Hash an API key using SHA-256."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key and its hash.

    Returns:
        Tuple of (plain_key, hashed_key). Store the hash, show the plain key once.
    """
    raw = secrets.token_urlsafe(32)
    plain_key = f"{KEY_PREFIX}{raw}"
    hashed = hash_key(plain_key)
    return plain_key, hashed


async def get_api_key_from_request(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """Extract and validate the API key from the X-API-Key header.

    This is a FastAPI dependency — inject into route handlers to enforce auth.

    Raises:
        HTTPException 401: If the key is missing or invalid.
        HTTPException 403: If the key is revoked.
    """
    api_key = request.headers.get("X-API-Key")

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    key_hash = hash_key(api_key)
    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    db_key = result.scalar_one_or_none()

    if db_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    if db_key.revoked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key has been revoked",
        )

    return db_key


async def require_admin(
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> ApiKey:
    """Dependency that requires the authenticated API key to have admin role.

    Raises:
        HTTPException 403: If the key does not have an admin role.
    """
    if api_key.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return api_key


async def get_tenant_id(
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> str:
    """Dependency that extracts the tenant_id from the authenticated API key.

    This is a convenience dependency for endpoints that need the tenant_id
    without needing the full ApiKey object.
    """
    return api_key.tenant_id


async def require_role(min_role: str = "reader"):
    """Factory that returns a dependency requiring a minimum role level.

    Usage:
        @router.get("/some-endpoint")
        async def handler(api_key: ApiKey = Depends(require_role("writer"))):
            ...

    Raises:
        HTTPException 403: If the key's role is insufficient.
    """
    from app.middleware.rbac import get_role_level

    async def _dependency(
        api_key: ApiKey = Depends(get_api_key_from_request),
    ) -> ApiKey:
        if get_role_level(api_key.role) < get_role_level(min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {min_role}, current role: {api_key.role}",
            )
        return api_key

    return _dependency
