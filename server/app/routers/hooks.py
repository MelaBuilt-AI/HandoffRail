"""HandoffRail API Server — Webhook CRUD endpoints.

POST /hooks   — Register a new webhook
GET  /hooks   — List webhooks for the authenticated tenant
DELETE /hooks/{id} — Deactivate a webhook
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_api_key_from_request
from app.models.db import ApiKey, Webhook
from app.models.packet import WebhookCreate, WebhookResponse

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
        created_at=datetime.now(timezone.utc),
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
