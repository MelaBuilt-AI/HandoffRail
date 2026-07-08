"""HandoffRail API Server — Webhook CRUD endpoints.

POST /hooks   — Register a new webhook
GET  /hooks   — List webhooks for the authenticated tenant
DELETE /hooks/{id} — Deactivate a webhook
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_api_key_from_request, require_admin
from app.models.db import ApiKey, Webhook, WebhookDelivery
from app.models.packet import WebhookCreate, WebhookResponse
from app.services.webhook import get_dlq_entries, replay_dlq_entry, retry_failed_deliveries

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/hooks", tags=["hooks"])


@router.post(
    "",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    payload: WebhookCreate,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> WebhookResponse:
    """Register a new webhook URL for packet status change notifications.

    The webhook will receive POST requests with HMAC-SHA256 signed payloads
    when the subscribed events occur.
    """
    db_webhook = Webhook(
        id=str(uuid4()),
        url=payload.url,
        events=payload.model_dump()["events"],  # Already validated list
        secret=payload.secret,
        tenant_id=api_key.tenant_id,
        active=True,
        created_at=datetime.now(UTC),
    )
    # Serialize events list to JSON string
    db_webhook.set_events(payload.events)

    db.add(db_webhook)
    await db.commit()
    await db.refresh(db_webhook)

    logger.info(
        "webhook_created",
        webhook_id=db_webhook.id,
        url=payload.url,
        events=payload.events,
        tenant_id=api_key.tenant_id,
    )

    return WebhookResponse(
        id=db_webhook.id,
        url=db_webhook.url,
        events=db_webhook.get_events(),
        tenant_id=db_webhook.tenant_id,
        active=db_webhook.active,
        created_at=db_webhook.created_at,
    )


@router.get(
    "",
    response_model=list[WebhookResponse],
)
async def list_webhooks(
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> list[WebhookResponse]:
    """List all webhooks for the authenticated tenant."""
    result = await db.execute(
        select(Webhook).where(Webhook.tenant_id == api_key.tenant_id)
    )
    webhooks = result.scalars().all()

    return [
        WebhookResponse(
            id=w.id,
            url=w.url,
            events=w.get_events(),
            tenant_id=w.tenant_id,
            active=w.active,
            created_at=w.created_at,
        )
        for w in webhooks
    ]


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_webhook(
    webhook_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> None:
    """Deactivate (soft-delete) a webhook. The webhook is marked as inactive.

    Inactive webhooks will not receive notifications but are retained for
    audit purposes.
    """
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.tenant_id == api_key.tenant_id,
        )
    )
    webhook = result.scalar_one_or_none()

    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found",
        )

    if not webhook.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Webhook {webhook_id} is already inactive",
        )

    webhook.active = False
    await db.commit()

    logger.info("webhook_deactivated", webhook_id=webhook_id, tenant_id=api_key.tenant_id)


@router.get(
    "/{webhook_id}/deliveries",
    response_model=list[dict[str, Any]],
)
async def list_webhook_deliveries(
    webhook_id: str,
    status_filter: str | None = Query(None, alias="status", description="Filter by delivery status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> list[dict[str, Any]]:
    """List delivery history for one webhook in the authenticated tenant."""
    hook_result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.tenant_id == api_key.tenant_id,
        )
    )
    if hook_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found",
        )

    query = select(WebhookDelivery).where(
        WebhookDelivery.webhook_id == webhook_id,
        WebhookDelivery.tenant_id == api_key.tenant_id,
    )
    if status_filter:
        query = query.where(WebhookDelivery.status == status_filter)

    result = await db.execute(
        query.order_by(WebhookDelivery.created_at.desc()).offset(offset).limit(limit)
    )
    deliveries = result.scalars().all()

    return [
        {
            "id": d.id,
            "webhook_id": d.webhook_id,
            "packet_id": d.packet_id,
            "event_type": d.event_type,
            "status": d.status,
            "attempts": d.attempts,
            "last_error": d.last_error,
            "last_status_code": d.last_status_code,
            "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
            "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in deliveries
    ]


# ── Dead Letter Queue endpoints ────────────────────────────────────────────────


@router.get(
    "/dlq",
    response_model=list[dict[str, Any]],
)
async def list_dlq(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> list[dict[str, Any]]:
    """List dead letter queue entries for the authenticated tenant."""
    return await get_dlq_entries(tenant_id=api_key.tenant_id, limit=limit, offset=offset)


@router.post(
    "/dlq/{delivery_id}/replay",
    status_code=status.HTTP_200_OK,
)
async def replay_dlq(
    delivery_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> dict[str, Any]:
    """Replay a single dead letter delivery attempt. Scoped to the authenticated tenant."""
    success = await replay_dlq_entry(delivery_id, tenant_id=api_key.tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DLQ entry {delivery_id} not found, not in dead_letter status, or webhook inactive",
        )
    return {"delivery_id": delivery_id, "replayed": True}


@router.post(
    "/dlq/retry-all",
    status_code=status.HTTP_200_OK,
)
async def retry_all_dlq(
    db: AsyncSession = Depends(get_db),
    _admin: ApiKey = Depends(require_admin),
) -> dict[str, Any]:
    """Retry all failed deliveries that are due for retry. Requires admin API key."""
    result = await retry_failed_deliveries(max_batch=100)
    return result
