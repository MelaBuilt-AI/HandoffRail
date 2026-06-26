# HandoffRail

[![Tests](https://img.shields.io/badge/tests-430%20passing-brightgreen)](https://github.com/MelaBuilt-AI/HandoffRail) [![PyPI](https://img.shields.io/pypi/v/handoffrail-sdk)](https://pypi.org/project/handoffrail-sdk/) [![Python](https://img.shields.io/badge/python-3.11+-blue)](https://python.org) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/MelaBuilt-AI/HandoffRail/blob/main/LICENSE) [![Docker](https://img.shields.io/badge/docker-GHCR-2496ED)](https://github.com/MelaBuilt-AI/HandoffRail/pkgs/container/handoffrail) [![Docs](https://img.shields.io/badge/docs-handoffrail.melabuilt.ai-6c5ce7)](https://handoffrail.melabuilt.ai/docs/)

> **Zero Context Loss Between AI Agents**
>
> Session-continuity middleware for multi-agent AI workflows

When Agent A finishes its part and hands off to Agent B (or a human), the full context — decisions, pending actions, dependencies, conversation state — survives the transition intact. **No context loss, no repetition, no dropped threads.**

**430 tests passing · 24 skipped · 19 API endpoints · Python SDK + CLI · LangChain & CrewAI adapters**

## Quick Start

### Prerequisites

- Python 3.11+
- pip

### Install from PyPI

```bash
pip install handoffrail-sdk
```

### Install & Run from Source

```bash
# Clone the repo
git clone https://github.com/MelaBuilt-AI/HandoffRail.git
cd handoffrail

# Install server with dev dependencies
cd server
pip install -e ".[dev]"

# Run the API server (dev mode with auto-reload)
uvicorn app.main:app --reload --port 8080
```

The API will be available at `http://localhost:8080`. Interactive OpenAPI docs at `http://localhost:8080/docs`.

### Docker

```bash
# From the repo root
docker compose up --build
```

### Create Your First Handoff

```bash
# 1. Create an API key
curl -X POST http://localhost:8080/api/v1/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "my-agent"}'

# 2. Create a handoff packet
curl -X POST http://localhost:8080/api/v1/packets \
  -H "X-API-Key: hr_your_key_here" \
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

# 3. Claim the packet from another agent
curl -X POST http://localhost:8080/api/v1/packets/{packet_id}/claim \
  -H "X-API-Key: hr_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "billing-01", "agent_name": "BillingBot"}'
```

## API Reference

All endpoints require the `X-API-Key` header. Full interactive docs available at `/docs` when the server is running.

### Packet Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/packets` | Create a new handoff packet |
| `GET` | `/api/v1/packets` | List packets with filtering & pagination |
| `GET` | `/api/v1/packets/{id}` | Get a single packet by ID |
| `PATCH` | `/api/v1/packets/{id}` | Update packet fields / status |
| `DELETE` | `/api/v1/packets/{id}` | Soft-delete packet (marks expired) |
| `POST` | `/api/v1/packets/{id}/claim` | Claim an unclaimed packet |
| `POST` | `/api/v1/packets/{id}/respond` | Respond to a HITL checkpoint |
| `POST` | `/api/v1/packets/{id}/chain` | Create a chained follow-up packet |
| `GET` | `/api/v1/packets/awaiting` | List packets awaiting human review |
| `GET` | `/api/v1/packets/{id}/history` | Get packet event audit trail |

#### Query Parameters (GET /packets)

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by status (comma-separated) |
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

### Webhook Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/hooks` | Register a webhook |
| `GET` | `/api/v1/hooks` | List webhooks for tenant |
| `DELETE` | `/api/v1/hooks/{id}` | Deactivate a webhook |

Webhooks fire with HMAC-SHA256 signature in `X-HR-Signature` header for verification.

### API Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/keys` | Create a new API key |
| `GET` | `/api/v1/keys` | List keys for tenant |
| `DELETE` | `/api/v1/keys/{id}` | Revoke an API key |

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe |
| `GET` | `/ready` | Readiness probe (checks DB) |
| `GET` | `/metrics` | Prometheus metrics |

## Packet Lifecycle

```
created → claimed → in_progress → completed
                   ↘ awaiting_human → claimed → in_progress → completed
                                                        ↘ failed
                                                ↘ expired
```

- **created** — Initial state, waiting for an agent to claim
- **claimed** — Agent has picked up the packet
- **in_progress** — Agent is actively working
- **awaiting_human** — Needs human review/approval (HITL checkpoint)
- **completed** — Work is done
- **failed** — Something went wrong
- **expired** — Soft-deleted or timed out

## Human-in-the-Loop (HITL)

HandoffRail supports human checkpoints in agent workflows:

```python
# Create a packet requiring human approval
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

# Human responds via API or CLI
client.respond_to_hitl(packet.id, response="Approve full refund", responded_by="manager@company.com")
```

## Python SDK

### Install

```bash
pip install handoffrail-sdk
```

### Basic Usage

```python
from handoffrail.sdk import HandoffRailClient

client = HandoffRailClient(
    base_url="http://localhost:8080/api/v1",
    api_key="hr_your_key_here"
)

# Create a packet
packet = client.create_packet(
    source_agent={"id": "sales-01", "name": "SalesBot", "framework": "langchain"},
    target_agent={"id": "billing-01", "name": "BillingBot"},
    summary="Customer wants to upgrade",
    priority="high",
    tags=["upgrade"]
)

# Claim a packet
claimed = client.claim_packet(packet.id, agent_id="billing-01", agent_name="BillingBot")

# Update progress
updated = client.update_packet(packet.id, status="in_progress")

# Complete
completed = client.complete_packet(packet.id)

# Query packets
results = client.list_packets(status="created", limit=10)

# Get packets awaiting human review
awaiting = client.list_awaiting_human()

# Get packet history
history = client.get_packet_history(packet.id)

# Chain: create follow-up packet
chained = client.chain_packet(packet.id, target_agent={"id": "followup-01", "name": "FollowUpBot"})
```

### Builder Pattern

```python
from handoffrail.sdk import HandoffPacket

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
```

### Async Client

```python
from handoffrail.sdk import AsyncHandoffRailClient

async def main():
    async with AsyncHandoffRailClient(base_url="...", api_key="...") as client:
        packet = await client.create_packet(...)
        packets = await client.list_packets(status="created")
```

## Framework Integrations

### LangChain

```python
from handoffrail.sdk import HandoffRailClient
from handoffrail.integrations.langchain import LangChainAdapter, HandoffRailCallbackHandler, HandoffRailTool

client = HandoffRailClient(base_url="http://localhost:8080/api/v1", api_key="hr_...")
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

# Callback handler (auto-captures conversation)
handler = HandoffRailCallbackHandler(adapter=adapter, auto_handoff=True, target_agent_id="billing-01")
result = agent.run("Help the customer upgrade", callbacks=[handler])

# LangChain Tool (for agent tool use)
tool = HandoffRailTool(client=client)
agent = initialize_agent([tool], llm, agent=AgentType.ZERO_SHOT_REACT)
```

### CrewAI

```python
from handoffrail.sdk import HandoffRailClient
from handoffrail.integrations.crewai import CrewAIAdapter, HandoffRailCrewAITool

client = HandoffRailClient(base_url="http://localhost:8080/api/v1", api_key="hr_...")
adapter = CrewAIAdapter(client=client, agent_id="billing-01", agent_name="BillingBot")

# Create a handoff from a task completion
packet = adapter.handoff_from_task(
    task_result="Payment processed",
    target_agent_id="support-01",
    summary="Billing complete, customer needs onboarding",
)

# Receive a handoff and convert to task input
packets = adapter.poll_for_handoff()
task_input = adapter.resume_conversation(packets[0])

# CrewAI Tool
tool = HandoffRailCrewAITool(client=client)
```

### Custom Adapter

```python
from handoffrail.integrations.base import BaseAdapter

class MyAdapter(BaseAdapter):
    def extract_conversation(self, context) -> list[dict]:
        # Custom logic to extract conversation from your framework
        ...

    def resume_conversation(self, packet) -> Any:
        # Custom logic to convert packet to framework input
        ...

adapter = MyAdapter(client=client, agent_id="my-agent", agent_name="MyBot")
```

## CLI

```bash
# Start the API server
handoffrail serve --port 8080

# Create a packet (from file or CLI args)
handoffrail create -f packet.yaml
handoffrail create --source-id sales-01 --source-name SalesBot --target-id billing-01 --summary "Customer upgrade"

# Get a packet
handoffrail get <packet_id>

# List packets with filters
handoffrail list --status created --priority high --limit 10

# Claim a packet
handoffrail claim <packet_id> --agent-id billing-01 --agent-name BillingBot

# Respond to a HITL checkpoint
handoffrail respond <packet_id> --response "Approved" --responded-by manager@company.com

# View event history
handoffrail history <packet_id>

# Error reference
handoffrail errors
```

## Running Tests

```bash
cd handoffrail
python3 -m pytest tests/ -v

# Run specific test modules
python3 -m pytest tests/test_packets.py -v        # Core packet CRUD
python3 -m pytest tests/test_lifecycle.py -v      # Full lifecycle tests
python3 -m pytest tests/test_cli.py -v             # CLI commands
python3 -m pytest tests/test_sdk_client.py -v      # SDK sync client
python3 -m pytest tests/test_sdk_async_client.py -v # SDK async client
python3 -m pytest tests/test_langchain_integration.py -v  # LangChain adapter
python3 -m pytest tests/test_crewai_integration.py -v     # CrewAI adapter
```

**430 tests passing, 24 skipped** (skipped tests require optional LangChain/CrewAI dependencies).

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
│    Human     │          │  │  Packet DB │  │        │
│  (Manager)   │◄─ HITL ──│  │  SQLite/PG │  │        │
└──────────────┘          │  └────────────┘  │        │
                          │  ┌────────────┐  │        │
                          │  │  Webhooks  │  │        │
                          │  │  + Events  │  │        │
                          │  └────────────┘  │        │
                          └──────────────────┘        │
                                                      │
                          ┌──────────────────┐        │
                          │   Python SDK     │◄───────┘
                          │  ┌─────────────┐ │
                          │  │  Client +   │ │
                          │  │  Builders   │ │
                          │  └─────────────┘ │
                          │  ┌─────────────┐ │
                          │  │ Adapters:   │ │
                          │  │ LangChain   │ │
                          │  │ CrewAI      │ │
                          │  │ BaseAdapter │ │
                          │  └─────────────┘ │
                          └──────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Framework | FastAPI |
| Database | SQLite (dev) / PostgreSQL (prod) |
| ORM | SQLAlchemy 2.0 + Alembic |
| Validation | Pydantic v2 |
| Auth | API Keys (tier-based: free / pro / business) |
| Webhooks | HMAC-SHA256 signed |
| Testing | pytest + httpx |
| CLI | Click |
| Logging | structlog |

## Project Status

| Week | Focus | Status |
|------|-------|--------|
| 1 | Foundation, models, POST/GET | ✅ |
| 2 | Claim, state machine, PATCH, DELETE, HITL, auth | ✅ |
| 3 | Query + History, filtering, pagination, webhooks | ✅ |
| 4 | Python SDK core (client, models, builders, async) | ✅ |
| 5 | Framework integrations (LangChain, CrewAI, BaseAdapter) | ✅ |
| 6 | CLI + Polish | ✅ |
| 7 | Deployment + Auth tiers | ✅ |
| 8 | Landing page + Launch | ✅ |

## Deployment

### Tier Plans

| Feature | Free | Pro | Business |
|---------|------|-----|----------|
| Handoffs/day | 5 | Unlimited | Unlimited |
| Max agents | 2 | 10 | 50 |
| Max API keys | 1 | 5 | 25 |
| Max packet size | 64KB | 256KB | 1MB |
| Rate limit (req/hr) | 100 | 1,000 | 10,000 |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HR_ENVIRONMENT` | `dev` | `dev`, `staging`, or `prod` |
| `HR_DATABASE_URL` | `sqlite+aiosqlite:///./handoffrail.db` | Database connection URL |
| `HR_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `HR_TIER_DEFAULT` | `free` | Default tier for new API keys |
| `HR_LOG_LEVEL` | `info` | Log level (debug/info/warning/error) |
| `HR_PORT` | `8080` | Server port |
| `HR_CORS_ORIGINS` | `*["*"]` | CORS allowed origins (JSON list) |

### Docker (Development)

```bash
docker compose up --build
```

### Docker (Production)

```bash
# Set required environment variables
cp .env.example .env
# Edit .env with your PostgreSQL credentials

docker compose -f docker-compose.prod.yml up -d
```

Production compose includes:
- **API** server (HandoffRail FastAPI)
- **PostgreSQL 16** (persistent storage)
- **Redis 7** (future: Celery task queue)

### PostgreSQL Setup

The server auto-detects PostgreSQL from the `DATABASE_URL`:
- `postgresql://user:pass@host/db` → automatically uses `asyncpg` driver
- `postgres://user:pass@host/db` → shorthand also supported
- If omitted → falls back to SQLite for dev

Run Alembic migrations for PostgreSQL:

```bash
cd server
alembic upgrade head
```

### Health & Monitoring

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness probe — returns 200 if process is running |
| `GET /ready` | Readiness probe — returns 200 if DB is connected, 503 if not |
| `GET /metrics` | Prometheus metrics (request count, latency, active packets, handoffs per tenant) |

### Prometheus Metrics

Exposed at `/metrics` in standard Prometheus format:
- `handoffrail_requests_total{method,endpoint,status_code}` — request counter
- `handoffrail_request_latency_seconds{method,endpoint}` — request latency histogram
- `handoffrail_active_packets` — gauge of non-terminal packets
- `handoffrail_handoffs_total{tenant_id}` — handoffs per tenant

## License

MIT
