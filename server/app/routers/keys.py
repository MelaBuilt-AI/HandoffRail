"""HandoffRail API Server — API key management endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import generate_api_key, get_api_key_from_request
from app.models.db import ApiKey
from app.models.packet import ApiKeyCreate, ApiKeyResponse
from app.routers.metrics import record_api_key_operation

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/keys", tags=["keys"])


@router.post(
    "",
    response_model=ApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    payload: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    _current_key: ApiKey = Depends(get_api_key_from_request),
) -> ApiKeyResponse:
    """Create a new API key. Requires an existing valid API key."""
    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]  # e.g., "hr_abcdEF"

    db_key = ApiKey(
        id=str(uuid4()),
        name=payload.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        tenant_id=payload.tenant_id or _current_key.tenant_id,
    )

    db.add(db_key)
    await db.commit()
    await db.refresh(db_key)

    logger.info(
        "api_key_created",
        key_id=db_key.id,
        name=payload.name,
        tenant_id=db_key.tenant_id,
    )

    record_api_key_operation("created")

    return ApiKeyResponse(
        id=db_key.id,
        name=db_key.name,
        key_prefix=db_key.key_prefix,
        tenant_id=db_key.tenant_id,
        revoked=db_key.revoked,
        created_at=db_key.created_at,
        key=plain_key,  # Only shown on creation
    )


@router.get(
    "",
    response_model=list[ApiKeyResponse],
)
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    _current_key: ApiKey = Depends(get_api_key_from_request),
) -> list[ApiKeyResponse]:
    """List all API keys for the current tenant. The actual key values are not shown."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.tenant_id == _current_key.tenant_id)
    )
    keys = result.scalars().all()

    return [
        ApiKeyResponse(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            tenant_id=k.tenant_id,
            revoked=k.revoked,
            created_at=k.created_at,
            key=None,  # Never show key on list
        )
        for k in keys
    ]


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    _current_key: ApiKey = Depends(get_api_key_from_request),
) -> None:
    """Revoke (soft-delete) an API key. The key is marked as revoked, not removed."""
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    db_key = result.scalar_one_or_none()

    if db_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {key_id} not found",
        )

    if db_key.revoked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"API key {key_id} is already revoked",
        )

    db_key.revoked = True
    db_key.revoked_at = datetime.now(UTC)

    await db.commit()

    logger.info("api_key_revoked", key_id=key_id, revoked_by=_current_key.id)

    record_api_key_operation("revoked")


@router.post(
    "/{key_id}/rotate",
    response_model=ApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    _current_key: ApiKey = Depends(get_api_key_from_request),
) -> ApiKeyResponse:
    """Rotate an API key — creates a new key and revokes the old one.

    The new key inherits the same name (with ' (rotated)' suffix), tenant_id,
    and tier as the original. The old key is immediately revoked.

    Returns the new key with the plain key value (shown only once).
    """
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    old_key = result.scalar_one_or_none()

    if old_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {key_id} not found",
        )

    if old_key.revoked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"API key {key_id} is already revoked — cannot rotate",
        )

    # Generate new key
    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]

    new_key = ApiKey(
        id=str(uuid4()),
        name=f"{old_key.name} (rotated)",
        key_hash=key_hash,
        key_prefix=key_prefix,
        tenant_id=old_key.tenant_id,
        tier=old_key.tier,
        rotated_from=old_key.id,
    )

    # Revoke old key
    old_key.revoked = True
    old_key.revoked_at = datetime.now(UTC)

    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)

    logger.info(
        "api_key_rotated",
        old_key_id=old_key.id,
        new_key_id=new_key.id,
        rotated_by=_current_key.id,
    )

    record_api_key_operation("rotated")

    return ApiKeyResponse(
        id=new_key.id,
        name=new_key.name,
        key_prefix=new_key.key_prefix,
        tenant_id=new_key.tenant_id,
        revoked=new_key.revoked,
        created_at=new_key.created_at,
        key=plain_key,  # Only shown on creation
    )
