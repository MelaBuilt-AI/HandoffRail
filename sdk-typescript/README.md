# HandoffRail TypeScript SDK

[![npm version](https://img.shields.io/npm/v/handoffrail-sdk.svg)](https://www.npmjs.com/package/handoffrail-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Session-continuity middleware for multi-agent AI workflows.**

HandoffRail provides a structured way to pass context, decisions, and pending
actions between AI agents — or between agents and human reviewers.

This is the **TypeScript/JavaScript SDK**, which mirrors the [Python SDK](https://github.com/mela-ai/handoffrail-sdk-python).
Both share the same API surface and the same HTTP API contract.

---

## Installation

```bash
npm install handoffrail-sdk
```

For Vercel AI SDK integration:

```bash
npm install handoffrail-sdk ai
```

## Quickstart

### 1. Create a handoff packet

```typescript
import { HandoffRailClient, PacketBuilder } from 'handoffrail-sdk';

const client = new HandoffRailClient({
  baseUrl: 'http://localhost:8080/api/v1',
  apiKey: process.env.HANDOFFRAIL_API_KEY,
});

const packet = client.createPacket(
  new PacketBuilder()
    .to('billing-01', 'BillingBot', { framework: 'langchain' })
    .from('sales-01', 'SalesBot', { framework: 'custom' })
    .withSummary('Customer wants to upgrade to Business tier')
    .withPriority('high')
    .withTags(['upgrade', 'business'])
    .withConversation([
      { role: 'user', content: 'I want to upgrade my plan' },
      { role: 'agent', content: "I'd be happy to help you with that!" },
    ])
    .withDecision('Proceed with upgrade', {
      rationale: 'Customer meets all eligibility criteria',
    })
    .withAction({
      description: 'Process payment of $199/mo',
      assignee: 'billing-01',
      priority: 'high',
    })
    .build(),
);

console.log(`Created packet: ${packet.id}`);
```

### 2. Claim and complete a packet (receiving agent)

```typescript
import { HandoffRailClient } from 'handoffrail-sdk';

const client = new HandoffRailClient({
  baseUrl: 'http://localhost:8080/api/v1',
  apiKey: process.env.HANDOFFRAIL_API_KEY,
});

// Claim an available packet
const claimed = client.claimPacket(packet.id, {
  agent_id: 'billing-01',
  agent_name: 'BillingBot',
  framework: 'langchain',
});

console.log(`Claimed: ${claimed.id}`);
console.log(`Context: ${claimed.context.summary}`);
console.log(`Decisions: ${JSON.stringify(claimed.decisions)}`);

// Process the handoff and mark as complete
client.completePacket(packet.id);
```

### 3. Async usage

```typescript
import { AsyncHandoffRailClient, PacketBuilder } from 'handoffrail-sdk';

const client = new AsyncHandoffRailClient({
  baseUrl: 'http://localhost:8080/api/v1',
  apiKey: process.env.HANDOFFRAIL_API_KEY,
});

const packet = await client.createPacket(
  new PacketBuilder()
    .to('billing-01', 'BillingBot')
    .from('sales-01', 'SalesBot')
    .withSummary('Customer upgrade request')
    .build(),
);
```

---

## WebSocket Client (Real-Time Events)

The SDK includes an `AsyncWebSocketClient` for real-time event streaming from HandoffRail's `/ws` endpoint.

### Installation

For Node.js, install the `ws` package:

```bash
npm install handoffrail-sdk ws
```

In the browser, the native `WebSocket` API is used — no extra dependencies needed.

### Quickstart

```typescript
import { AsyncWebSocketClient } from 'handoffrail-sdk';

const client = new AsyncWebSocketClient({
  baseUrl: 'http://localhost:8080',
  apiKey: process.env.HANDOFFRAIL_API_KEY,
});

// Register event handlers
client.onPacketCreated = (event) => {
  console.log(`New packet: ${event.packet_id}`);
};

client.onPacketCompleted = (event) => {
  console.log(`Packet completed: ${event.packet_id}`);
};

// Connect and subscribe to channels
await client.connect();
await client.subscribe('status:created');
await client.subscribe('status:completed');

// ... listen for events ...

// Disconnect when done
await client.close();
```

### Node.js Usage

In Node.js, provide a WebSocket factory using the `ws` package:

```typescript
import WebSocket from 'ws';
import { AsyncWebSocketClient } from 'handoffrail-sdk';

const client = new AsyncWebSocketClient({
  baseUrl: 'http://localhost:8080',
  apiKey: process.env.HANDOFFRAIL_API_KEY,
  webSocketFactory: (url) => new WebSocket(url),
});
```

### Configuration

```typescript
const client = new AsyncWebSocketClient({
  baseUrl: 'http://localhost:8080',        // HTTP base URL (ws:// derived automatically)
  apiKey: 'sk-...',                         // API key for authentication
  reconnect: true,                          // Auto-reconnect on disconnect (default: true)
  reconnectDelay: 1000,                     // Initial reconnect delay in ms (default: 1000)
  maxReconnectDelay: 30000,                 // Max reconnect delay in ms (default: 30000)
  reconnectMultiplier: 2.0,                 // Exponential backoff multiplier (default: 2.0)
  webSocketFactory: (url) => new WebSocket(url), // Custom WebSocket factory
});
```

### Event Types

| Event Constant | Value | Description |
|---------------|-------|-------------|
| `EVENT_PACKET_CREATED` | `packet.created` | A new handoff packet was created |
| `EVENT_PACKET_CLAIMED` | `packet.claimed` | A packet was claimed by an agent |
| `EVENT_PACKET_UPDATED` | `packet.updated` | A packet was updated |
| `EVENT_PACKET_IN_PROGRESS` | `packet.in_progress` | A packet moved to in-progress |
| `EVENT_PACKET_AWAITING_HUMAN` | `packet.awaiting_human` | A packet is awaiting human input |
| `EVENT_PACKET_COMPLETED` | `packet.completed` | A packet was completed |
| `EVENT_PACKET_FAILED` | `packet.failed` | A packet failed |
| `EVENT_PACKET_EXPIRED` | `packet.expired` | A packet expired |
| `EVENT_PACKET_CHAINED` | `packet.chained` | A chained follow-up packet was created |
| `EVENT_HITL_RESPONSE_READY` | `hitl.response_ready` | A HITL response is ready |

### Event Object

```typescript
interface HandoffRailEvent {
  event_type: string;                    // e.g. "packet.created"
  packet_id: string;                     // The packet ID
  timestamp: string;                     // ISO-8601 timestamp
  data: Record<string, unknown>;         // Full event payload
}
```

### Callbacks

| Callback | Signature | Description |
|----------|-----------|-------------|
| `onPacketCreated` | `(event: HandoffRailEvent) => void` | Fired on packet creation |
| `onPacketClaimed` | `(event: HandoffRailEvent) => void` | Fired on packet claim |
| `onPacketUpdated` | `(event: HandoffRailEvent) => void` | Fired on packet update |
| `onPacketInProgress` | `(event: HandoffRailEvent) => void` | Fired on in-progress |
| `onPacketAwaitingHuman` | `(event: HandoffRailEvent) => void` | Fired on awaiting human |
| `onPacketCompleted` | `(event: HandoffRailEvent) => void` | Fired on completion |
| `onPacketFailed` | `(event: HandoffRailEvent) => void` | Fired on failure |
| `onPacketExpired` | `(event: HandoffRailEvent) => void` | Fired on expiry |
| `onPacketChained` | `(event: HandoffRailEvent) => void` | Fired on chain creation |
| `onHitlResponseReady` | `(event: HandoffRailEvent) => void` | Fired on HITL response |
| `onEvent` | `(event: HandoffRailEvent) => void` | Generic — fires for all events |
| `onConnected` | `() => void` | Fired on connection established |
| `onDisconnected` | `() => void` | Fired on disconnection |
| `onError` | `(error: Error) => void` | Fired on WebSocket error |

### Channel Subscriptions

```typescript
// Subscribe to events by status
await client.subscribe('status:created');
await client.subscribe('status:completed');

// Subscribe to events for a specific packet
await client.subscribe('packet:550e8400-e29b-41d4-a716-446655440000');

// Subscribe to events for a specific agent
await client.subscribe('agent:billing-01');

// Unsubscribe
await client.unsubscribe('status:created');

// Send a heartbeat ping
await client.ping();
```

### Auto-Reconnect

By default, the client automatically reconnects on disconnect with exponential backoff:

- Initial delay: `reconnectDelay` (default 1000ms)
- Each subsequent attempt multiplies the delay by `reconnectMultiplier` (default 2.0)
- Delay is capped at `maxReconnectDelay` (default 30000ms)
- Set `reconnect: false` to disable auto-reconnect

---

## API Reference

### Client

#### `HandoffRailClient` (sync)

```typescript
const client = new HandoffRailClient(options: {
  baseUrl: string;
  apiKey: string;
  timeout?: number;       // default: 30000
  maxRetries?: number;    // default: 3
  retryDelay?: number;    // default: 500
});
```

#### `AsyncHandoffRailClient` (async)

```typescript
const client = new AsyncHandoffRailClient(options: {
  baseUrl: string;
  apiKey: string;
  timeout?: number;       // default: 30000
  maxRetries?: number;    // default: 3
  retryDelay?: number;    // default: 500
});
```

### Methods

Both clients expose the same methods (sync client returns values directly,
async client returns Promises):

| Method | Description |
|--------|-------------|
| `createPacket(packet)` | Create a new handoff packet |
| `getPacket(packetId)` | Get a packet by ID |
| `listPackets(options?)` | List packets with filtering |
| `claimPacket(packetId, options)` | Claim a packet for processing |
| `updatePacket(packetId, update)` | Partially update a packet |
| `completePacket(packetId)` | Mark a packet as completed |
| `deletePacket(packetId)` | Soft-delete a packet |
| `respondToHitl(packetId, options)` | Respond to a HITL checkpoint |
| `listAwaitingHuman(options?)` | Get packets awaiting human review |
| `getPacketHistory(packetId)` | Get packet event history |
| `chainPacket(parentId, request)` | Create a chained follow-up packet |
| `registerWebhook(options)` | Register a new webhook |
| `listWebhooks()` | List all webhooks |
| `deleteWebhook(webhookId)` | Delete a webhook |

### Builder: `PacketBuilder`

Fluent builder for constructing `PacketCreate` payloads.

```typescript
new PacketBuilder()
  .from(agentId, agentName, { framework?, version? })
  .to(agentId, agentName, { framework? })
  .withSummary(summary)
  .withPriority('low' | 'normal' | 'high' | 'critical')
  .withTags(['tag1', 'tag2'])
  .withConversation([{ role: 'user', content: '...' }])
  .addConversationEntry('user', '...', { metadata? })
  .withDecision('decision', { rationale?, alternatives?, decided_by? })
  .withAction({ description, assignee, priority?, depends_on? })
  .withDependency({ id, type?, description?, status?, source? })
  .withHitl({ reason, question?, options?, timeout_seconds? })
  .withCustom({ key: 'value' })
  .withParent(parentPacketId)
  .build();
```

### Builder: `ChainBuilder`

Fluent builder for constructing `ChainHandoffRequest` payloads.

```typescript
new ChainBuilder()
  .from(agentId, agentName)
  .to(agentId, agentName)
  .withSummary(summary)
  .withDecision(...)
  .withAction(...)
  .withDependency(...)
  .withHitl(...)
  .build();
```

### Error Classes

All errors extend `HandoffRailError`.

| Error | HTTP Status | Description |
|-------|------------|-------------|
| `AuthenticationError` | 401 | Invalid or missing API key |
| `NotFoundError` | 404 / 410 | Resource not found |
| `ValidationError` | 400 | Request validation failure |
| `ConflictError` | 409 | Resource conflict |
| `RateLimitError` | 429 | Rate limit exceeded |
| `ServerError` | 5xx | Server-side error |
| `ConnectionError` | — | Network / timeout error |

---

## Framework Integration

### Vercel AI SDK

The SDK ships with a Vercel AI SDK adapter that exposes HandoffRail operations
as AI-callable tools.

**Install the `ai` package:**

```bash
npm install handoffrail-sdk ai
```

**Usage:**

```typescript
import { generateText } from 'ai';
import { openai } from '@ai-sdk/openai';
import { HandoffRailClient } from 'handoffrail-sdk';
import { createHandoffRailTools } from 'handoffrail-sdk/integrations/ai-sdk';

const client = new HandoffRailClient({
  baseUrl: process.env.HANDOFFRAIL_URL!,
  apiKey: process.env.HANDOFFRAIL_API_KEY!,
});

const tools = createHandoffRailTools(client, {
  agentId: 'my-agent-01',
  agentName: 'MyAgent',
  framework: 'vercel-ai-sdk',
});

const result = await generateText({
  model: openai('gpt-4o'),
  tools,
  maxSteps: 10,
  prompt: 'Check if there are any handoffs for me and process the first one.',
});
```

**Available tools:**

| Tool Name | Description |
|-----------|-------------|
| `handoffrail_create_packet` | Create a handoff to another agent |
| `handoffrail_claim_packet` | Claim an available handoff |
| `handoffrail_update_packet` | Update a handoff packet |
| `handoffrail_complete_packet` | Mark a handoff as completed |
| `handoffrail_list_packets` | List handoffs with filters |
| `handoffrail_get_packet` | Get handoff details |
| `handoffrail_respond_to_hitl` | Respond to a HITL checkpoint |
| `handoffrail_get_packet_history` | Get packet audit trail |
| `handoffrail_chain_packet` | Create a chained follow-up |

---

## Data Types

### `PacketCreate`

| Field | Type | Required |
|-------|------|----------|
| `metadata` | `Metadata` | ✓ |
| `context` | `PacketContext` | ✓ |
| `parent_packet_id` | `string` | |
| `decisions` | `Decision[]` | |
| `actions` | `Actions` | |
| `dependencies` | `Dependency[]` | |
| `hitl` | `HitlCheckpoint` | |

### `PacketResponse`

All fields from `PacketCreate`, plus:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | Packet UUID |
| `version` | `string` | Schema version |
| `status` | `PacketStatus` | Current status |
| `created_at` | `string` | ISO 8601 timestamp |
| `updated_at` | `string` | ISO 8601 timestamp |

### Enums

**`PacketStatus`:** `'created' | 'claimed' | 'in_progress' | 'awaiting_human' | 'completed' | 'failed' | 'expired'`

**`Priority`:** `'low' | 'normal' | 'high' | 'critical'`

**`ConversationRole`:** `'user' | 'agent' | 'system' | 'human'`

**`DependencyType`:** `'data' | 'api' | 'human_approval' | 'external_event' | 'resource'`

---

## Package Exports

The package provides two entry points:

```typescript
// Main SDK — client, models, builders, errors
import { HandoffRailClient, PacketBuilder } from 'handoffrail-sdk';

// Vercel AI SDK integration
import { createHandoffRailTools } from 'handoffrail-sdk/integrations/ai-sdk';
```

---

## Development

```bash
# Install dependencies
npm install

# Build
npm run build

# Run tests
npm test

# Lint
npm run lint

# Type check
npm run typecheck
```

### Project Structure

```
src/
├── index.ts            # Package entry point — re-exports all public API
├── client.ts           # HandoffRailClient (sync, using Node http/https)
├── async-client.ts     # AsyncHandoffRailClient (using fetch)
├── ws-client.ts        # AsyncWebSocketClient (real-time events)
├── models.ts           # TypeScript interfaces and serialization helpers
├── builders.ts         # PacketBuilder and ChainBuilder fluent builders
├── errors.ts           # Custom error hierarchy
└── integrations/
    └── ai-sdk.ts       # Vercel AI SDK adapter
tests/
├── client.test.ts      # Sync client tests (in-memory test server)
├── async-client.test.ts # Async client tests (mocked fetch)
├── ws-client.test.ts   # WebSocket client tests (mocked WebSocket)
├── builders.test.ts    # Builder tests
├── models.test.ts      # Model/serialization tests
├── errors.test.ts      # Error class tests
├── helpers/
│   └── test-server.ts  # In-memory HTTP test server
└── integrations/
    └── ai-sdk.test.ts  # AI SDK integration tests
```

---

## License

MIT — see [LICENSE](LICENSE).

---

*Built for multi-agent AI workflows. Woof! 🐺*
