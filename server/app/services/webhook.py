"""HandoffRail API Server — Webhook dispatch service.

Delivers POST notifications to registered webhook URLs when packet
status changes occur. Includes HMAC-SHA256 signing, retry logic
with exponential backoff, persistent delivery tracking, and dead letter
queue for permanently failed deliveries.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import select, update

from app.database import async_session
from app.models.db import Packet, Webhook, WebhookDelivery

logger = structlog.get_logger()

# Retry configuration
MAX_RETRIES = 6
BACKOFF_SCHEDULE_SECONDS = [1, 5, 30, 300, 3600, 21600]
DLQ_THRESHOLD = MAX_RETRIES  # After this many attempts → dead letter

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
    extra_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the webhook payload for a packet event.

    Args:
        event_type: The event type (e.g. 'packet.claimed').
        packet: The ORM Packet object.
        extra_details: Optional additional details to include.

    Returns:
        Dict payload suitable for JSON serialization.
    """
    payload: dict[str, Any] = {
        "event": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
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


async def _create_delivery_record(
    webhook_id: str,
    tenant_id: str,
    packet_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> WebhookDelivery:
    """Create a persistent delivery tracking record."""
    delivery = WebhookDelivery(
        id=str(uuid4()),
        webhook_id=webhook_id,
        tenant_id=tenant_id,
        packet_id=packet_id,
        event_type=event_type,
        payload_json=json.dumps(payload, default=str),
        status="pending",
        attempts=0,
    )
    async with async_session() as session:
        session.add(delivery)
        await session.commit()
        await session.refresh(delivery)
    return delivery


async def _update_delivery_record(
    delivery_id: str,
    status: str,
    attempts: int,
    error: str | None = None,
    status_code: int | None = None,
    next_retry_at: datetime | None = None,
    delivered_at: datetime | None = None,
) -> None:
    """Update a delivery record after an attempt."""
    async with async_session() as session:
        await session.execute(
            update(WebhookDelivery)
            .where(WebhookDelivery.id == delivery_id)
            .values(
                status=status,
                attempts=attempts,
                last_error=error,
                last_status_code=status_code,
                next_retry_at=next_retry_at,
                delivered_at=delivered_at,
            )
        )
        await session.commit()


async def _get_delivery_attempts(delivery_id: str) -> int:
    """Read current attempts for a delivery record."""
    async with async_session() as session:
        result = await session.execute(
            select(WebhookDelivery.attempts).where(WebhookDelivery.id == delivery_id)
        )
        attempts = result.scalar_one_or_none()
        return attempts or 0


async def deliver_webhook(
    webhook: Webhook,
    payload: dict[str, Any],
    delivery_id: str | None = None,
) -> bool:
    """Deliver a webhook payload to the registered URL with HMAC signing.

    Uses httpx for async HTTP delivery. One attempt is made per call; failed
    deliveries are scheduled for retry with exponential backoff and moved to
    the dead letter queue after MAX_RETRIES attempts.

    Args:
        webhook: The Webhook ORM object.
        payload: The payload dict to send.
        delivery_id: Optional delivery record ID for tracking.

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
        "X-HR-Delivery-ID": delivery_id or str(uuid4()),
    }

    previous_attempts = await _get_delivery_attempts(delivery_id) if delivery_id else 0
    attempt = previous_attempts + 1
    last_error = None
    last_status_code = None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                webhook.url,
                content=payload_json,
                headers=headers,
            )

            last_status_code = response.status_code

            if 200 <= response.status_code < 300:
                logger.info(
                    "webhook_delivered",
                    webhook_id=webhook.id,
                    url=webhook.url,
                    status_code=response.status_code,
                    attempt=attempt,
                )
                if delivery_id:
                    await _update_delivery_record(
                        delivery_id,
                        status="delivered",
                        attempts=attempt,
                        status_code=response.status_code,
                        delivered_at=datetime.now(UTC),
                    )
                return True

            logger.warning(
                "webhook_delivery_non_2xx",
                webhook_id=webhook.id,
                url=webhook.url,
                status_code=response.status_code,
                attempt=attempt,
            )
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"

    except Exception as exc:
        logger.warning(
            "webhook_delivery_error",
            webhook_id=webhook.id,
            url=webhook.url,
            error=str(exc),
            attempt=attempt,
        )
        last_error = str(exc)

    exhausted = attempt >= MAX_RETRIES
    retry_delay = BACKOFF_SCHEDULE_SECONDS[min(attempt - 1, len(BACKOFF_SCHEDULE_SECONDS) - 1)]
    next_retry_at = None if exhausted else datetime.now(UTC) + timedelta(seconds=retry_delay)
    next_status = "dead_letter" if exhausted else "failed"

    if delivery_id:
        await _update_delivery_record(
            delivery_id,
            status=next_status,
            attempts=attempt,
            error=last_error,
            status_code=last_status_code,
            next_retry_at=next_retry_at,
        )

    logger.error(
        "webhook_delivery_failed",
        webhook_id=webhook.id,
        url=webhook.url,
        attempt=attempt,
        next_status=next_status,
        next_retry_at=next_retry_at.isoformat() if next_retry_at else None,
    )

    return False


async def dispatch_webhooks(
    packet: Packet,
    event_type: str,
    tenant_id: str = "default",
    extra_details: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Dispatch webhook notifications for a packet event.

    Finds all active webhooks for the tenant that subscribe to the
    event type and delivers the payload to each. Creates persistent
    delivery records for tracking and DLQ.

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
        # Create delivery record for tracking
        delivery = await _create_delivery_record(
            webhook_id=webhook.id,
            tenant_id=tenant_id,
            packet_id=packet.id,
            event_type=webhook_event,
            payload=payload,
        )

        success = await deliver_webhook(webhook, payload, delivery_id=delivery.id)
        results.append({
            "webhook_id": webhook.id,
            "delivery_id": delivery.id,
            "url": webhook.url,
            "success": success,
        })

    return results


async def retry_failed_deliveries(max_batch: int = 50) -> dict[str, Any]:
    """Retry webhook deliveries that are in 'failed' status with next_retry_at in the past.

    This is intended to be called by a background task or admin endpoint.

    Args:
        max_batch: Maximum number of deliveries to retry in one batch.

    Returns:
        Summary dict with retried, succeeded, failed counts.
    """
    now = datetime.now(UTC)
    retried = 0
    succeeded = 0
    failed = 0

    async with async_session() as session:
        result = await session.execute(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status.in_(["failed", "pending"]),
                WebhookDelivery.next_retry_at <= now,
            )
            .limit(max_batch)
        )
        deliveries = result.scalars().all()

        for delivery in deliveries:
            # Fetch the webhook
            wh_result = await session.execute(
                select(Webhook).where(Webhook.id == delivery.webhook_id)
            )
            webhook = wh_result.scalar_one_or_none()
            if webhook is None or not webhook.active:
                # Webhook gone or inactive → mark as dead letter
                delivery.status = "dead_letter"
                delivery.last_error = "Webhook no longer exists or inactive"
                continue

            retried += 1
            success = await deliver_webhook(
                webhook,
                json.loads(delivery.payload_json),
                delivery_id=delivery.id,
            )
            if success:
                succeeded += 1
            else:
                failed += 1

        await session.commit()

    logger.info(
        "dlq_retry_batch",
        retried=retried,
        succeeded=succeeded,
        failed=failed,
    )

    return {"retried": retried, "succeeded": succeeded, "failed": failed}


async def get_dlq_entries(
    tenant_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Get dead letter queue entries, optionally filtered by tenant.

    Args:
        tenant_id: Optional tenant filter.
        limit: Max results.
        offset: Pagination offset.

    Returns:
        List of DLQ entry dicts.
    """
    async with async_session() as session:
        query = select(WebhookDelivery).where(
            WebhookDelivery.status == "dead_letter"
        )
        if tenant_id:
            query = query.where(WebhookDelivery.tenant_id == tenant_id)

        query = query.order_by(WebhookDelivery.updated_at.desc()).offset(offset).limit(limit)
        result = await session.execute(query)
        deliveries = result.scalars().all()

        return [
            {
                "id": d.id,
                "webhook_id": d.webhook_id,
                "packet_id": d.packet_id,
                "event_type": d.event_type,
                "attempts": d.attempts,
                "last_error": d.last_error,
                "last_status_code": d.last_status_code,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
            for d in deliveries
        ]


async def replay_dlq_entry(delivery_id: str) -> bool:
    """Replay a single dead letter delivery.

    Resets the delivery to pending and attempts immediate delivery.

    Args:
        delivery_id: The WebhookDelivery ID to replay.

    Returns:
        True if delivery succeeded, False otherwise.
    """
    async with async_session() as session:
        result = await session.execute(
            select(WebhookDelivery).where(WebhookDelivery.id == delivery_id)
        )
        delivery = result.scalar_one_or_none()
        if delivery is None:
            return False

        if delivery.status != "dead_letter":
            return False

        # Fetch the webhook
        wh_result = await session.execute(
            select(Webhook).where(Webhook.id == delivery.webhook_id)
        )
        webhook = wh_result.scalar_one_or_none()
        if webhook is None or not webhook.active:
            return False

        # Reset and retry
        delivery.status = "pending"
        delivery.attempts = 0
        delivery.last_error = None
        await session.commit()

    return await deliver_webhook(
        webhook,
        json.loads(delivery.payload_json),
        delivery_id=delivery_id,
    )
