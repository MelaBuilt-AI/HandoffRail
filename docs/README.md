# HandoffRail

> Session-continuity middleware for multi-agent AI workflows

[![Tests](https://img.shields.io/badge/tests-430%20passing-brightgreen)](https://github.com/MelaBuilt-AI/HandoffRail) [![Python](https://img.shields.io/badge/python-3.11+-blue)](https://python.org) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Docker](https://img.shields.io/badge/docker-ready-2496ED)](https://hub.docker.com)

When Agent A finishes its part and hands off to Agent B (or a human), the full context — decisions, pending actions, dependencies, conversation state — survives the transition intact. **No context loss, no repetition, no dropped threads.**

## Why HandoffRail?

Multi-agent AI workflows have a missing layer: **session continuity**. When agents hand off work, context gets lost. Decisions made by Agent A aren't visible to Agent B. Conversations start over. Humans are left out of the loop.

HandoffRail fixes this with **structured handoff packets** — validated JSON payloads that carry everything the next agent (or human) needs to pick up exactly where the last one left off.

**Pick up exactly where the last agent left off.**

## Quick Start

```bash
# Clone & install
git clone https://github.com/MelaBuilt-AI/HandoffRail.git
cd handoffrail/server && pip install -e ".[dev]"

# Start the API
uvicorn app.main:app --reload --port 8080

# Create your first handoff (Python SDK)
```

```python
from handoffrail.sdk import HandoffRailClient

client = HandoffRailClient(base_url="http://localhost:8080/api/v1", api_key="hr_...")
packet = client.create_packet(
    source_agent={"id": "sales-01", "name": "SalesBot", "framework": "langchain"},
    target_agent={"id": "billing-01", "name": "BillingBot"},
    summary="Customer wants to upgrade to Business tier",
    priority="high",
)
```

→ **[Full Quick Start Guide →](docs/quickstart.md)**

## Key Features

| Feature | Description |
|---------|-------------|
| **Structured Packets** | Validated JSON schema with decisions, conversation, actions, dependencies, artifacts |
| **Human-in-the-Loop** | Built-in HITL checkpoints with approval workflows and timeouts |
| **Chain Handoffs** | Link packets into multi-agent workflows with full audit trails |
| **Webhooks** | HMAC-SHA256 signed event notifications |
| **Python SDK** | Sync + async clients, fluent builder, LangChain & CrewAI adapters |
| **CLI** | 7 commands — create, get, list, claim, respond, history, serve |
| **Docker** | One-command dev setup, PostgreSQL + Redis production config |
| **Auth + Rate Limiting** | API keys with tier-based quotas (Free / Pro / Business) |
| **Observability** | Prometheus metrics, structlog, health probes, event history |

## Architecture

```
Agent A (LangChain) → Create Packet → HandoffRail API → Claim → Agent B (CrewAI)
                                       ↓
                                   HITL Check
                                       ↓
                                   Human Manager
                                       ↓
                                   Chain → Agent C
```

HandoffRail sits between your agents as structured middleware. It doesn't orchestrate — it **preserves context** across transitions.

→ **[Full Architecture Docs →](docs/deployment.md)**

## Documentation

| Doc | Description |
|-----|-------------|
| [Quick Start](docs/quickstart.md) | 5-minute setup to your first handoff |
| [API Reference](docs/api-reference.md) | All 19 endpoints with examples |
| [SDK Guide](docs/sdk-guide.md) | Python SDK, builder pattern, async client |
| [Deployment](deployment.md) | Docker Compose, PostgreSQL, Redis, TLS, monitoring, backups, scaling |

## Framework Integrations

### LangChain

```python
from handoffrail.integrations.langchain import LangChainAdapter, HandoffRailTool

adapter = LangChainAdapter(client=client, agent_id="sales-01", agent_name="SalesBot")
packet = adapter.create_handoff(target_agent_id="billing-01", ...)
messages = adapter.resume_conversation(claimed_packet)
```

### CrewAI

```python
from handoffrail.integrations.crewai import CrewAIAdapter

adapter = CrewAIAdapter(client=client, agent_id="billing-01", agent_name="BillingBot")
packet = adapter.handoff_from_task(task_result, target_agent_id="support-01", ...)
task_input = adapter.resume_conversation(packet)
```

### Custom Adapter

```python
from handoffrail.integrations.base import BaseAdapter

class MyAdapter(BaseAdapter):
    def extract_conversation(self, context) -> list[dict]: ...
    def resume_conversation(self, packet) -> Any: ...
```

## Packet Lifecycle

```
created → claimed → in_progress → completed
               ↘ awaiting_human → claimed → in_progress → completed
                                                        ↘ failed
                                                ↘ expired
```

Each status transition is validated, logged, and queryable via the event history API.

## Pricing

| Feature | Free | Pro ($29/mo) | Business ($99/mo) |
|---------|------|-------------|-------------------|
| Handoffs/day | 5 | Unlimited | Unlimited |
| Agents | 2 | 10 | 50 |
| API Keys | 1 | 5 | 25 |
| Packet Size | 64 KB | 256 KB | 1 MB |
| Rate Limit | 100/hr | 1,000/hr | 10,000/hr |
| Webhooks | — | 5 | Unlimited |
| Audit Trail | — | 30 days | Full + export |

Self-host is always free. Cloud tiers add managed infrastructure and higher limits.

## Examples

| Example | Description |
|---------|-------------|
| [`basic_handoff.py`](examples/basic_handoff.py) | Simple two-agent handoff |
| [`chain_handoff.py`](examples/chain_handoff.py) | Multi-agent chain with HITL approval |

## Running Tests

```bash
python3 -m pytest tests/ -v
# 430 tests passing, 24 skipped (optional LangChain/CrewAI deps)
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Framework | FastAPI |
| Database | SQLite (dev) / PostgreSQL 16 (prod) |
| ORM | SQLAlchemy 2.0 + Alembic |
| Validation | Pydantic v2 |
| Auth | API Keys (tier-based) |
| Webhooks | HMAC-SHA256 signed |
| CLI | Click |
| Testing | pytest + httpx |
| Logging | structlog |
| Monitoring | Prometheus + health probes |

## License

MIT © 2026 MelaBuilt AI