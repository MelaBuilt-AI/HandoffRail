# HandoffRail — Project Plan

> Session-continuity middleware for multi-agent AI workflows  
> Last updated: 2026-05-13

---

## 1. Product Vision & Scope

### Vision

HandoffRail is the missing connective tissue in multi-agent AI workflows. When Agent A finishes its part and hands off to Agent B (or a human), the full context — decisions made, pending actions, dependencies, conversation state — survives the transition intact. No context loss, no repetition, no dropped threads.

### Core Value Proposition

**"Pick up exactly where the last agent left off."**

- Structured handoff packets preserve everything needed to continue work
- Human-in-the-loop checkpoints ensure critical decisions get human eyes
- Framework-agnostic — works with LangChain, CrewAI, AutoGen, or raw HTTP

### MVP Scope (v0.1 — Weeks 1–8)

| In MVP | Out of MVP (v0.2+) |
|--------|---------------------|
| Handoff packet CRUD API | Real-time streaming (WebSocket/SSE) |
| Packet store with search/filter | Multi-tenant org isolation |
| Python SDK (LangChain + CrewAI adapters) | TypeScript SDK |
| Human-in-the-loop checkpoint flow | Agent orchestration engine |
| Basic auth (API keys) | SSO / OAuth2 |
| CLI for packet inspection | Web dashboard UI |
| Local / Docker deployment | Managed cloud service |
| File-based + SQLite storage tier | PostgreSQL production tier |
| Packet versioning (v1 schema) | Packet version migration |

### Future Scope (v0.2–v1.0)

- Real-time handoff streaming via WebSocket
- Web dashboard for packet visualization and human approvals
- Multi-tenant isolation with org-level access control
- SSO integration (Google, Microsoft, SAML)
- TypeScript SDK + REST client generators
- Agent orchestration engine (workflow DAGs)
- Packet schema version migration tooling
- Managed cloud deployment (handoffrail.cloud)

---

## 2. Handoff Packet Schema v1

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://handoffrail.dev/schemas/packet/v1",
  "title": "HandoffPacket",
  "type": "object",
  "required": ["id", "version", "metadata", "context", "decisions", "actions", "dependencies"],
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid",
      "description": "Unique packet identifier"
    },
    "version": {
      "type": "string",
      "const": "1.0.0",
      "description": "Schema version for forward compatibility"
    },
    "parent_packet_id": {
      "type": ["string", "null"],
      "format": "uuid",
      "description": "ID of the packet this continues from (for chain handoffs)"
    },
    "metadata": {
      "type": "object",
      "required": ["source_agent", "target_agent", "created_at", "priority"],
      "properties": {
        "source_agent": {
          "type": "object",
          "required": ["id", "name", "framework"],
          "properties": {
            "id": { "type": "string", "description": "Unique agent identifier" },
            "name": { "type": "string", "description": "Human-readable agent name" },
            "framework": { "type": "string", "description": "Agent framework (langchain, crewai, autogen, custom)" },
            "version": { "type": "string", "description": "Agent version (optional)" }
          }
        },
        "target_agent": {
          "type": "object",
          "required": ["id", "name"],
          "properties": {
            "id": { "type": "string", "description": "Target agent or 'human' for HITL" },
            "name": { "type": "string", "description": "Target name or role" },
            "framework": { "type": "string", "description": "Target framework (optional)" }
          }
        },
        "created_at": { "type": "string", "format": "date-time" },
        "claimed_at": { "type": ["string", "null"], "format": "date-time" },
        "completed_at": { "type": ["string", "null"], "format": "date-time" },
        "priority": {
          "type": "string",
          "enum": ["low", "normal", "high", "critical"],
          "default": "normal"
        },
        "tags": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Freeform tags for filtering"
        }
      }
    },
    "context": {
      "type": "object",
      "required": ["summary", "conversation_state"],
      "properties": {
        "summary": {
          "type": "string",
          "description": "Concise natural-language summary of work so far"
        },
        "conversation_state": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["role", "content"],
            "properties": {
              "role": { "type": "string", "enum": ["user", "agent", "system", "human"] },
              "content": { "type": "string" },
              "timestamp": { "type": ["string", "null"], "format": "date-time" },
              "metadata": { "type": ["object", "null"] }
            }
          },
          "description": "Key conversation turns (not necessarily full transcript)"
        },
        "artifacts": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["key", "value"],
            "properties": {
              "key": { "type": "string", "description": "Artifact name (e.g. 'draft_email')" },
              "value": { "type": ["string", "object", "array"], "description": "Artifact content" },
              "content_type": { "type": "string", "description": "MIME type hint (optional)" }
            }
          },
          "description": "Named artifacts produced during the session"
        },
        "custom": {
          "type": "object",
          "description": "Framework-specific or user-defined context fields",
          "additionalProperties": true
        }
      }
    },
    "decisions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "decision", "rationale"],
        "properties": {
          "id": { "type": "string", "description": "Decision identifier" },
          "decision": { "type": "string", "description": "What was decided" },
          "rationale": { "type": "string", "description": "Why this decision was made" },
          "alternatives": {
            "type": "array",
            "items": { "type": "string" },
            "description": "Options that were considered but not chosen"
          },
          "decided_by": { "type": "string", "description": "Agent or human who decided" },
          "timestamp": { "type": "string", "format": "date-time" }
        }
      },
      "description": "Decisions made during this session"
    },
    "actions": {
      "type": "object",
      "required": ["pending"],
      "properties": {
        "pending": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["id", "description", "assignee"],
            "properties": {
              "id": { "type": "string" },
              "description": { "type": "string", "description": "What needs to be done" },
              "assignee": { "type": "string", "description": "Agent/human ID who should handle this" },
              "priority": { "type": "string", "enum": ["low", "normal", "high", "critical"] },
              "depends_on": {
                "type": "array",
                "items": { "type": "string" },
                "description": "IDs of actions this depends on"
              },
              "deadline": { "type": ["string", "null"], "format": "date-time" }
            }
          }
        },
        "completed": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["id", "description", "result"],
            "properties": {
              "id": { "type": "string" },
              "description": { "type": "string" },
              "result": { "type": "string", "description": "Outcome or output" },
              "completed_by": { "type": "string" },
              "completed_at": { "type": "string", "format": "date-time" }
            }
          }
        },
        "failed": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["id", "description", "error"],
            "properties": {
              "id": { "type": "string" },
              "description": { "type": "string" },
              "error": { "type": "string" },
              "retries_remaining": { "type": "integer" }
            }
          }
        }
      }
    },
    "dependencies": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "type", "description"],
        "properties": {
          "id": { "type": "string" },
          "type": {
            "type": "string",
            "enum": ["data", "api", "human_approval", "external_event", "resource"],
            "description": "Kind of dependency"
          },
          "description": { "type": "string" },
          "status": { "type": "string", "enum": ["blocked", "available", "unknown"], "default": "unknown" },
          "source": { "type": "string", "description": "Where this dependency comes from (URL, service name, etc.)" }
        }
      },
      "description": "External dependencies the receiving agent should know about"
    },
    "hitl": {
      "type": ["object", "null"],
      "description": "Human-in-the-loop checkpoint (null if no HITL needed)",
      "properties": {
        "required": { "type": "boolean", "default": false },
        "reason": { "type": "string", "description": "Why human review is needed" },
        "question": { "type": "string", "description": "Question or decision point for the human" },
        "options": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Predefined choices (optional, null = free-form)"
        },
        "response": { "type": ["string", "null"], "description": "Human's response (null until answered)" },
        "responded_at": { "type": ["string", "null"], "format": "date-time" },
        "responded_by": { "type": ["string", "null"], "description": "Human identifier" },
        "timeout_seconds": { "type": ["integer", "null"], "description": "Auto-escalation timeout" }
      }
    },
    "status": {
      "type": "string",
      "enum": ["created", "claimed", "in_progress", "awaiting_human", "completed", "failed", "expired"],
      "default": "created",
      "description": "Packet lifecycle status"
    }
  }
}
```

### Example Packet (Minimal)

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "version": "1.0.0",
  "parent_packet_id": null,
  "metadata": {
    "source_agent": { "id": "sales-agent-01", "name": "SalesBot", "framework": "langchain" },
    "target_agent": { "id": "billing-agent-01", "name": "BillingBot", "framework": "crewai" },
    "created_at": "2026-05-13T21:00:00Z",
    "claimed_at": null,
    "completed_at": null,
    "priority": "normal",
    "tags": ["sales-to-billing", "subscription-upgrade"]
  },
  "context": {
    "summary": "Customer requested upgrade from Pro to Business tier. Eligibility confirmed.",
    "conversation_state": [
      { "role": "user", "content": "I want to upgrade to Business", "timestamp": "2026-05-13T20:55:00Z" },
      { "role": "agent", "content": "Great! Your account is eligible. Let me hand you to billing.", "timestamp": "2026-05-13T20:59:00Z" }
    ],
    "artifacts": [
      { "key": "customer_profile", "value": { "id": "cust-789", "tier": "pro", "eligible": true } }
    ],
    "custom": {}
  },
  "decisions": [
    { "id": "d1", "decision": "Proceed with upgrade", "rationale": "Customer eligible, no outstanding invoices", "alternatives": ["defer"], "decided_by": "sales-agent-01", "timestamp": "2026-05-13T20:58:00Z" }
  ],
  "actions": {
    "pending": [
      { "id": "a1", "description": "Process payment for Business tier", "assignee": "billing-agent-01", "priority": "high", "depends_on": [], "deadline": null }
    ],
    "completed": [],
    "failed": []
  },
  "dependencies": [
    { "id": "dep1", "type": "api", "description": "Payment gateway must be up", "status": "available", "source": "stripe-api" }
  ],
  "hitl": null,
  "status": "created"
}
```

### Example Packet (Human-in-the-Loop)

```json
{
  "id": "f7e6d5c4-b3a2-1098-7654-fedcba098765",
  "version": "1.0.0",
  "parent_packet_id": null,
  "metadata": {
    "source_agent": { "id": "support-agent-01", "name": "SupportBot", "framework": "langchain" },
    "target_agent": { "id": "human", "name": "Account Manager" },
    "created_at": "2026-05-13T21:00:00Z",
    "claimed_at": null,
    "completed_at": null,
    "priority": "high",
    "tags": ["refund-approval"]
  },
  "context": {
    "summary": "Customer requesting $500 refund outside policy window. Requires manager approval.",
    "conversation_state": [
      { "role": "user", "content": "I need a refund for order #1234", "timestamp": "2026-05-13T20:50:00Z" },
      { "role": "agent", "content": "That order is past the 30-day window. I'll escalate for approval.", "timestamp": "2026-05-13T20:55:00Z" }
    ],
    "artifacts": [
      { "key": "order_details", "value": { "order_id": "#1234", "amount": 500, "days_since_purchase": 42 } }
    ],
    "custom": {}
  },
  "decisions": [
    { "id": "d1", "decision": "Escalate to human for refund approval", "rationale": "Outside 30-day policy, requires manager override", "alternatives": ["deny immediately"], "decided_by": "support-agent-01", "timestamp": "2026-05-13T20:55:00Z" }
  ],
  "actions": {
    "pending": [
      { "id": "a1", "description": "Approve or deny $500 refund for order #1234", "assignee": "human", "priority": "high", "depends_on": [], "deadline": "2026-05-14T21:00:00Z" }
    ],
    "completed": [],
    "failed": []
  },
  "dependencies": [],
  "hitl": {
    "required": true,
    "reason": "Refund exceeds policy threshold — requires human approval",
    "question": "Should we approve the $500 refund for order #1234?",
    "options": ["Approve full refund", "Approve partial refund", "Deny refund"],
    "response": null,
    "responded_at": null,
    "responded_by": null,
    "timeout_seconds": 86400
  },
  "status": "awaiting_human"
}
```

---

## 3. Core API Design

### Base URL

```
http://localhost:8080/api/v1
```

### Authentication

All endpoints require `X-API-Key` header. API keys are scoped to a tenant.

---

### `POST /packets` — Create Handoff Packet

Create a new handoff packet. Validates against v1 schema.

**Request:**

```json
{
  "parent_packet_id": null,
  "metadata": {
    "source_agent": { "id": "agent-1", "name": "SalesBot", "framework": "langchain" },
    "target_agent": { "id": "agent-2", "name": "BillingBot", "framework": "crewai" },
    "priority": "normal",
    "tags": ["sales-to-billing"]
  },
  "context": {
    "summary": "Customer wants to upgrade tier",
    "conversation_state": [
      { "role": "user", "content": "I want to upgrade" }
    ],
    "artifacts": [],
    "custom": {}
  },
  "decisions": [],
  "actions": {
    "pending": [{ "id": "a1", "description": "Process upgrade", "assignee": "agent-2", "priority": "normal", "depends_on": [] }],
    "completed": [],
    "failed": []
  },
  "dependencies": [],
  "hitl": null
}
```

**Response `201 Created`:**

```json
{
  "id": "a1b2c3d4-...",
  "version": "1.0.0",
  "status": "created",
  "metadata": {
    "...": "...",
    "created_at": "2026-05-13T21:00:00Z",
    "claimed_at": null,
    "completed_at": null
  },
  "context": { "...": "..." },
  "decisions": [],
  "actions": { "...": "..." },
  "dependencies": [],
  "hitl": null,
  "_links": {
    "self": "/api/v1/packets/a1b2c3d4-...",
    "claim": "/api/v1/packets/a1b2c3d4-.../claim",
    "history": "/api/v1/packets/a1b2c3d4-.../history"
  }
}
```

**Errors:**
- `400 Bad Request` — Schema validation failed (includes field-level errors)
- `401 Unauthorized` — Missing or invalid API key
- `429 Too Many Requests` — Rate limit exceeded

---

### `POST /packets/{id}/claim` — Claim a Packet

Agent claims an unclaimed packet, transitioning status from `created` → `claimed`.

**Request:**

```json
{
  "agent_id": "billing-agent-01",
  "agent_name": "BillingBot",
  "framework": "crewai"
}
```

**Response `200 OK`:**

```json
{
  "id": "a1b2c3d4-...",
  "status": "claimed",
  "metadata": {
    "...": "...",
    "claimed_at": "2026-05-13T21:05:00Z",
    "target_agent": { "id": "billing-agent-01", "name": "BillingBot", "framework": "crewai" }
  },
  "...": "..."
}
```

**Errors:**
- `404 Not Found` — Packet doesn't exist
- `409 Conflict` — Packet already claimed (returns current claimant info)
- `410 Gone` — Packet expired

---

### `PATCH /packets/{id}` — Update Packet

Partial update to packet fields. Used for progressing work, adding decisions, updating actions.

**Request:**

```json
{
  "status": "in_progress",
  "decisions": [
    { "id": "d2", "decision": "Applied Business tier pricing", "rationale": "Customer confirmed upgrade", "decided_by": "billing-agent-01", "timestamp": "2026-05-13T21:10:00Z" }
  ],
  "actions": {
    "completed": [
      { "id": "a1", "description": "Process upgrade", "result": "Upgraded to Business tier", "completed_by": "billing-agent-01", "completed_at": "2026-05-13T21:12:00Z" }
    ]
  }
}
```

**Response `200 OK`:** Full updated packet.

**Errors:**
- `400` — Invalid status transition
- `404` — Packet not found

---

### `POST /packets/{id}/respond` — Human Responds to HITL Checkpoint

Submit a human response to a packet awaiting human review.

**Request:**

```json
{
  "response": "Approve full refund",
  "responded_by": "manager@aaron.co"
}
```

**Response `200 OK`:** Updated packet with `hitl.response` filled and `status` → `claimed` (if auto-released) or `in_progress`.

**Errors:**
- `409 Conflict` — Packet not in `awaiting_human` status
- `410 Gone` — HITL timeout expired

---

### `GET /packets` — Query Packet History

List packets with filtering and pagination.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by status (comma-separated for multiple) |
| `source_agent` | string | Filter by source agent ID |
| `target_agent` | string | Filter by target agent ID |
| `tags` | string | Filter by tags (comma-separated, all must match) |
| `priority` | string | Filter by priority |
| `hitl_required` | boolean | Only packets needing human review |
| `created_after` | datetime | ISO 8601 timestamp |
| `created_before` | datetime | ISO 8601 timestamp |
| `limit` | integer | Max results (default 50, max 200) |
| `offset` | integer | Pagination offset |
| `sort` | string | Sort field: `created_at` (default), `priority`, `status` |
| `order` | string | `asc` or `desc` (default `desc`) |

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

Full packet detail.

**Response `200 OK`:** Complete packet object (same as create response).

**Errors:**
- `404 Not Found`

---

### `GET /packets/{id}/history` — Packet Event History

Audit trail of all status transitions and modifications.

**Response `200 OK`:**

```json
{
  "packet_id": "a1b2c3d4-...",
  "events": [
    { "timestamp": "2026-05-13T21:00:00Z", "type": "created", "actor": "agent:sales-agent-01", "details": {} },
    { "timestamp": "2026-05-13T21:05:00Z", "type": "claimed", "actor": "agent:billing-agent-01", "details": {} },
    { "timestamp": "2026-05-13T21:12:00Z", "type": "completed", "actor": "agent:billing-agent-01", "details": { "actions_completed": 1 } }
  ]
}
```

---

### `GET /packets/awaiting` — List HITL-Pending Packets

Convenience endpoint: returns all packets with `status=awaiting_human`.

**Response `200 OK`:** Same shape as `GET /packets` but filtered.

---

### `POST /packets/{id}/chain` — Create Chain Packet

Create a new packet that continues from this one, automatically setting `parent_packet_id`.

**Request:** Same as `POST /packets` but `parent_packet_id` is auto-set.

**Response `201 Created`:** New packet with `parent_packet_id` populated.

---

### `DELETE /packets/{id}` — Delete Packet

Soft delete (marks as `expired`). Hard delete requires admin scope.

**Response `204 No Content`**

---

### Webhook / Event Subscription (MVP: Polling)

MVP uses polling (`GET /packets?status=created` for agents, `GET /packets/awaiting` for humans). WebSocket/SSE event streaming is v0.2 scope.

For MVP, a lightweight webhook registration is included:

**`POST /hooks`**

```json
{
  "url": "https://my-agent.example.com/handoffrail/webhook",
  "events": ["packet.created", "packet.claimed", "packet.completed", "hitl.response_ready"],
  "secret": "whsec_..."
}
```

Webhooks fire with a `POST` containing the event type and full packet payload. HMAC-SHA256 signature in `X-HR-Signature` header for verification.

---

## 4. SDK Design

### Python SDK Structure

```
handoffrail-sdk/
├── pyproject.toml
├── src/
│   └── handoffrail/
│       ├── __init__.py          # Public API
│       ├── client.py            # HTTP client wrapper
│       ├── packet.py            # Packet data models
│       ├── exceptions.py        # Custom exceptions
│       └── integrations/
│           ├── __init__.py
│           ├── base.py          # Base adapter class
│           ├── langchain.py     # LangChain integration
│           └── crewai.py        # CrewAI integration
├── tests/
│   ├── test_client.py
│   ├── test_packet.py
│   └── test_integrations/
│       ├── test_langchain.py
│       └── test_crewai.py
└── README.md
```

### Key Classes & Methods

#### `HandoffRailClient` — Core HTTP Client

```python
from handoffrail import HandoffRailClient

client = HandoffRailClient(
    base_url="http://localhost:8080/api/v1",
    api_key="hr_key_..."
)

# Create a handoff packet
packet = client.create_packet(
    source_agent={"id": "sales-01", "name": "SalesBot", "framework": "langchain"},
    target_agent={"id": "billing-01", "name": "BillingBot", "framework": "crewai"},
    summary="Customer wants to upgrade to Business tier",
    conversation_state=[
        {"role": "user", "content": "I want to upgrade"}
    ],
    pending_actions=[
        {"id": "a1", "description": "Process upgrade", "assignee": "billing-01", "priority": "high"}
    ],
    priority="normal",
    tags=["upgrade"]
)

# Claim a packet
claimed = client.claim_packet(packet.id, agent_id="billing-01", agent_name="BillingBot")

# Update a packet
updated = client.update_packet(
    packet.id,
    status="in_progress",
    decisions=[{"id": "d1", "decision": "...", "rationale": "...", "decided_by": "billing-01"}]
)

# Complete a packet
completed = client.complete_packet(packet.id)

# Respond to HITL checkpoint
responded = client.respond_to_hitl(packet.id, response="Approved", responded_by="manager@aaron.co")

# Query packets
results = client.list_packets(status="created", target_agent="billing-01", limit=10)

# Get packets awaiting human review
awaiting = client.list_awaiting_human()

# Get packet history
history = client.get_packet_history(packet.id)

# Chain: create follow-up packet
chained = client.chain_packet(packet.id, target_agent={"id": "followup-01", "name": "FollowUpBot"})
```

#### `HandoffPacket` — Data Model

```python
from handoffrail import HandoffPacket

packet = HandoffPacket(
    source_agent={"id": "sales-01", "name": "SalesBot", "framework": "langchain"},
    target_agent={"id": "billing-01", "name": "BillingBot", "framework": "crewai"},
    summary="Customer upgrade request",
    priority="high"
)

# Builder pattern for complex packets
packet = (
    HandoffPacket.builder()
    .from_agent("sales-01", "SalesBot", framework="langchain")
    .to_agent("billing-01", "BillingBot", framework="crewai")
    .with_summary("Customer wants Business tier")
    .with_conversation(messages=[...])
    .with_decision("Proceed with upgrade", rationale="Eligible customer")
    .with_action("Process payment", assignee="billing-01", priority="high")
    .with_dependency("stripe-api", type="api", description="Payment gateway")
    .with_hitl(reason="High-value upgrade needs approval", question="Approve upgrade?")
    .with_priority("high")
    .with_tags(["upgrade", "business-tier"])
    .build()
)

# Access fields
print(packet.id)           # UUID (auto-generated)
print(packet.status)       # "created"
print(packet.to_dict())    # Full dict
print(packet.to_json())    # JSON string
```

#### `LangChainAdapter` — LangChain Integration

```python
from handoffrail.integrations.langchain import LangChainAdapter

adapter = LangChainAdapter(client=client, agent_id="sales-01", agent_name="SalesBot")

# Wrap a LangChain agent to auto-send handoff on completion
# The adapter hooks into the agent's output to create a packet
adapter.wrap(agent)  # Returns wrapped agent

# Manually create a handoff from current conversation
packet = adapter.handoff(
    target_agent_id="billing-01",
    target_agent_name="BillingBot",
    summary="Customer wants upgrade",
    conversation_state=adapter.extract_conversation(chat_history),
    pending_actions=[...]
)

# Receive: poll for unclaimed packets and pick up work
packet = adapter.poll_for_handoff(timeout=30)

# Resume conversation from a packet
chat_history = adapter.resume_conversation(packet)
agent.run(chat_history)  # Continue from where the previous agent left off
```

#### `CrewAIAdapter` — CrewAI Integration

```python
from handoffrail.integrations.crewai import CrewAIAdapter

adapter = CrewAIAdapter(client=client, agent_id="billing-01", agent_name="BillingBot")

# Create handoff from a CrewAI task completion
packet = adapter.handoff_from_task(
    task=completed_task,
    target_agent_id="support-01",
    summary="Billing processed, customer needs onboarding"
)

# Receive: claim next available packet for this agent
packet = adapter.poll_for_handoff(task_type="billing")

# Convert packet context to CrewAI task input
task_input = adapter.packet_to_task_input(packet)
```

#### `BaseAdapter` — For Custom Agents

```python
from handoffrail.integrations.base import BaseAdapter

class MyCustomAdapter(BaseAdapter):
    def extract_conversation(self, context) -> list[dict]:
        # Custom logic to extract conversation turns
        ...

    def resume_conversation(self, packet) -> Any:
        # Custom logic to convert packet to agent input
        ...

adapter = MyCustomAdapter(client=client, agent_id="custom-01", agent_name="CustomBot")
```

---

## 5. Tech Stack

| Layer | Technology | Justification |
|-------|-----------|--------------|
| **Language** | Python 3.11+ | Dominant language for AI/ML ecosystem; LangChain & CrewAI are Python-native |
| **Framework** | FastAPI | Async-native, auto OpenAPI docs, Pydantic validation, wide adoption |
| **Database** | SQLite (dev) / PostgreSQL (prod) | SQLite zero-config for local dev; PostgreSQL for production scale |
| **ORM** | SQLAlchemy 2.0 + Alembic | Type-safe queries, async support, migration management |
| **Validation** | Pydantic v2 | JSON schema generation, validation, serialization — built into FastAPI |
| **Auth** | API Keys (MVP) → OAuth2 (v0.2) | Simple API key auth for MVP; OAuth2/SSO for business tier |
| **Messaging** | Webhooks (MVP) → Redis Streams (v0.2) | Webhooks for event delivery; Redis Streams for real-time pub/sub later |
| **Task Queue** | Celery + Redis (hitl timeouts, cleanup) | Background jobs for packet expiry, HITL timeout escalation, metrics |
| **Containerization** | Docker + Docker Compose | One-command local dev; consistent deploy target |
| **Testing** | pytest + httpx (async tests) | Standard Python testing; httpx for async API tests |
| **CLI** | Click | Packet inspection, status queries, manual HITL responses from terminal |
| **CI/CD** | GitHub Actions | Automated test + lint + publish pipeline |
| **SDK Packaging** | Poetry | Dependency management + publish to PyPI |
| **Monitoring** | Structured logging (structlog) + Prometheus metrics | Observability from day one |

### Architecture Rationale

**Why FastAPI over Flask/Django:**
- Async-first (critical for polling/webhook handlers)
- Auto-generated OpenAPI docs (saves SDK doc effort)
- Pydantic models double as schema validation + DB models
- Native WebSocket support ready for v0.2

**Why SQLite for dev:**
- Zero config — `pip install` and go
- Single-file DB perfect for local testing and Docker
- Production switch is a config change (SQLAlchemy abstracts it)

**Why Redis (later) over RabbitMQ/Kafka:**
- Simpler ops for MVP scale
- Streams API provides ordered, consumer-group messaging
- Can upgrade to Kafka if throughput demands it

---

## 6. MVP Milestones

### Week 1 — Foundation (Days 1–7)

**Goal:** Project scaffolding, schema, data models, basic API skeleton

- [ ] Initialize project structure (monorepo: `server/`, `sdk/`, `cli/`)
- [ ] Define Pydantic models for full v1 packet schema
- [ ] Set up FastAPI app with health check endpoint
- [ ] Configure SQLAlchemy + SQLite with migration scaffolding (Alembic)
- [ ] `POST /packets` — create endpoint with full validation
- [ ] `GET /packets/{id}` — read endpoint
- [ ] Docker Compose for local dev (API + SQLite)
- [ ] pytest scaffolding + CI pipeline (GitHub Actions)
- [ ] JSON Schema file published alongside API for SDK validation

**Deliverable:** Working API that creates and reads handoff packets with full schema validation.

---

### Week 2 — Core CRUD + Claim (Days 8–14)

**Goal:** Full packet lifecycle — claim, update, complete, delete

- [ ] `POST /packets/{id}/claim` — claim endpoint with conflict detection
- [ ] `PATCH /packets/{id}` — partial update with status transition validation
- [ ] `DELETE /packets/{id}` — soft delete (expire)
- [ ] Status state machine: `created → claimed → in_progress → completed`
- [ ] Branch: `awaiting_human` status and HITL flow
- [ ] `POST /packets/{id}/respond` — HITL response endpoint
- [ ] Packet expiry background task (Celery)
- [ ] API key auth middleware
- [ ] API key management: `POST /keys`, `DELETE /keys/{id}`, `GET /keys`
- [ ] Integration tests for full lifecycle

**Deliverable:** Complete packet lifecycle with status transitions and HITL checkpoint flow.

---

### Week 3 — Query + History (Days 15–21)

**Goal:** Filtering, pagination, audit trail, chain handoffs

- [ ] `GET /packets` — list with all query parameters (status, agent, tags, date range, pagination)
- [ ] `GET /packets/awaiting` — HITL convenience endpoint
- [ ] `GET /packets/{id}/history` — event history (all transitions)
- [ ] `POST /packets/{id}/chain` — create chained follow-up packet
- [ ] Webhook registration: `POST /hooks`, `GET /hooks`, `DELETE /hooks/{id}`
- [ ] Webhook delivery with HMAC-SHA256 signing
- [ ] Rate limiting middleware (per API key, tier-based)
- [ ] Structured logging (structlog)

**Deliverable:** Queryable packet store with audit trail, webhook delivery, and chain handoffs.

---

### Week 4 — Python SDK Core (Days 22–28)

**Goal:** SDK client, data models, builder pattern

- [ ] SDK project scaffolding (Poetry, pyproject.toml, structure)
- [ ] `HandoffRailClient` — HTTP client with all API methods
- [ ] `HandoffPacket` — data model with builder pattern
- [ ] `PacketBuilder` — fluent builder for complex packets
- [ ] Error handling: `HandoffRailError`, `ValidationError`, `ConflictError`, `NotFoundError`
- [ ] Async client support (`AsyncHandoffRailClient`)
- [ ] Full SDK test suite (mocked API responses)
- [ ] Publish to PyPI (private package initially)

**Deliverable:** Usable Python SDK that wraps all API endpoints.

---

### Week 5 — Framework Integrations (Days 29–35)

**Goal:** LangChain + CrewAI adapters, custom adapter base class

- [ ] `BaseAdapter` — abstract class with hook points for custom frameworks
- [ ] `LangChainAdapter` — conversation extraction, handoff creation, resumption
- [ ] `CrewAIAdapter` — task completion handoff, packet-to-task input conversion
- [ ] Integration tests with real LangChain and CrewAI agents
- [ ] Example notebooks: "Handoff between two LangChain agents", "LangChain → CrewAI handoff"
- [ ] Example: HITL flow with human approval in Jupyter
- [ ] Documentation: integration guides for each framework

**Deliverable:** Working adapters for LangChain and CrewAI with example notebooks.

---

### Week 6 — CLI + Polish (Days 36–42) ✅

**Goal:** CLI tool, error handling, docs, edge cases

- [x] `handoffrail` CLI (Click):
  - `handoffrail create` — create packet from YAML/JSON
  - `handoffrail get <id>` — inspect packet
  - `handoffrail list` — list packets with filters
  - `handoffrail claim <id>` — claim a packet
  - `handoffrail respond <id>` — respond to HITL
  - `handoffrail history <id>` — view event trail
  - `handoffrail serve` — start API server (dev mode)
- [x] Comprehensive error messages and edge case handling
- [x] Packet size limits and validation (max 256KB per packet)
- [x] Request timeout handling and retry logic in SDK
- [ ] API documentation (auto-generated from FastAPI + hand-written guides)
- [ ] README.md with quickstart, architecture, deployment

**Deliverable:** CLI tool for manual packet operations, polished error handling, docs.

---

### Week 7 — Deployment + Auth Tiers (Days 43–49)

**Goal:** Production-ready deployment, tier-based access control

- [ ] PostgreSQL migration tested and documented
- [ ] Docker image published (GHCR)
- [ ] Docker Compose production config (API + PostgreSQL + Redis + Celery)
- [ ] Rate limiting per tier (free/pro/business)
- [ ] Agent count enforcement per tier
- [ ] Audit trail completeness for business tier
- [ ] Environment-based config (dev/staging/prod)
- [ ] Health check and readiness endpoints
- [ ] Prometheus metrics endpoint (`/metrics`)

**Deliverable:** Production-ready Docker deployment with tier enforcement.

---

### Week 8 — Landing Page + Launch (Days 50–56) ✅

**Goal:** Marketing site, examples, launch readiness

- [x] Landing page (modern dark theme, responsive)
  - Hero section with value prop
  - How it works (3-step diagram: Create → Claim → Chain)
  - Feature highlights (9 cards)
  - Code examples (Python SDK, REST, CLI, Builder, LangChain tabs)
  - Pricing tiers (Free / Pro / Business)
  - Quick start section
  - CTA + GitHub link
- [x] GitHub README polished with badges, features table, architecture
- [x] Quickstart guide (5-minute setup to first handoff)
- [x] API reference (all 19 endpoints with request/response examples)
- [x] SDK guide (sync + async, builder, adapters, error handling)
- [x] Deployment guide (Docker, PostgreSQL, Redis, monitoring, security)
- [x] Example repo with 2 end-to-end demos:
  1. `basic_handoff.py` — simple two-agent handoff with full lifecycle
  2. `chain_handoff.py` — multi-agent chain with HITL approval

**Deliverable:** Public-facing landing page, docs, and example repo ready for launch.

---

## 7. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        HandoffRail Architecture                 │
└─────────────────────────────────────────────────────────────────┘

  ┌──────────┐                                                    ┌──────────┐
  │          │   1. Create Packet                                  │          │
  │ Agent A  │ ──────────────────────┐                            │ Agent B  │
  │(LangChain)│                      │                            │(CrewAI)  │
  │          │   ┌───────────────────▼──────────────────┐          │          │
  └──────────┘   │                                     │   3. Claim ───────────┘
                  │        HandoffRail API (FastAPI)     │  & Resume
                  │                                     │  Packet
  ┌──────────┐   │  ┌─────────────────────────────────┐ │          ┌──────────┐
  │          │   │  │                                 │ │          │          │
  │  Human   │   │  │     Packet Store (DB Layer)     │ │          │  Agent C │
  │(Manager) │   │  │  ┌────────┐  ┌──────────────┐   │ │          │(AutoGen) │
  │          │   │  │  │SQLite/ │  │  Event Log   │   │ │          │          │
  └────┬─────┘   │  │  │PG      │  │  (History)   │   │ │          └────┬─────┘
       │         │  │  └────────┘  └──────────────┘   │ │               │
       │         │  │                                 │ │               │
  5. Respond     │  └─────────────────────────────────┘ │               │
  to HITL        │                                     │               │
       │         │  ┌─────────────────────────────────┐ │               │
       │         │  │     Auth & Rate Limiting         │ │               │
       └─────────┼──│  (API Keys, Tier Enforcement)   │─┼───────────────┘
                 │  └─────────────────────────────────┘ │
                 │                                     │
                 │  ┌─────────────────────────────────┐ │
                 │  │     Webhook Dispatcher            │ │
                 │  │  (Event → HTTP POST to hooks)     │ │
                 │  └─────────────────────────────────┘ │
                 │                                     │
                 │  ┌─────────────────────────────────┐ │
                 │  │     Background Workers            │ │
                 │  │  (Celery: expiry, HITL timeout,  │ │
                 │  │   metrics, cleanup)               │ │
                 │  └─────────────────────────────────┘ │
                 └──────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────┐
  │                     SDK Layer                                │
  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
  │  │ HandoffRail  │  │ LangChain    │  │ CrewAI Adapter    │  │
  │  │ Client       │  │ Adapter      │  │                   │  │
  │  └──────┬───────┘  └──────┬───────┘  └────────┬──────────┘  │
  │         │                 │                    │              │
  │         └─────────────────┴────────────────────┘              │
  │                           │                                  │
  │                    BaseAdapter                               │
  └──────────────────────────────────────────────────────────────┘

  Flow:
  1. Agent A creates handoff packet via SDK or HTTP
  2. Packet stored in DB, status = "created"
  3. Agent B (or Human) claims packet, status = "claimed" / "awaiting_human"
  4. Agent B works through packet context, decisions, and actions
  5. If HITL required: Human responds, packet continues
  6. Agent B completes packet, status = "completed"
  7. Optional: Agent B chains to next agent via new packet
```

---

## 8. Monetization Implementation

### Tier Definitions

| Feature | Free | Pro ($29/mo) | Business ($99/mo) |
|---------|------|-------------|-------------------|
| **Handoffs/day** | 5 | Unlimited | Unlimited |
| **Registered agents** | 2 | 10 | 50 |
| **API keys** | 1 | 5 | 25 |
| **Packet size** | 64KB | 256KB | 1MB |
| **Retention** | 7 days | 30 days | 1 year |
| **HITL checkpoints** | ✅ | ✅ | ✅ |
| **Webhooks** | ❌ | ✅ (5 hooks) | ✅ (unlimited) |
| **Audit trail** | ❌ | Last 30 days | Full history + export |
| **Event history** | ❌ | ✅ | ✅ |
| **SSO** | ❌ | ❌ | ✅ (Google, Microsoft, SAML) |
| **Priority support** | ❌ | Email | Slack channel |
| **Custom branding** | ❌ | ❌ | ✅ |

### Enforcement Architecture

```python
# Rate limiting middleware (per API key, per tier)
TIER_LIMITS = {
    "free": {"handoffs_per_day": 5, "max_agents": 2, "max_api_keys": 1, "max_packet_size": 65536},
    "pro": {"handoffs_per_day": -1, "max_agents": 10, "max_api_keys": 5, "max_packet_size": 262144},
    "business": {"handoffs_per_day": -1, "max_agents": 50, "max_api_keys": 25, "max_packet_size": 1048576},
}

# Middleware checks on every request:
# 1. API key → tenant → tier
# 2. Tier → limits
# 3. Current usage vs limits
# 4. Allow/deny + rate limit headers
```

### Billing Integration (v0.2+)

- Stripe for subscription management
- Metered usage tracking (handoffs beyond daily limit in pro)
- Usage dashboard in web UI

---

## 9. Risk Assessment

### High Priority

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|------------|
| **Schema too rigid for diverse agents** | High | Medium | `context.custom` field allows arbitrary data; schema versioning with migration path; community feedback loop in weeks 5–6 |
| **Low adoption — solving a problem not enough people have yet** | High | Medium | Focus on LangChain + CrewAI communities (largest); publish compelling demos; "5-minute quickstart" as north star |
| **Competitive response from AgentOps/Fluq** | Medium | Low | First-mover advantage in handoff-specific category; open-core model builds trust; differentiate on structured packets + HITL |
| **HITL flow UX is clunky without web UI** | Medium | High | CLI-first HITL for MVP; API-driven for programmatic; web dashboard is v0.2 priority |

### Medium Priority

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|------------|
| **Large packets degrade performance** | Medium | Medium | 64KB default size cap; streaming for large artifacts; lazy-load conversation_state |
| **SQLite concurrency limits under load** | Medium | Low | SQLite for dev only; PostgreSQL for prod from day one in Docker; WAL mode for better concurrency |
| **SDK breaking changes between v0.1 and v0.2** | Medium | Medium | Semantic versioning; stable API surface for client methods; integration adapters may change but client won't |
| **Security vulnerabilities in API key auth** | High | Low | Key hashing (never store plaintext); rate limiting; HTTPS required; audit logging |

### Assumptions

1. **Python-first is correct.** LangChain and CrewAI are Python-dominant; TypeScript SDK can wait.
2. **Polling is acceptable for MVP.** Real-time streaming is nice-to-have; agents already poll for work.
3. **Packet size < 256KB covers 95% of use cases.** Large artifacts (files, images) should be referenced by URL, not embedded.
4. **Single-tenant is fine for MVP.** Multi-tenant isolation with org scoping is v0.2.
5. **5 handoffs/day is meaningful for free tier.** Enough to evaluate, too little for production.
6. **Human responders use CLI or API initially.** Web dashboard for HITL is v0.2 scope.

---

## 10. Directory Structure

```
handoffrail/
├── README.md
├── LICENSE
├── RESEARCH.md                    # Competitive landscape research
├── PLAN.md                        # This file
├── docker-compose.yml             # Local dev: API + PostgreSQL + Redis
├── docker-compose.prod.yml        # Production config
│
├── server/                        # HandoffRail API Server
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/                   # Database migrations
│   │   ├── env.py
│   │   └── versions/
│   ├── src/
│   │   └── handoffrail/
│   │       ├── __init__.py
│   │       ├── main.py            # FastAPI app entry point
│   │       ├── config.py          # Settings (env-based)
│   │       ├── models/
│   │       │   ├── __init__.py
│   │       │   ├── packet.py      # SQLAlchemy models
│   │       │   ├── event.py       # Event history model
│   │       │   ├── hook.py        # Webhook model
│   │       │   └── api_key.py     # API key + tenant model
│   │       ├── schemas/
│   │       │   ├── __init__.py
│   │       │   ├── packet.py      # Pydantic request/response models
│   │       │   ├── event.py
│   │       │   ├── hook.py
│   │       │   └── common.py      # Pagination, errors, etc.
│   │       ├── api/
│   │       │   ├── __init__.py
│   │       │   ├── router.py      # Main API router
│   │       │   ├── packets.py     # Packet endpoints
│   │       │   ├── hooks.py       # Webhook endpoints
│   │       │   └── keys.py        # API key management
│   │       ├── services/
│   │       │   ├── __init__.py
│   │       │   ├── packet_service.py   # Business logic
│   │       │   ├── hook_service.py    # Webhook dispatch
│   │       │   └── auth_service.py    # API key auth + tier limits
│   │       ├── workers/
│   │       │   ├── __init__.py
│   │       │   ├── expiry.py      # Packet expiry job
│   │       │   ├── hitl_timeout.py # HITL escalation job
│   │       │   └── webhook.py     # Async webhook delivery
│   │       └── middleware/
│   │           ├── __init__.py
│   │           ├── rate_limit.py  # Tier-based rate limiting
│   │           └── auth.py        # API key extraction
│   └── tests/
│       ├── conftest.py
│       ├── test_packets.py
│       ├── test_claim.py
│       ├── test_hitl.py
│       ├── test_hooks.py
│       ├── test_auth.py
│       └── test_rate_limit.py
│
├── sdk/                           # Python SDK
│   ├── pyproject.toml
│   ├── src/
│   │   └── handoffrail/
│   │       ├── __init__.py
│   │       ├── client.py          # HandoffRailClient (sync)
│   │       ├── async_client.py    # AsyncHandoffRailClient
│   │       ├── packet.py          # HandoffPacket + PacketBuilder
│   │       ├── exceptions.py      # Error classes
│   │       └── integrations/
│   │           ├── __init__.py
│   │           ├── base.py        # BaseAdapter
│   │           ├── langchain.py   # LangChainAdapter
│   │           └── crewai.py      # CrewAIAdapter
│   └── tests/
│       ├── conftest.py
│       ├── test_client.py
│       ├── test_packet.py
│       ├── test_async_client.py
│       └── test_integrations/
│           ├── test_langchain.py
│           └── test_crewai.py
│
├── cli/                           # CLI Tool
│   ├── pyproject.toml
│   ├── src/
│   │   └── handoffrail_cli/
│   │       ├── __init__.py
│   │       ├── main.py            # Click CLI entry point
│   │       └── commands/
│   │           ├── __init__.py
│   │           ├── create.py
│   │           ├── get.py
│   │           ├── list.py
│   │           ├── claim.py
│   │           ├── respond.py
│   │           ├── history.py
│   │           └── serve.py
│   └── tests/
│       └── test_cli.py
│
├── schemas/                       # Published JSON schemas
│   └── packet.v1.schema.json
│
├── examples/                      # Example notebooks & scripts
│   ├── 01_basic_handoff.py
│   ├── 02_langchain_to_crewai.py
│   ├── 03_hitl_approval_flow.py
│   └── 04_chain_handoffs.py
│
├── docs/                          # Documentation
│   ├── quickstart.md
│   ├── api-reference.md
│   ├── sdk-guide.md
│   ├── integration-langchain.md
│   ├── integration-crewai.md
│   ├── deployment.md
│   └── packet-schema.md
│
└── .github/
    └── workflows/
        ├── test.yml
        ├── publish-sdk.yml
        └── publish-docker.yml
```

---

*Plan authored: 2026-05-13 by Mela*  
*Timeline: 8 weeks to MVP launch*  
*Status: Ready for development*