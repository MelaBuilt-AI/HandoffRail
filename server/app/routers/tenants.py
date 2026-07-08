"""HandoffRail API Server — Tenant management endpoints.

POST   /tenants          — Create a new tenant (admin only)
GET    /tenants          — List all tenants (admin only)
GET    /tenants/{id}     — Get tenant details (admin only)
PATCH  /tenants/{id}     — Update tenant (admin only)
DELETE /tenants/{id}     — Soft-delete tenant (admin only)
GET    /tenants/{id}/keys — List API keys for a tenant (admin only)
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import require_admin
from app.models.db import ApiKey, Tenant
from app.models.packet import (
    ApiKeyResponse,
    TenantCreate,
    TenantResponse,
    TenantUpdate,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.post(
    "",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant(
    payload: TenantCreate,
    db: AsyncSession = Depends(get_db),
    _admin: ApiKey = Depends(require_admin),
) -> TenantResponse:
    """Create a new tenant. Requires admin API key."""
    # Check for duplicate name
    result = await db.execute(
        select(Tenant).where(Tenant.name == payload.name, Tenant.deleted_at.is_(None))
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant '{payload.name}' already exists",
        )

    tenant = Tenant(
        id=str(uuid4()),
        name=payload.name,
        tier=payload.tier,
        handoffs_per_day=payload.handoffs_per_day,
        max_api_keys=payload.max_api_keys,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    logger.info("tenant_created", tenant_id=tenant.id, name=tenant.name)

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        tier=tenant.tier,
        handoffs_per_day=tenant.handoffs_per_day,
        max_api_keys=tenant.max_api_keys,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )


@router.get(
    "",
    response_model=list[TenantResponse],
)
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    _admin: ApiKey = Depends(require_admin),
) -> list[TenantResponse]:
    """List all tenants (excluding soft-deleted). Requires admin API key."""
    result = await db.execute(
        select(Tenant).where(Tenant.deleted_at.is_(None)).order_by(Tenant.created_at.desc())
    )
    tenants = result.scalars().all()

    return [
        TenantResponse(
            id=t.id,
            name=t.name,
            tier=t.tier,
            handoffs_per_day=t.handoffs_per_day,
            max_api_keys=t.max_api_keys,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in tenants
    ]


@router.get(
    "/{tenant_id}",
    response_model=TenantResponse,
)
async def get_tenant(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: ApiKey = Depends(require_admin),
) -> TenantResponse:
    """Get tenant details by ID. Requires admin API key."""
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
    )
    tenant = result.scalar_one_or_none()

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        tier=tenant.tier,
        handoffs_per_day=tenant.handoffs_per_day,
        max_api_keys=tenant.max_api_keys,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )


@router.patch(
    "/{tenant_id}",
    response_model=TenantResponse,
)
async def update_tenant(
    tenant_id: str,
    payload: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: ApiKey = Depends(require_admin),
) -> TenantResponse:
    """Update a tenant's configuration. Requires admin API key."""
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
    )
    tenant = result.scalar_one_or_none()

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    if payload.name is not None:
        # Check for duplicate name
        dup = await db.execute(
            select(Tenant).where(Tenant.name == payload.name, Tenant.id != tenant_id, Tenant.deleted_at.is_(None))
        )
        if dup.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tenant '{payload.name}' already exists",
            )
        tenant.name = payload.name
    if payload.tier is not None:
        tenant.tier = payload.tier
    if payload.handoffs_per_day is not None:
        tenant.handoffs_per_day = payload.handoffs_per_day
    if payload.max_api_keys is not None:
        tenant.max_api_keys = payload.max_api_keys

    tenant.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(tenant)

    logger.info("tenant_updated", tenant_id=tenant.id)

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        tier=tenant.tier,
        handoffs_per_day=tenant.handoffs_per_day,
        max_api_keys=tenant.max_api_keys,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )


@router.delete(
    "/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_tenant(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: ApiKey = Depends(require_admin),
) -> None:
    """Soft-delete a tenant. Requires admin API key."""
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
    )
    tenant = result.scalar_one_or_none()

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    if tenant.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant {tenant_id} is already deleted",
        )

    tenant.deleted_at = datetime.now(UTC)
    tenant.updated_at = datetime.now(UTC)
    await db.commit()

    logger.info("tenant_deleted", tenant_id=tenant_id)


@router.get(
    "/{tenant_id}/keys",
    response_model=list[ApiKeyResponse],
)
async def list_tenant_keys(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: ApiKey = Depends(require_admin),
) -> list[ApiKeyResponse]:
    """List all API keys for a specific tenant. Requires admin API key."""
    # Verify tenant exists
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
    )
    if tenant_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    result = await db.execute(
        select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()

    return [
        ApiKeyResponse(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            tenant_id=k.tenant_id,
            admin=k.admin,
            revoked=k.revoked,
            created_at=k.created_at,
            key=None,
        )
        for k in keys
    ]
