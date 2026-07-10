# HandoffRail

[![CI](https://github.com/MelaBuilt-AI/HandoffRail/actions/workflows/ci.yml/badge.svg)](https://github.com/MelaBuilt-AI/HandoffRail/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/handoffrail-sdk)](https://pypi.org/project/handoffrail-sdk/)
[![npm](https://img.shields.io/npm/v/handoffrail-sdk)](https://www.npmjs.com/package/handoffrail-sdk)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](https://python.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.4+-3178c6)](https://www.typescriptlang.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/MelaBuilt-AI/HandoffRail/blob/main/LICENSE)
[![Docker](https://img.shields.io/badge/docker-GHCR-2496ED)](https://github.com/MelaBuilt-AI/HandoffRail/pkgs/container/handoffrail)
[![Docs](https://img.shields.io/badge/docs-handoffrail.melabuilt.ai-6c5ce7)](https://handoffrail.melabuilt.ai/docs/)

**Session-continuity middleware for multi-agent AI workflows.**

When one agent finishes its part and hands off to another — or to a human reviewer — the full context survives the transition. Decisions, pending actions, dependencies, conversation state, and audit history all travel in a structured packet. No context loss, no repetition, no dropped threads.

---

## Why HandoffRail?

Multi-agent AI systems fail in the gaps between agents. Agent A finishes, Agent B starts from scratch, and the user repeats everything. HandoffRail closes that gap with a structured handoff protocol:

- **Structured packets** — Not freeform text. Typed fields for decisions, actions, dependencies, conversation state, and human-in-the-loop checkpoints.
- **Lifecycle management** — Packets move through a state machine: `created → claimed → in_progress → completed` (with `awaiting_human` and `failed` branches).
- **Human-in-the-loop** — Built-in HITL checkpoints with questions, options, timeouts, and approval routing.
- **Chain handoffs** — Agent B can create a follow-up packet linked to Agent A's, preserving full lineage.
- **Webhooks & real-time** — HMAC-signed webhooks, SSE event streaming, and WebSocket support for live updates.
- **Multi-tenant** — Full tenant isolation with per-tenant rate limiting, API keys, and audit logs.
- **RBAC** — Role-based access control (admin / writer / reader / agent) on every API key.
- **Schema validation** — Optional JSON Schema registry to validate packet context before acceptance.
- **Production-ready** — PostgreSQL, Redis Pub/Sub, Prometheus metrics, Grafana dashboard, Docker, health/readiness probes.

---

## Quick Start

### Install

**Python SDK:**

```bash
pip install handoffrail-sdk
```

**TypeScript SDK:**

```bash
npm install handoffrail-sdk
```

**From source:**

```bash
git clone https://github.com/MelaBuilt-AI/HandoffRail.git
cd HandoffRail/server
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8080
```

**Docker:**

```bash
docker compose up --build
```

The API runs on `http://localhost:8080`. Interactive docs at `/docs`, Redoc at `/redoc`.

### Create Your First Handoff

```bash
# 1. Create an API key
curl -X POST http://localhost:8080/api/v1/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "my-agent"}'

# 2. Create a handoff packet
curl -X POST http://localhost:8080/api/v1/packets \
  -H "X-API-Key: ***" \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {
      "source_agent": {"id": "sales-01", "name": "SalesBot", "framework": "langchain"},
      "target_agent": {"id": "billing-01", "name": "BillingBot"},
      "priority": "normal"
    },
    "context": {
      "summary": "Customer wants to upgrade to Business tier",
      "conversation_state": [
        {"role": "user", "content": "I want to upgrade"},
        {"role": "agent", "content": "Let me hand you to billing."}
      ]
    },
    "decisions": [],
    "actions": {
      "pending": [{"id": "a1", "description": "Process upgrade", "assignee": "billing-01", "priority": "high", "depends_on": []}],
      "completed": [],
      "failed": []
    },
    "dependencies": [],
    "hitl": null
  }'

# 3. Claim it from another agent
curl -X POST http://localhost:8080/api/v1/packets/{packet_id}/claim \
  -H "X-API-Key: ***" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "billing-01", "agent_name": "BillingBot"}'
```

---

## Python SDK

```python
from handoffrail.sdk import HandoffRailClient, HandoffPacket

client = HandoffRailClient(
    base_url="http://localhost:8080/api/v1",
    api_key="sk-..."
)

# Builder pattern for structured packets
packet = (
    HandoffPacket.builder()
    .from_agent("sales-01", "SalesBot", framework="langchain")
    .to_agent("billing-01", "BillingBot")
    .with_summary("Customer wants Business tier upgrade")
    .with_conversation(messages=[
        {"role": "user", "content": "I want to upgrade"},
        {"role": "agent", "content": "Let me connect you to billing"}
    ])
    .with_decision("Proceed with upgrade", rationale="Customer eligible", decided_by="sales-01")
    .with_action("Process payment", assignee="billing-01", priority="high")
    .with_dependency("stripe-api", type="api", description="Payment gateway")
    .with_hitl(reason="High-value upgrade needs approval", question="Approve upgrade?")
    .with_priority("high")
    .with_tags(["upgrade", "business-tier"])
    .build()
)

created = client.create_packet(packet)
claimed = client.claim_packet(created.id, agent_id="billing-01", agent_name="BillingBot")
client.complete_packet(claimed.id)

# Query and search
results = client.list_packets(status="created", limit=10)
awaiting = client.list_awaiting_human()
history = client.get_packet_history(created.id)
chained = client.chain_packet(created.id, target_agent={"id": "followup-01", "name": "FollowUpBot"})
```

### Async Client

```python
from handoffrail.sdk import AsyncHandoffRailClient

async with AsyncHandoffRailClient(base_url="...", api_key="sk-...") as client:
    packet = await client.create_packet(...)
    packets = await client.list_packets(status="created")
```

---

## TypeScript SDK

```typescript
import { HandoffRailClient, PacketBuilder } from 'handoffrail-sdk';

const client = new HandoffRailClient({
  baseUrl: 'http://localhost:8080/api/v1',
  apiKey: 'sk-...',
});

// Fluent builder
const packet = new PacketBuilder()
  .from('sales-01', 'SalesBot', 'langchain')
  .to('billing-01', 'BillingBot')
  .withSummary('Customer wants upgrade')
  .withPriority('high')
  .withTags(['upgrade'])
  .build();

const created = client.createPacket(packet);
const claimed = client.claimPacket(created.id, { agent_id: 'billing-01', agent_name: 'BillingBot' });
client.completePacket(claimed.id);

// WebSocket client for real-time events
import { AsyncWebSocketClient } from 'handoffrail-sdk';

const ws = new AsyncWebSocketClient({ baseUrl: 'http://localhost:8080', apiKey: 'sk-...' });
ws.onPacketCreated = (event) => console.log('New packet:', event.packet_id);
await ws.connect();
await ws.subscribe('status:created');
```

---

## Framework Integrations

### LangChain

```python
from handoffrail.sdk import HandoffRailClient
from handoffrail.integrations.langchain import LangChainAdapter, HandoffRailCallbackHandler, HandoffRailTool

client = HandoffRailClient(base_url="http://localhost:8080/api/v1", api_key="sk-...")
adapter = LangChainAdapter(client=client, agent_id="sales-01", agent_name="SalesBot")

# Create a handoff from a LangChain conversation
packet = adapter.create_handoff(
    target_agent_id="billing-01",
    target_agent_name="BillingBot",
    summary="Customer upgrade request",
    conversation_state=adapter.extract_conversation(chat_history),
)

# Resume from a handoff
packets = adapter.poll_for_handoff()
claimed = adapter.claim_handoff(packets[0].id)
messages = adapter.resume_conversation(claimed)

# Auto-capture with callback handler
handler = HandoffRailCallbackHandler(adapter=adapter, auto_handoff=True, target_agent_id="billing-01")
result = agent.run("Help the customer upgrade", callbacks=[handler])
```

### CrewAI

```python
from handoffrail.sdk import HandoffRailClient
from handoffrail.integrations.crewai import CrewAIAdapter, HandoffRailCrewAITool

client = HandoffRailClient(base_url="http://localhost:8080/api/v1", api_key="sk-...")
adapter = CrewAIAdapter(client=client, agent_id="billing-01", agent_name="BillingBot")

# Hand off after task completion
packet = adapter.handoff_from_task(
    task_result="Payment processed",
    target_agent_id="support-01",
    summary="Billing complete, customer needs onboarding",
)

# Receive and resume
packets = adapter.poll_for_handoff()
task_input = adapter.resume_conversation(packets[0])
```

### Vercel AI SDK

```typescript
import { createHandoffRailTools } from 'handoffrail-sdk/integrations/ai-sdk';

const tools = createHandoffRailTools({
  baseUrl: 'http://localhost:8080/api/v1',
  apiKey: 'sk-...',
  agentId: 'billing-01',
  agentName: 'BillingBot',
});
```

### Custom Adapter

```python
from handoffrail.integrations.base import BaseAdapter

class MyAdapter(BaseAdapter):
    def extract_conversation(self, context) -> list[dict]:
        ...

    def resume_conversation(self, packet) -> Any:
        ...

adapter = MyAdapter(client=client, agent_id="my-agent", agent_name="MyBot")
```

---

## CLI

```bash
handoffrail serve --port 8080                    # Start API server
handoffrail create -f packet.yaml                # Create from file
handoffrail create --source-id sales-01 \
  --source-name SalesBot --target-id billing-01 \
  --summary "Customer upgrade"                   # Create from args
handoffrail get <packet_id>                      # Get packet
handoffrail list --status created --limit 10     # List with filters
handoffrail claim <packet_id> \
  --agent-id billing-01 --agent-name BillingBot # Claim a packet
handoffrail respond <packet_id> \
  --response "Approved" \
  --responded-by manager@company.com             # Respond to HITL
handoffrail history <packet_id>                  # Event audit trail
handoffrail errors                                # Error reference
```

---

## API Reference

All endpoints require the `X-API-Key` header. Full interactive docs at `/docs` when the server is running.

### Packets

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/packets` | Create a handoff packet |
| `GET` | `/api/v1/packets` | List with filtering, pagination, cursor support |
| `GET` | `/api/v1/packets/{id}` | Get by ID |
| `PATCH` | `/api/v1/packets/{id}` | Update fields / status |
| `DELETE` | `/api/v1/packets/{id}` | Soft-delete (marks expired) |
| `POST` | `/api/v1/packets/{id}/claim` | Claim an unclaimed packet |
| `POST` | `/api/v1/packets/{id}/respond` | Respond to a HITL checkpoint |
| `POST` | `/api/v1/packets/{id}/chain` | Create a chained follow-up packet |
| `GET` | `/api/v1/packets/awaiting` | List packets awaiting human review |
| `GET` | `/api/v1/packets/{id}/history` | Event audit trail |
| `POST` | `/api/v1/packets/batch` | Batch create packets |
| `POST` | `/api/v1/packets/batch/claim` | Batch claim packets |
| `POST` | `/api/v1/packets/batch/complete` | Batch complete packets |
| `GET` | `/api/v1/packets/search` | Full-text search (FTS5 / tsvector) |

### Schemas

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/schemas` | Register a JSON Schema for context validation |
| `GET` | `/api/v1/schemas` | List schemas |
| `GET` | `/api/v1/schemas/{id}` | Get schema by ID |

### Webhooks

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/hooks` | Register a webhook |
| `GET` | `/api/v1/hooks` | List webhooks |
| `DELETE` | `/api/v1/hooks/{id}` | Deactivate a webhook |
| `GET` | `/api/v1/hooks/{id}/deliveries` | Delivery history with retry status |

Webhooks fire with HMAC-SHA256 signature in `X-HR-Signature` header.

### API Keys & RBAC

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/keys` | Create API key (with role assignment) |
| `GET` | `/api/v1/keys` | List keys |
| `DELETE` | `/api/v1/keys/{id}` | Revoke key |

Roles: `admin` > `writer` > `reader` > `agent` — enforced via RBAC middleware.

### Audit

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/audit` | Tenant-scoped audit log over lifecycle events |

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe |
| `GET` | `/ready` | Readiness probe (checks DB) |
| `GET` | `/metrics` | Prometheus metrics |

---

## Packet Lifecycle

```
created → claimed → in_progress → completed
                   ↘ awaiting_human → claimed → in_progress → completed
                                                        ↘ failed
                                                ↘ expired
```

| State | Description |
|-------|-------------|
| `created` | Initial state, waiting for an agent to claim |
| `claimed` | Agent has picked up the packet |
| `in_progress` | Agent is actively working |
| `awaiting_human` | Needs human review/approval (HITL checkpoint) |
| `completed` | Work is done |
| `failed` | Something went wrong |
| `expired` | Soft-deleted or timed out |

---

## Human-in-the-Loop

```python
packet = client.create_packet(
    source_agent={"id": "support-01", "name": "SupportBot"},
    target_agent={"id": "human", "name": "Account Manager"},
    summary="Customer requesting $500 refund outside policy window",
    hitl={
        "required": True,
        "reason": "Refund exceeds policy threshold",
        "question": "Should we approve the $500 refund?",
        "options": ["Approve full refund", "Approve partial", "Deny"],
        "timeout_seconds": 86400
    }
)

client.respond_to_hitl(packet.id, response="Approve full refund", responded_by="manager@company.com")
```

---

## Architecture

```
┌──────────────┐                              ┌──────────────┐
│   Agent A    │ ── Create Packet ──┐          │   Agent B    │
│  (LangChain) │                    │          │   (CrewAI)   │
└──────────────┘                    ▼          └──────────────┘
                          ┌──────────────────┐        │
                          │  HandoffRail API │        │ Claim &
                          │    (FastAPI)     │        │ Resume
                          │                  │        │
┌──────────────┐          │  ┌────────────┐  │        │
│    Human     │◄─ HITL ──│  │ PostgreSQL │  │        │
│  (Manager)   │          │  │ / SQLite   │  │        │
└──────────────┘          │  └────────────┘  │        │
                          │  ┌────────────┐  │        │
                          │  │   Redis    │  │        │
                          │  │  Pub/Sub   │  │        │
                          │  └────────────┘  │        │
                          │  ┌────────────┐  │        │
                          │  │  Webhooks  │  │        │
                          │  │  + SSE/WS  │  │        │
                          │  └────────────┘  │        │
                          └──────────────────┘        │
                                                      │
                          ┌──────────────────┐        │
                          │   SDKs           │◄───────┘
                          │  Python · TS     │
                          │  CLI · Adapters  │
                          └──────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI (Python 3.11+) |
| Database | SQLite (dev) / PostgreSQL 16 (prod) |
| ORM | SQLAlchemy 2.0 + Alembic migrations |
| Validation | Pydantic v2 |
| Auth | API Keys with RBAC (admin/writer/reader/agent) |
| Real-time | Redis Pub/Sub, SSE, WebSocket |
| Webhooks | HMAC-SHA256 signed, retry with dead-letter queue |
| Metrics | Prometheus + Grafana dashboard |
| SDKs | Python (`handoffrail-sdk`), TypeScript (`handoffrail-sdk` on npm) |
| Integrations | LangChain, CrewAI, Vercel AI SDK |
| CLI | Click |
| Logging | structlog |
| Container | Docker, GHCR |

---

## Deployment

### Tier Plans

| Feature | Free | Pro | Business |
|---------|------|-----|----------|
| Handoffs/day | 5 | Unlimited | Unlimited |
| Max agents | 2 | 10 | 50 |
| Max API keys | 1 | 5 | 25 |
| Max packet size | 64 KB | 256 KB | 1 MB |
| Rate limit (req/hr) | 100 | 1,000 | 10,000 |
| RBAC roles | reader | writer | admin |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HR_ENVIRONMENT` | `dev` | `dev`, `staging`, or `prod` |
| `HR_DATABASE_URL` | `sqlite+aiosqlite:///./handoffrail.db` | Database URL |
| `HR_REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `HR_TIER_DEFAULT` | `free` | Default tier for new API keys |
| `HR_LOG_LEVEL` | `info` | Log level |
| `HR_PORT` | `8080` | Server port |
| `HR_CORS_ORIGINS` | `["*"]` | CORS origins (JSON list) |

### Docker (Development)

```bash
docker compose up --build
```

### Docker (Production)

```bash
cp .env.example .env  # Edit with PostgreSQL + Redis credentials
docker compose -f docker-compose.prod.yml up -d
```

Production compose includes API, PostgreSQL 16, and Redis 7.

### PostgreSQL Setup

```bash
cd server
alembic upgrade head
```

### Monitoring

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness — 200 if process running |
| `GET /ready` | Readiness — 200 if DB connected, 503 if not |
| `GET /metrics` | Prometheus metrics |

**Prometheus metrics:** `handoffrail_requests_total`, `handoffrail_request_latency_seconds`, `handoffrail_active_packets`, `handoffrail_handoffs_total{tenant_id}`

**Grafana dashboard** included at `docs/grafana/dashboard.json` — import via Grafana UI.

---

## Testing

```bash
# Python tests
python3 -m pytest tests/ -v

# TypeScript tests
cd sdk-typescript && npx jest

# Lint
ruff check server/app/ tests/          # Python
npx eslint src/ --ext .ts               # TypeScript
```

**594 Python tests passing, 24 skipped** (skips require optional LangChain/CrewAI deps).
**139 TypeScript tests passing.**

---

## Project Structure

```
HandoffRail/
├── server/                 # FastAPI server
│   ├── app/
│   │   ├── main.py         # App entry
│   │   ├── models/         # Pydantic + DB models
│   │   ├── routers/        # API routes
│   │   ├── middleware/     # Auth, RBAC, rate limiting
│   │   └── database.py     # SQLAlchemy setup
│   ├── alembic/            # DB migrations
│   ├── tests/              # 594 test suite
│   ├── Dockerfile
│   └── pyproject.toml
├── sdk/                    # Python SDK (handoffrail-sdk on PyPI)
│   ├── src/handoffrail/sdk/
│   │   ├── client.py       # Sync client
│   │   ├── async_client.py # Async client
│   │   ├── models.py       # Data models
│   │   └── builders.py     # PacketBuilder
│   └── pyproject.toml
├── sdk-typescript/         # TypeScript SDK (handoffrail-sdk on npm)
│   ├── src/
│   │   ├── client.ts       # Sync client
│   │   ├── async-client.ts # Async client
│   │   ├── models.ts       # TS interfaces
│   │   ├── ws-client.ts    # WebSocket client
│   │   └── integrations/   # Vercel AI SDK
│   ├── tests/
│   └── package.json
├── docs/                   # Documentation + Grafana dashboard
├── docker-compose.yml      # Dev compose
├── docker-compose.prod.yml # Prod compose
├── .github/workflows/      # CI/CD
└── README.md
```

## License

MIT