# API Reference

Complete reference for all 19 HandoffRail API endpoints.

## Base URL

```
http://localhost:8080/api/v1
```

## Authentication

All endpoints require the `X-API-Key` header. API keys are scoped to a tenant and tier.

```http
X-API-Key: hr_your_key_here
```

Create keys via `POST /api/v1/keys`. Keys are hashed at rest — the full key is only returned once at creation.

## Rate Limiting

Rate limits are enforced per API key based on tier:

| Tier | Requests / Hour |
|------|----------------|
| Free | 100 |
| Pro | 1,000 |
| Business | 10,000 |

Rate limit info is returned in response headers:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1685491200
```

When exceeded, the API returns `429 Too Many Requests` with a `Retry-After` header.

---

## Packet Endpoints

### `POST /packets` — Create Handoff Packet

Create a new handoff packet. Validates against v1 schema.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `parent_packet_id` | UUID | No | ID of parent packet (for chain handoffs) |
| `metadata.source_agent` | object | Yes | Source agent identity (`id`, `name`, `framework`) |
| `metadata.target_agent` | object | Yes | Target agent identity (`id`, `name`, optional `framework`) |
| `metadata.priority` | string | No | `low`, `normal`, `high`, `critical` (default: `normal`) |
| `metadata.tags` | string[] | No | Freeform tags for filtering |
| `context.summary` | string | Yes | Natural-language summary of work so far |
| `context.conversation_state` | object[] | No | Conversation turns (`role`, `content`, optional `timestamp`) |
| `context.artifacts` | object[] | No | Named artifacts (`key`, `value`, optional `content_type`) |
| `context.custom` | object | No | Framework-specific or user-defined fields |
| `decisions` | object[] | No | Decisions made (`id`, `decision`, `rationale`, optional `alternatives`, `decided_by`) |
| `actions.pending` | object[] | No | Pending actions (`id`, `description`, `assignee`, optional `priority`, `depends_on`) |
| `actions.completed` | object[] | No | Completed actions (`id`, `description`, `result`) |
| `actions.failed` | object[] | No | Failed actions (`id`, `description`, `error`) |
| `dependencies` | object[] | No | External dependencies (`id`, `type`, `description`, optional `status`, `source`) |
| `hitl` | object | No | HITL checkpoint (`required`, `reason`, `question`, optional `options`, `timeout_seconds`) |

**Response `201 Created`:**

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "version": "1.0.0",
  "parent_packet_id": null,
  "metadata": { "source_agent": { "..." }, "target_agent": { "..." }, "created_at": "..." },
  "context": { "summary": "...", "conversation_state": [], "artifacts": [], "custom": {} },
  "decisions": [],
  "actions": { "pending": [], "completed": [], "failed": [] },
  "dependencies": [],
  "hitl": null,
  "status": "created",
  "created_at": "2026-05-30T19:35:00Z",
  "updated_at": "2026-05-30T19:35:00Z",
  "_links": {
    "self": "/api/v1/packets/a1b2c3d4-...",
    "claim": "/api/v1/packets/a1b2c3d4-.../claim",
    "history": "/api/v1/packets/a1b2c3d4-.../history"
  }
}
```

**Errors:**

| Status | Code | When |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | Schema validation failed (includes field-level errors) |
| 401 | `UNAUTHORIZED` | Missing or invalid API key |
| 413 | `PAYLOAD_TOO_LARGE` | Packet exceeds tier size limit |
| 429 | `RATE_LIMITED` | Rate limit exceeded |

---

### `GET /packets` — List Packets

List packets with filtering, sorting, and pagination.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | string | — | Filter by status (comma-separated for OR: `created,claimed`) |
| `source_agent` | string | — | Filter by source agent ID |
| `target_agent` | string | — | Filter by target agent ID |
| `tags` | string | — | Filter by tags (comma-separated, AND logic) |
| `priority` | string | — | Filter by priority |
| `hitl_required` | boolean | — | Only packets needing human review |
| `created_after` | datetime | — | ISO 8601 timestamp |
| `created_before` | datetime | — | ISO 8601 timestamp |
| `limit` | integer | 50 | Max results (1–200) |
| `offset` | integer | 0 | Pagination offset |
| `sort` | string | `created_at` | Sort field: `created_at`, `priority`, `status` |
| `order` | string | `desc` | Sort order: `asc` or `desc` |

**Response `200 OK`:**

```json
{
  "packets": [ "...array of packet summaries..." ],
  "total": 142,
  "limit": 50,
  "offset": 0,
  "_links": {
    "next": "/api/v1/packets?offset=50&limit=50",
    "prev": null
  }
}
```

---

### `GET /packets/{id}` — Get Single Packet

Full packet detail by ID.

**Response `200 OK`:** Complete packet object (same shape as create response).

**Errors:** `404 Not Found` if packet doesn't exist.

---

### `PATCH /packets/{id}` — Update Packet

Partial update to packet fields. Used for progressing work, adding decisions, updating actions.

**Request Body:** Any subset of packet fields:

```json
{
  "status": "in_progress",
  "decisions": [
    {"id": "d2", "decision": "Applied Business tier pricing", "rationale": "Customer confirmed", "decided_by": "billing-01"}
  ],
  "actions": {
    "completed": [
      {"id": "a1", "description": "Process upgrade", "result": "Upgraded to Business", "completed_by": "billing-01"}
    ]
  }
}
```

**Response `200 OK`:** Full updated packet.

**Errors:**

| Status | When |
|--------|------|
| 400 | Invalid status transition |
| 404 | Packet not found |

---

### `DELETE /packets/{id}` — Soft-Delete Packet

Marks packet as `expired`. Hard delete requires admin scope.

**Response `204 No Content`**

---

### `POST /packets/{id}/claim` — Claim a Packet

Agent claims an unclaimed packet, transitioning `created` → `claimed`.

**Request Body:**

```json
{
  "agent_id": "billing-01",
  "agent_name": "BillingBot",
  "framework": "crewai"
}
```

**Response `200 OK`:** Updated packet with `status: "claimed"` and `claimed_at` populated.

**Errors:**

| Status | When |
|--------|------|
| 404 | Packet not found |
| 409 | Packet already claimed (returns current claimant info) |
| 410 | Packet expired |

---

### `POST /packets/{id}/respond` — HITL Response

Submit a human response to a packet in `awaiting_human` status.

**Request Body:**

```json
{
  "response": "Approve full refund",
  "responded_by": "manager@company.com",
  "notes": "Customer is VIP"
}
```

**Response `200 OK`:** Updated packet with `hitl.response` filled and status → `claimed`.

**Errors:**

| Status | When |
|--------|------|
| 409 | Packet not in `awaiting_human` status |
| 410 | HITL timeout expired |

---

### `POST /packets/{id}/chain` — Chain Handoff

Create a new packet that continues from this one. `parent_packet_id` is auto-set.

**Request Body:** Same shape as `POST /packets` (without `parent_packet_id`).

**Response `201 Created`:** New packet with `parent_packet_id` populated.

---

### `GET /packets/awaiting` — List HITL-Pending

Convenience endpoint: all packets with `status=awaiting_human`.

**Query Parameters:** `limit`, `offset` (same as `GET /packets`).

**Response `200 OK`:** Same shape as `GET /packets`.

---

### `GET /packets/{id}/history` — Event History

Audit trail of all status transitions and modifications for a packet.

**Response `200 OK`:**

```json
{
  "packet_id": "a1b2c3d4-...",
  "events": [
    { "timestamp": "2026-05-30T19:35:00Z", "event_type": "created", "actor": "agent:sales-01", "details": {} },
    { "timestamp": "2026-05-30T19:40:00Z", "event_type": "claimed", "actor": "agent:billing-01", "details": {} },
    { "timestamp": "2026-05-30T19:50:00Z", "event_type": "completed", "actor": "agent:billing-01", "details": { "actions_completed": 1 } }
  ]
}
```

---

## Webhook Endpoints

### `POST /hooks` — Register Webhook

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | Yes | HTTPS callback URL |
| `events` | string[] | No | Event types to subscribe to (defaults to standard set) |
| `secret` | string | Yes | Secret for HMAC-SHA256 signing (min 16 chars) |

**Valid Event Types:**

`packet.created`, `packet.claimed`, `packet.in_progress`, `packet.awaiting_human`, `packet.completed`, `packet.failed`, `packet.expired`, `hitl.response_ready`

**Response `201 Created`:** Webhook object with `id`, `url`, `events`, `active`, `created_at`.

**Webhook Payload:** POST to `url` with full packet payload and `X-HR-Signature` HMAC-SHA256 header.

**Verifying Webhooks:**

```python
import hmac, hashlib

def verify_webhook(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

---

### `GET /hooks` — List Webhooks

All webhooks for the authenticated tenant.

**Response `200 OK`:** Array of webhook objects.

---

### `DELETE /hooks/{id}` — Deactivate Webhook

Soft-delete. **Response `204 No Content`**.

---

## API Key Endpoints

### `POST /keys` — Create API Key

**Request Body:**

```json
{ "name": "my-agent", "tier": "free" }
```

**Response `201 Created`:**

```json
{
  "id": "key-uuid",
  "key": "hr_full_key_returned_once",
  "name": "my-agent",
  "tier": "free",
  "created_at": "2026-05-30T19:35:00Z"
}
```

> ⚠️ The full key is only returned once. Store it securely.

---

### `GET /keys` — List API Keys

All keys for the authenticated tenant. Full keys are **not** returned.

**Response `200 OK`:** Array of key objects (without `key` field).

---

### `DELETE /keys/{id}` — Revoke API Key

Immediately invalidates the key. **Response `204 No Content`**.

---

## System Endpoints

### `GET /health` — Liveness Probe

Returns `200 OK` if the process is running. No authentication required.

### `GET /ready` — Readiness Probe

Returns `200 OK` if the database is connected, `503 Service Unavailable` if not. No authentication required.

### `GET /metrics` — Prometheus Metrics

Standard Prometheus format. No authentication required.

**Key Metrics:**

| Metric | Type | Description |
|--------|------|-------------|
| `handoffrail_requests_total` | Counter | Request count by method, endpoint, status |
| `handoffrail_request_latency_seconds` | Histogram | Request latency by method, endpoint |
| `handoffrail_active_packets` | Gauge | Non-terminal packet count |
| `handoffrail_handoffs_total` | Counter | Handoffs per tenant |

---

## Error Format

All errors follow a consistent structure:

```json
{
  "detail": "Human-readable error message",
  "code": "MACHINE_READABLE_CODE",
  "field": "field_name",
  "status_code": 400
}
```

**Common Error Codes:**

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `VALIDATION_ERROR` | 400 | Request body failed schema validation |
| `UNAUTHORIZED` | 401 | Missing or invalid API key |
| `NOT_FOUND` | 404 | Resource doesn't exist |
| `CONFLICT` | 409 | State conflict (e.g., already claimed) |
| `GONE` | 410 | Resource expired |
| `RATE_LIMITED` | 429 | Rate limit exceeded |
| `PAYLOAD_TOO_LARGE` | 413 | Packet exceeds tier size limit |
| `SERVER_ERROR` | 500 | Internal server error |