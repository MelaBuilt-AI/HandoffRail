# Quick Start Guide

Get from zero to your first handoff in under 5 minutes.

## Prerequisites

- Python 3.11+
- pip
- (Optional) Docker + Docker Compose for containerized setup

## Option A: Local Install

### 1. Clone the Repo

```bash
git clone https://github.com/MelaBuilt-AI/handoffrail.git
cd handoffrail
```

### 2. Install the Server

```bash
cd server
pip install -e ".[dev]"
```

### 3. Start the API Server

```bash
uvicorn app.main:app --reload --port 8080
```

The API is now running at `http://localhost:8080`. Interactive docs at `http://localhost:8080/docs`.

### 4. Create an API Key

```bash
curl -X POST http://localhost:8080/api/v1/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "my-first-agent"}'
```

Copy the returned `key` value (starts with `hr_`). You'll need it for all API calls.

### 5. Create Your First Handoff

**Using the Python SDK:**

```bash
pip install handoffrail-sdk
```

```python
from handoffrail.sdk import HandoffRailClient

client = HandoffRailClient(
    base_url="http://localhost:8080/api/v1",
    api_key="hr_your_key_here"
)

# Create a handoff packet
packet = client.create_packet(
    source_agent={"id": "agent-a", "name": "Agent A", "framework": "langchain"},
    target_agent={"id": "agent-b", "name": "Agent B"},
    summary="Customer wants to upgrade to Business tier",
    priority="high",
    tags=["upgrade", "business-tier"]
)

print(f"Packet created: {packet.id}")
print(f"Status: {packet.status}")
```

**Using curl:**

```bash
curl -X POST http://localhost:8080/api/v1/packets \
  -H "X-API-Key: hr_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {
      "source_agent": {"id": "agent-a", "name": "Agent A", "framework": "langchain"},
      "target_agent": {"id": "agent-b", "name": "Agent B"},
      "priority": "high"
    },
    "context": {
      "summary": "Customer wants to upgrade",
      "conversation_state": [
        {"role": "user", "content": "I want to upgrade"},
        {"role": "agent", "content": "Let me hand you to billing."}
      ]
    },
    "decisions": [],
    "actions": {
      "pending": [{"id": "a1", "description": "Process upgrade", "assignee": "agent-b", "priority": "high", "depends_on": []}],
      "completed": [],
      "failed": []
    },
    "dependencies": [],
    "hitl": null
  }'
```

**Using the CLI:**

```bash
handoffrail create \
  --source-id agent-a \
  --source-name "Agent A" \
  --target-id agent-b \
  --summary "Customer upgrade request" \
  --priority high
```

### 6. Claim the Packet

```python
claimed = client.claim_packet(
    packet.id,
    agent_id="agent-b",
    agent_name="Agent B"
)
print(f"Claimed by: {claimed.metadata.target_agent.name}")
print(f"Status: {claimed.status}")  # "claimed"
```

### 7. Complete the Handoff

```python
completed = client.complete_packet(packet.id)
print(f"Status: {completed.status}")  # "completed"
```

🎉 **That's it!** You've created, claimed, and completed your first handoff.

## Option B: Docker

```bash
# Clone and start
git clone https://github.com/MelaBuilt-AI/handoffrail.git
cd handoffrail
docker compose up --build
```

The API runs on `http://localhost:8080`. Create an API key and proceed from step 5 above.

## Next Steps

- **[API Reference →](api-reference.md)** — All 19 endpoints with request/response examples
- **[SDK Guide →](sdk-guide.md)** — Python SDK deep dive (builder pattern, async, adapters)
- **[Deployment →](deployment.md)** — Production setup with PostgreSQL, Redis, Docker
- **[Examples →](../examples/)** — Working code for basic handoffs, chains, and HITL

## Common Issues

| Issue | Solution |
|-------|---------|
| `ModuleNotFoundError: No module named 'app'` | Make sure you're in the `server/` directory when running `uvicorn`, or install with `pip install -e ".[dev]"` |
| `401 Unauthorized` | Check your API key. Make sure it starts with `hr_` and hasn't been revoked |
| `429 Too Many Requests` | You've hit the rate limit for your tier. Free tier = 100 req/hr. Check `X-RateLimit-Remaining` header |
| Port 8080 already in use | Use `--port 8081` or any available port |
| SQLite locking errors under load | Switch to PostgreSQL for production (see [Deployment Guide](deployment.md)) |