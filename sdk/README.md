# HandoffRail SDK

Python SDK for [HandoffRail](https://github.com/MelaBuilt-AI/HandoffRail) — session-continuity middleware for multi-agent AI workflows.

## Install

```bash
pip install handoffrail-sdk
```

## Quick Start

```python
from handoffrail import Client

client = Client(base_url="http://localhost:8000", api_key="your-key")

# Create a handoff packet
packet = client.create_packet(
    source_agent="research-agent",
    target_agent="writing-agent",
    summary="Research complete on topic X",
)

# Claim and resolve
client.claim_packet(packet.id, agent_id="writing-agent")
client.resolve_packet(packet.id, outcome="Article drafted successfully")
```

## Features

- Sync and async clients
- Pydantic v2 models
- LangChain / CrewAI integrations (optional extras)
- WebSocket support for real-time updates

## License

MIT