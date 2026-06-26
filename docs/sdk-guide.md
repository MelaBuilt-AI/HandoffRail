# SDK Guide

Complete guide to the HandoffRail Python SDK — sync client, async client, builder pattern, and framework adapters.

## Installation

```bash
pip install handoffrail-sdk
```

## Sync Client

### Basic Usage

```python
from handoffrail.sdk import HandoffRailClient

# Create client
client = HandoffRailClient(
    base_url="http://localhost:8080/api/v1",
    api_key="hr_your_key_here"
)

# Use it
packet = client.create_packet(...)
client.close()

# Or as a context manager (recommended)
with HandoffRailClient(base_url="...", api_key="...") as client:
    packet = client.create_packet(...)
```

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_url` | str | required | API base URL |
| `api_key` | str | required | API key for authentication |
| `timeout` | float | 30.0 | Request timeout in seconds |
| `max_retries` | int | 3 | Max retries on transient errors |
| `retry_delay` | float | 0.5 | Base delay between retries (exponential backoff) |

### Methods

#### `create_packet(packet: PacketCreate) → PacketResponse`

Create a new handoff packet. Takes a `PacketCreate` model (see [Models](#models)).

```python
from handoffrail.sdk.models import PacketCreate, Metadata, AgentInfo, TargetAgentInfo, PacketContext, Actions

packet = client.create_packet(PacketCreate(
    metadata=Metadata(
        source_agent=AgentInfo(id="sales-01", name="SalesBot", framework="langchain"),
        target_agent=TargetAgentInfo(id="billing-01", name="BillingBot"),
        priority="high",
    ),
    context=PacketContext(summary="Customer upgrade request"),
    actions=Actions(),
))
```

#### `get_packet(packet_id: str | UUID) → PacketResponse`

Get a single packet by ID.

#### `list_packets(*, status=None, source_agent=None, target_agent=None, tags=None, priority=None, created_after=None, created_before=None, limit=50, offset=0) → PacketListResponse`

List packets with filtering and pagination. All parameters are optional keyword args.

```python
results = client.list_packets(
    status="created",
    priority="high",
    limit=10
)
for packet in results.packets:
    print(f"{packet.id}: {packet.context.summary}")
print(f"Total: {results.total}")
```

#### `claim_packet(packet_id, *, agent_id, agent_name, framework=None) → PacketResponse`

Claim an unclaimed packet.

```python
claimed = client.claim_packet(
    packet.id,
    agent_id="billing-01",
    agent_name="BillingBot",
    framework="crewai"
)
```

#### `update_packet(packet_id, update: PacketUpdate) → PacketResponse`

Partially update a packet.

```python
from handoffrail.sdk.models import PacketUpdate

updated = client.update_packet(
    packet.id,
    PacketUpdate(status="in_progress")
)
```

#### `complete_packet(packet_id) → PacketResponse`

Convenience method — sets status to `completed`.

```python
completed = client.complete_packet(packet.id)
```

#### `delete_packet(packet_id) → None`

Soft-delete (marks as `expired`).

#### `respond_to_hitl(packet_id, *, response, responded_by, notes=None) → PacketResponse`

Submit a human response to a HITL checkpoint.

```python
responded = client.respond_to_hitl(
    packet.id,
    response="Approve full refund",
    responded_by="manager@company.com"
)
```

#### `get_awaiting(*, limit=50, offset=0) → PacketListResponse`

Get packets awaiting human review.

#### `get_history(packet_id) → PacketHistoryResponse`

Get the audit trail for a packet.

```python
history = client.get_history(packet.id)
for event in history.events:
    print(f"{event.timestamp}: {event.event_type} by {event.actor}")
```

#### `chain_handoff(parent_packet_id, request: ChainHandoffRequest) → PacketResponse`

Create a chained follow-up packet. `parent_packet_id` is auto-linked.

```python
from handoffrail.sdk.models import ChainHandoffRequest, Metadata, AgentInfo, TargetAgentInfo, PacketContext

chained = client.chain_handoff(
    packet.id,
    ChainHandoffRequest(
        metadata=Metadata(
            source_agent=AgentInfo(id="billing-01", name="BillingBot"),
            target_agent=TargetAgentInfo(id="onboard-01", name="OnboardBot"),
        ),
        context=PacketContext(summary="Billing complete, start onboarding"),
    )
)
```

#### Webhook Methods

```python
# Register a webhook
webhook = client.register_webhook(
    url="https://my-app.com/webhooks/handoffrail",
    events=["packet.created", "packet.completed"],
    secret="whsec_my_secret_min_16_chars"
)

# List webhooks
webhooks = client.list_webhooks()

# Deactivate
client.delete_webhook(webhook.id)
```

---

## Async Client

For async applications, use `AsyncHandoffRailClient`:

```python
from handoffrail.sdk import AsyncHandoffRailClient

async def main():
    async with AsyncHandoffRailClient(base_url="...", api_key="...") as client:
        # Same methods as sync client, but await them
        packet = await client.create_packet(...)
        packets = await client.list_packets(status="created")
        claimed = await client.claim_packet(packet.id, agent_id="billing-01", agent_name="BillingBot")
        completed = await client.complete_packet(packet.id)
```

All methods on the async client are coroutines with identical signatures to the sync client.

---

## Builder Pattern

For complex packets, use the fluent builder:

```python
from handoffrail.sdk import HandoffPacket

packet = (
    HandoffPacket.builder()
    .from_agent("sales-01", "SalesBot", framework="langchain")
    .to_agent("billing-01", "BillingBot")
    .with_summary("Customer wants Business tier upgrade")
    .with_conversation(messages=[
        {"role": "user", "content": "I want to upgrade"},
        {"role": "agent", "content": "Let me connect you to billing"},
    ])
    .with_decision(
        "Proceed with upgrade",
        rationale="Customer eligible, no outstanding invoices",
        decided_by="sales-01"
    )
    .with_action(
        "Process payment",
        assignee="billing-01",
        priority="high"
    )
    .with_dependency(
        "stripe-api",
        type="api",
        description="Payment gateway"
    )
    .with_hitl(
        reason="High-value upgrade needs approval",
        question="Approve Business tier upgrade?",
        options=["Approve", "Deny"],
        timeout_seconds=86400
    )
    .with_priority("high")
    .with_tags(["upgrade", "business-tier"])
    .build()
)

# Submit to API
response = client.create_packet(packet)
```

### Builder Methods

| Method | Description |
|--------|-------------|
| `.from_agent(id, name, framework=None)` | Set source agent |
| `.to_agent(id, name, framework=None)` | Set target agent |
| `.with_summary(text)` | Set context summary |
| `.with_conversation(messages)` | Add conversation turns |
| `.with_artifact(key, value, content_type=None)` | Add named artifact |
| `.with_decision(decision, rationale, alternatives=None, decided_by=None)` | Add a decision |
| `.with_action(description, assignee, priority=None, depends_on=None)` | Add pending action |
| `.with_dependency(id, type, description, status=None, source=None)` | Add dependency |
| `.with_hitl(reason, question=None, options=None, timeout_seconds=None)` | Set HITL checkpoint |
| `.with_priority(level)` | Set priority (`low`/`normal`/`high`/`critical`) |
| `.with_tags(tags)` | Set tags |
| `.build()` | Build the PacketCreate model |

---

## Models

All models use Pydantic v2 and provide `from_dict()` / `to_dict()` helpers.

### Core Models

| Model | Description |
|-------|-------------|
| `PacketCreate` | Request body for creating a packet |
| `PacketResponse` | Full packet response from the API |
| `PacketListResponse` | Paginated list of packets |
| `PacketUpdate` | Partial update request |
| `PacketClaim` | Claim request body |
| `ChainHandoffRequest` | Chain handoff request body |
| `HitlRespondRequest` | HITL response request body |
| `PacketEvent` | Single event in packet history |
| `PacketHistoryResponse` | Packet event history response |
| `WebhookCreate` | Webhook registration request |
| `WebhookResponse` | Webhook response |

### Nested Models

| Model | Description |
|-------|-------------|
| `AgentInfo` | Source agent identity |
| `TargetAgentInfo` | Target agent identity |
| `Metadata` | Packet metadata (agents, timestamps, priority, tags) |
| `PacketContext` | Context section (summary, conversation, artifacts, custom) |
| `ContextEntry` | Conversation turn (role, content, timestamp) |
| `Artifact` | Named artifact (key, value, content_type) |
| `Decision` | Decision record |
| `PendingAction` | Pending action |
| `CompletedAction` | Completed action |
| `FailedAction` | Failed action |
| `Actions` | Container for pending/completed/failed |
| `Dependency` | External dependency |
| `HitlCheckpoint` | HITL checkpoint |

### Enums

| Enum | Values |
|------|--------|
| `Priority` | `low`, `normal`, `high`, `critical` |
| `PacketStatus` | `created`, `claimed`, `in_progress`, `awaiting_human`, `completed`, `failed`, `expired` |
| `ConversationRole` | `user`, `agent`, `system`, `human` |
| `DependencyType` | `data`, `api`, `human_approval`, `external_event`, `resource` |
| `DependencyStatus` | `blocked`, `available`, `unknown` |

---

## Error Handling

The SDK maps HTTP errors to typed exceptions:

```python
from handoffrail.sdk.exceptions import (
    HandoffRailError,       # Base exception
    AuthenticationError,   # 401
    NotFoundError,         # 404, 410
    ValidationError,       # 400, 409
    RateLimitError,       # 429
    ServerError,           # 5xx
    ConnectionError,       # Network / timeout
)
```

```python
from handoffrail.sdk.exceptions import RateLimitError

try:
    packet = client.create_packet(...)
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after} seconds")
except ValidationError as e:
    print(f"Validation failed: {e.message}")
    print(f"Field: {e.field}")
```

All exceptions include:
- `message` — Human-readable error description
- `status_code` — HTTP status code (where applicable)
- `response_body` — Full API error response (where applicable)
- `field` — Failed field name (for `ValidationError`)

---

## Framework Adapters

### LangChain Adapter

```python
from handoffrail.sdk import HandoffRailClient
from handoffrail.integrations.langchain import LangChainAdapter, HandoffRailCallbackHandler, HandoffRailTool

client = HandoffRailClient(base_url="...", api_key="...")
adapter = LangChainAdapter(client=client, agent_id="sales-01", agent_name="SalesBot")
```

**Creating a handoff from LangChain:**

```python
packet = adapter.create_handoff(
    target_agent_id="billing-01",
    target_agent_name="BillingBot",
    summary="Customer upgrade request",
    conversation_state=adapter.extract_conversation(chat_history),
)
```

**Receiving a handoff:**

```python
packets = adapter.poll_for_handoff()
claimed = adapter.claim_handoff(packets[0].id)
messages = adapter.resume_conversation(claimed)
```

**Callback handler (auto-captures conversation):**

```python
handler = HandoffRailCallbackHandler(
    adapter=adapter,
    auto_handoff=True,
    target_agent_id="billing-01"
)
result = agent.run("Help the customer upgrade", callbacks=[handler])
```

**LangChain Tool (for agent tool use):**

```python
tool = HandoffRailTool(client=client)
agent = initialize_agent([tool], llm, agent=AgentType.ZERO_SHOT_REACT)
```

### CrewAI Adapter

```python
from handoffrail.integrations.crewai import CrewAIAdapter, HandoffRailCrewAITool

adapter = CrewAIAdapter(client=client, agent_id="billing-01", agent_name="BillingBot")
```

**Creating a handoff from a task:**

```python
packet = adapter.handoff_from_task(
    task_result="Payment processed",
    target_agent_id="support-01",
    summary="Billing complete, customer needs onboarding",
)
```

**Receiving a handoff:**

```python
packets = adapter.poll_for_handoff()
task_input = adapter.resume_conversation(packets[0])
```

### Custom Adapter

Extend `BaseAdapter` for any framework:

```python
from handoffrail.integrations.base import BaseAdapter

class MyAdapter(BaseAdapter):
    def extract_conversation(self, context) -> list[dict]:
        """Extract conversation turns from your framework's context."""
        return [{"role": "user", "content": msg.text} for msg in context.messages]

    def resume_conversation(self, packet) -> Any:
        """Convert a handoff packet to your framework's input format."""
        return [msg.to_dict() for msg in packet.context.conversation_state]
```