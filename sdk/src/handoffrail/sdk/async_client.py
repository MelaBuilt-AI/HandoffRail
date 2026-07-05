"""HandoffRail SDK — Asynchronous HTTP client.

Usage::

    from handoffrail.sdk import AsyncHandoffRailClient

    async with AsyncHandoffRailClient(base_url="...", api_key="hr_...") as client:
        packet = await client.create_packet(...)
        claimed = await client.claim_packet(packet.id, agent_id="billing-01", agent_name="BillingBot")
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import httpx

from handoffrail.sdk.exceptions import (
    AuthenticationError,
    ConnectionError,
    HandoffRailError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from handoffrail.sdk.models import (
    BatchClaimRequest,
    BatchClaimResponse,
    BatchCompleteRequest,
    BatchCompleteResponse,
    BatchCreateResponse,
    ChainHandoffRequest,
    HitlRespondRequest,
    PacketClaim,
    PacketCreate,
    PacketHistoryResponse,
    PacketListResponse,
    PacketResponse,
    PacketUpdate,
    SearchOptions,
    WebhookCreate,
    WebhookResponse,
)


class AsyncHandoffRailClient:
    """Asynchronous HTTP client for the HandoffRail API.

    Args:
        base_url: Base URL of the HandoffRail API (e.g. ``http://localhost:8080/api/v1``).
        api_key: API key for authentication (sent as ``X-API-Key`` header).
        timeout: Request timeout in seconds (default 30).
        max_retries: Maximum number of retries on transient errors (default 3).
        retry_delay: Base delay in seconds between retries (uses exponential backoff).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key},
            timeout=self.timeout,
        )

    # ── Context manager ────────────────────────────────────────────────────

    async def __aenter__(self) -> AsyncHandoffRailClient:
        return self

    async def __aexit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any | None) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an async HTTP request with retry logic and error mapping."""
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.request(
                    method,
                    path,
                    json=json_data,
                    params=params,
                )

                if response.status_code == 401:
                    raise AuthenticationError(
                        response.json().get("detail", "Authentication failed"),
                        status_code=401,
                        response_body=response.json(),
                    )
                if response.status_code == 404:
                    raise NotFoundError(
                        response.json().get("detail", "Resource not found"),
                        status_code=404,
                        response_body=response.json(),
                    )
                if response.status_code == 410:
                    raise NotFoundError(
                        response.json().get("detail", "Resource gone"),
                        resource_id=path,
                        status_code=410,
                        response_body=response.json(),
                    )
                if response.status_code == 400:
                    body = response.json()
                    raise ValidationError(
                        body.get("detail", "Validation error"),
                        field=body.get("field"),
                        status_code=400,
                        response_body=body,
                    )
                if response.status_code == 409:
                    body = response.json()
                    detail = body.get("detail", body) if isinstance(body, dict) else str(body)
                    raise ValidationError(
                        str(detail) if not isinstance(detail, str) else detail,
                        status_code=409,
                        response_body=body,
                    )
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    raise RateLimitError(
                        "Rate limit exceeded",
                        retry_after=int(retry_after) if retry_after else None,
                        status_code=429,
                        response_body=response.json() if response.content else {},
                    )
                if response.status_code >= 500:
                    raise ServerError(
                        f"Server error: {response.status_code}",
                        status_code=response.status_code,
                        response_body=response.json() if response.content else {},
                    )
                if response.status_code == 204:
                    return {}

                response.raise_for_status()
                return response.json()

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    backoff = self.retry_delay * (2 ** attempt)
                    await asyncio.sleep(backoff)
                    continue
                raise ConnectionError(
                    f"Unable to connect to HandoffRail server after {self.max_retries + 1} attempts",
                    original_error=exc,
                ) from exc

            except (AuthenticationError, NotFoundError, ValidationError, RateLimitError, ServerError):
                raise

            except httpx.HTTPStatusError as exc:
                raise ServerError(
                    f"Unexpected HTTP error: {exc.response.status_code}",
                    status_code=exc.response.status_code,
                    response_body=exc.response.json() if exc.response.content else {},
                ) from exc

            except Exception as exc:
                if isinstance(exc, HandoffRailError):
                    raise
                last_exception = exc
                if attempt < self.max_retries:
                    backoff = self.retry_delay * (2 ** attempt)
                    await asyncio.sleep(backoff)
                    continue
                raise ConnectionError(
                    "Unexpected error communicating with HandoffRail server",
                    original_error=exc,
                ) from exc

        raise ConnectionError("Exhausted retries", original_error=last_exception)

    # ── Packet CRUD ────────────────────────────────────────────────────────

    async def create_packet(self, packet: PacketCreate) -> PacketResponse:
        """Create a new handoff packet."""
        data = await self._request("POST", "/packets", json_data=packet.to_dict())
        return PacketResponse.from_dict(data)

    async def get_packet(self, packet_id: str | UUID) -> PacketResponse:
        """Get a single packet by ID."""
        data = await self._request("GET", f"/packets/{packet_id}")
        return PacketResponse.from_dict(data)

    async def list_packets(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        target_agent: str | None = None,
        tags: str | None = None,
        priority: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PacketListResponse:
        """List packets with filtering and pagination."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if source_agent:
            params["source_agent"] = source_agent
        if target_agent:
            params["target_agent"] = target_agent
        if tags:
            params["tags"] = tags
        if priority:
            params["priority"] = priority
        if created_after:
            params["created_after"] = created_after
        if created_before:
            params["created_before"] = created_before

        data = await self._request("GET", "/packets", params=params)
        return PacketListResponse.from_dict(data)

    async def claim_packet(
        self,
        packet_id: str | UUID,
        *,
        agent_id: str,
        agent_name: str,
        framework: str | None = None,
    ) -> PacketResponse:
        """Claim a packet for processing."""
        claim = PacketClaim(agent_id=agent_id, agent_name=agent_name, framework=framework)
        data = await self._request("POST", f"/packets/{packet_id}/claim", json_data=claim.to_dict())
        return PacketResponse.from_dict(data)

    async def update_packet(self, packet_id: str | UUID, update: PacketUpdate) -> PacketResponse:
        """Partially update a packet."""
        data = await self._request("PATCH", f"/packets/{packet_id}", json_data=update.to_dict())
        return PacketResponse.from_dict(data)

    async def complete_packet(self, packet_id: str | UUID) -> PacketResponse:
        """Mark a packet as completed."""
        update = PacketUpdate(status="completed")
        return await self.update_packet(packet_id, update)

    async def delete_packet(self, packet_id: str | UUID) -> None:
        """Soft-delete a packet (marks as expired)."""
        await self._request("DELETE", f"/packets/{packet_id}")

    async def respond_to_hitl(
        self,
        packet_id: str | UUID,
        *,
        response: str,
        responded_by: str,
        notes: str | None = None,
    ) -> PacketResponse:
        """Submit a human response to a HITL checkpoint."""
        payload = HitlRespondRequest(response=response, responded_by=responded_by, notes=notes)
        data = await self._request("POST", f"/packets/{packet_id}/respond", json_data=payload.to_dict())
        return PacketResponse.from_dict(data)

    async def get_awaiting(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> PacketListResponse:
        """Get packets awaiting human review."""
        data = await self._request("GET", "/packets/awaiting", params={"limit": limit, "offset": offset})
        return PacketListResponse.from_dict(data)

    async def get_history(self, packet_id: str | UUID) -> PacketHistoryResponse:
        """Get the event history for a packet."""
        data = await self._request("GET", f"/packets/{packet_id}/history")
        return PacketHistoryResponse.from_dict(data)

    async def chain_handoff(self, parent_packet_id: str | UUID, request: ChainHandoffRequest) -> PacketResponse:
        """Create a chained follow-up packet."""
        data = await self._request("POST", f"/packets/{parent_packet_id}/chain", json_data=request.to_dict())
        return PacketResponse.from_dict(data)

    # ── Webhook CRUD ───────────────────────────────────────────────────────

    async def register_webhook(
        self,
        *,
        url: str,
        events: list[str] | None = None,
        secret: str,
    ) -> WebhookResponse:
        """Register a new webhook."""
        webhook = WebhookCreate(url=url, events=events or ["packet.created", "packet.claimed", "packet.completed", "packet.failed"], secret=secret)
        data = await self._request("POST", "/hooks", json_data=webhook.to_dict())
        return WebhookResponse.from_dict(data)

    async def list_webhooks(self) -> list[WebhookResponse]:
        """List all webhooks for the authenticated tenant."""
        data = await self._request("GET", "/hooks")
        return [WebhookResponse.from_dict(w) for w in data]

    async def delete_webhook(self, webhook_id: str) -> None:
        """Deactivate (soft-delete) a webhook."""
        await self._request("DELETE", f"/hooks/{webhook_id}")

    # ── Batch Operations ───────────────────────────────────────────────────────

    async def batch_create_packets(self, packets: list[PacketCreate]) -> BatchCreateResponse:
        """Create multiple packets in a single request.

        Args:
            packets: List of packet create payloads (max 50).

        Returns:
            Response with created packets and any errors.
        """
        payload = {"packets": [p.to_dict() for p in packets]}
        data = await self._request("POST", "/packets/batch", json_data=payload)
        return BatchCreateResponse.from_dict(data)

    async def batch_claim_packets(
        self,
        packet_ids: list[str],
        agent_id: str,
        agent_name: str,
        framework: str | None = None,
    ) -> BatchClaimResponse:
        """Claim multiple packets in a single request.

        Args:
            packet_ids: List of packet UUIDs to claim.
            agent_id: The claiming agent's ID.
            agent_name: The claiming agent's name.
            framework: Optional agent framework identifier.

        Returns:
            Response with claimed packets and any errors.
        """
        payload = BatchClaimRequest(
            packet_ids=packet_ids,
            agent_id=agent_id,
            agent_name=agent_name,
            framework=framework,
        )
        data = await self._request("POST", "/packets/batch/claim", json_data=payload.to_dict())
        return BatchClaimResponse.from_dict(data)

    async def batch_complete_packets(self, packet_ids: list[str]) -> BatchCompleteResponse:
        """Complete multiple packets in a single request.

        Args:
            packet_ids: List of packet UUIDs to complete.

        Returns:
            Response with completed packets and any errors.
        """
        payload = BatchCompleteRequest(packet_ids=packet_ids)
        data = await self._request("POST", "/packets/batch/complete", json_data=payload.to_dict())
        return BatchCompleteResponse.from_dict(data)

    # ── Search ─────────────────────────────────────────────────────────────────

    async def search_packets(self, query: str, options: SearchOptions | None = None) -> PacketListResponse:
        """Full-text search across packet summaries and context.

        Args:
            query: Search query string (min 2 characters).
            options: Optional filters (limit, offset, status, priority).

        Returns:
            List response with matching packets ranked by relevance.
        """
        params: dict[str, Any] = {"q": query}
        if options:
            params.update(options.to_params())
        data = await self._request("GET", "/packets/search", params=params)
        return PacketListResponse.from_dict(data)
