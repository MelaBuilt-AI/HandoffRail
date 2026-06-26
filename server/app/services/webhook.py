"""HandoffRail API Server — Webhook dispatch service.

Delivers POST notifications to registered webhook URLs when packet
status changes occur. Includes HMAC-SHA256 signing and retry logic
with exponential backoff (3 retries).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import uuid4

import structlog
from sqlalchemy import select

from app.database import async_session
from app.models.db import Packet, Webhook

logger = structlog.get_logger()

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0
BACKOFF_MULTIPLIER = 2.0

# Valid webhook event types mapped to status transitions
STATUS_TO_EVENTS: dict[str, str] = {
    "created": "packet.created",
    "claimed": "packet.claimed",
    "in_progress": "packet.in_progress",
    "awaiting_human": "packet.awaiting_human",
    "completed": "packet.completed",
    "failed": "packet.failed",
    "expired": "packet.expired",
}

# HITL response event
HITL_EVENT = "hitl.response_ready"


def sign_payload(payload: str, secret: str) -> str:
    """Sign a payload with HMAC-SHA256 using the webhook secret.

    Args:
        payload: JSON string of the webhook payload.
        secret: The webhook's signing secret.

    Returns:
        Hex digest of the HMAC-SHA256 signature.
    """
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_webhook_payload(
    event_type: str,
    packet: Packet,
    extra_details: dict | None = None,
) -> dict:
    """Build the webhook payload for a packet event.

    Args:
        event_type: The event type (e.g. 'packet.claimed').
        packet: The ORM Packet object.
        extra_details: Optional additional details to include.

    Returns:
        Dict payload suitable for JSON serialization.
    """
    payload: dict = {
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "packet_id": packet.id,
        "status": packet.status,
        "metadata": packet.get_metadata(),
    }
    if extra_details:
        payload["details"] = extra_details
    return payload


async def get_active_webhooks(tenant_id: str, event_type: str) -> list[Webhook]:
    """Fetch all active webhooks for a tenant that subscribe to a given event type.

    Args:
        tenant_id: The tenant to fetch webhooks for.
        event_type: The event type to filter by.

    Returns:
        List of matching Webhook ORM objects.
    """
    async with async_session() as session:
        result = await session.execute(
            select(Webhook).where(
                Webhook.tenant_id == tenant_id,
                Webhook.active.is_(True),
            )
        )
        all_hooks = result.scalars().all()

        # Filter by event type (stored as JSON array)
        matching = []
        for hook in all_hooks:
            events = hook.get_events()
            if event_type in events:
                matching.append(hook)

        return matching


async def deliver_webhook(
    webhook: Webhook,
    payload: dict,
) -> bool:
    """Deliver a webhook payload to the registered URL with HMAC signing.

    Uses httpx for async HTTP delivery. Retries up to MAX_RETRIES times
    with exponential backoff on failure.

    Args:
        webhook: The Webhook ORM object.
        payload: The payload dict to send.

    Returns:
        True if delivery succeeded (2xx status), False otherwise.
    """
    import httpx

    payload_json = json.dumps(payload, default=str)
    signature = sign_payload(payload_json, webhook.secret)

    headers = {
        "Content-Type": "application/json",
        "X-HR-Signature": signature,
        "X-HR-Event": payload.get("event", "unknown"),
        "X-HR-Delivery-ID": str(uuid4()),
    }

    backoff = INITIAL_BACKOFF_SECONDS

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    webhook.url,
                    content=payload_json,
                    headers=headers,
                )

                if 200 <= response.status_code < 300:
                    logger.info(
                        "webhook_delivered",
                        webhook_id=webhook.id,
                        url=webhook.url,
                        status_code=response.status_code,
                        attempt=attempt,
                    )
                    return True

                logger.warning(
                    "webhook_delivery_non_2xx",
                    webhook_id=webhook.id,
                    url=webhook.url,
                    status_code=response.status_code,
                    attempt=attempt,
                )

        except Exception as exc:
            logger.warning(
                "webhook_delivery_error",
                webhook_id=webhook.id,
                url=webhook.url,
                error=str(exc),
                attempt=attempt,
            )

        if attempt < MAX_RETRIES:
            await asyncio.sleep(backoff)
            backoff *= BACKOFF_MULTIPLIER

    logger.error(
        "webhook_delivery_failed",
        webhook_id=webhook.id,
        url=webhook.url,
        max_retries=MAX_RETRIES,
    )
    return False


async def dispatch_webhooks(
    packet: Packet,
    event_type: str,
    tenant_id: str = "default",
    extra_details: dict | None = None,
) -> list[dict]:
    """Dispatch webhook notifications for a packet event.

    Finds all active webhooks for the tenant that subscribe to the
    event type and delivers the payload to each.

    Args:
        packet: The ORM Packet object.
        event_type: The event type string.
        tenant_id: The tenant ID to filter webhooks.
        extra_details: Optional extra details for the payload.

    Returns:
        List of delivery results with success/failure status.
    """
    # Map status transitions to webhook event types
    webhook_event = STATUS_TO_EVENTS.get(event_type)
    if webhook_event is None and event_type == "hitl_responded":
        webhook_event = HITL_EVENT

    if webhook_event is None:
        logger.debug("no_webhook_event_mapping", event_type=event_type)
        return []

    webhooks = await get_active_webhooks(tenant_id, webhook_event)

    if not webhooks:
        logger.debug("no_webhooks_registered", tenant_id=tenant_id, event=webhook_event)
        return []

    payload = build_webhook_payload(webhook_event, packet, extra_details)

    results = []
    for webhook in webhooks:
        success = await deliver_webhook(webhook, payload)
        results.append({
            "webhook_id": webhook.id,
            "url": webhook.url,
            "success": success,
        })

    return results
