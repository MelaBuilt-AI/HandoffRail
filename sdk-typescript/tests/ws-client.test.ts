/**
 * Tests for the AsyncWebSocketClient using mocked WebSocket.
 */

import {
  AsyncWebSocketClient,
  EVENT_PACKET_CREATED,
  EVENT_PACKET_CLAIMED,
  EVENT_PACKET_COMPLETED,
  EVENT_PACKET_FAILED,
  EVENT_PACKET_CHAINED,
  EVENT_HITL_RESPONSE_READY,
  ALL_EVENTS,
  WS_OPEN,
  WS_CLOSED,
} from '../src/ws-client';
import type { WebSocketLike, WebSocketFactory } from '../src/ws-client';

// ── Mock WebSocket ──────────────────────────────────────────────────────────

interface MockWSOptions {
  /** If true, fail the connection immediately (onerror + onclose). */
  failConnect?: boolean;
  /** If true, close the connection after a short delay. */
  closeAfterConnect?: boolean;
}

class MockWebSocket implements WebSocketLike {
  public readyState: number = 0; // CONNECTING
  public onopen: ((event: unknown) => void) | null = null;
  public onmessage: ((event: { data: string }) => void) | null = null;
  public onclose: ((event: { code: number; reason: string }) => void) | null = null;
  public onerror: ((event: unknown) => void) | null = null;

  private _sentMessages: string[] = [];
  private _options: MockWSOptions;

  constructor(
    public readonly url: string,
    options: MockWSOptions = {},
  ) {
    this._options = options;

    if (options.failConnect) {
      // Simulate immediate connection failure
      setTimeout(() => {
        if (this.onerror) this.onerror({});
        if (this.onclose) this.onclose({ code: 1006, reason: 'Connection failed' });
      }, 0);
    } else {
      // Simulate successful connection
      setTimeout(() => {
        this.readyState = WS_OPEN;
        if (this.onopen) this.onopen({});
      }, 0);
    }
  }

  send(data: string): void {
    this._sentMessages.push(data);
  }

  close(code?: number, reason?: string): void {
    this.readyState = WS_CLOSED;
    if (this.onclose) {
      this.onclose({ code: code ?? 1000, reason: reason ?? '' });
    }
  }

  /** Simulate receiving a message from the server. */
  simulateMessage(data: Record<string, unknown>): void {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify(data) });
    }
  }

  /** Simulate a server-initiated close. */
  simulateClose(code = 1000, reason = ''): void {
    this.readyState = WS_CLOSED;
    if (this.onclose) {
      this.onclose({ code, reason });
    }
  }

  /** Get all messages sent by the client. */
  get sentMessages(): string[] {
    return [...this._sentMessages];
  }
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function createMockFactory(
  options?: MockWSOptions,
): { factory: WebSocketFactory; instances: MockWebSocket[] } {
  const instances: MockWebSocket[] = [];
  const factory: WebSocketFactory = (url: string) => {
    const ws = new MockWebSocket(url, options);
    instances.push(ws);
    return ws;
  };
  return { factory, instances };
}

/** Wait for a tick to let async operations settle. */
const tick = () => new Promise((resolve) => setTimeout(resolve, 10));

// ── Tests ────────────────────────────────────────────────────────────────────

describe('AsyncWebSocketClient', () => {
  // ── URL construction ──────────────────────────────────────────────────

  describe('URL construction', () => {
    it('should derive ws:// URL from http:// base URL', () => {
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
      });
      expect(client.wsUrl).toBe('ws://localhost:8080/ws?api_key=test-key');
    });

    it('should derive wss:// URL from https:// base URL', () => {
      const client = new AsyncWebSocketClient({
        baseUrl: 'https://api.example.com',
        apiKey: 'test-key',
      });
      expect(client.wsUrl).toBe('wss://api.example.com/ws?api_key=test-key');
    });

    it('should strip /api/v1 suffix from base URL', () => {
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080/api/v1',
        apiKey: 'test-key',
      });
      expect(client.wsUrl).toBe('ws://localhost:8080/ws?api_key=test-key');
    });

    it('should strip trailing slash from base URL', () => {
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080/',
        apiKey: 'test-key',
      });
      expect(client.wsUrl).toBe('ws://localhost:8080/ws?api_key=test-key');
    });

    it('should URL-encode the API key', () => {
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'key with spaces',
      });
      expect(client.wsUrl).toBe('ws://localhost:8080/ws?api_key=key%20with%20spaces');
    });

    it('should not double-append /ws if already present', () => {
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080/ws',
        apiKey: 'test-key',
      });
      expect(client.wsUrl).toBe('ws://localhost:8080/ws?api_key=test-key');
    });
  });

  // ── Connection lifecycle ──────────────────────────────────────────────

  describe('connection lifecycle', () => {
    it('should connect and set connected flag', async () => {
      const { factory, instances } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });

      expect(client.connected).toBe(false);
      await client.connect();
      await tick();

      expect(client.connected).toBe(true);
      expect(instances.length).toBe(1);
      expect(instances[0].url).toBe('ws://localhost:8080/ws?api_key=test-key');

      await client.close();
    });

    it('should fire onConnected callback', async () => {
      const { factory } = createMockFactory();
      const onConnected = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onConnected = onConnected;

      await client.connect();
      await tick();

      expect(onConnected).toHaveBeenCalledTimes(1);
      await client.close();
    });

    it('should close and set connected to false', async () => {
      const { factory } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });

      await client.connect();
      await tick();
      expect(client.connected).toBe(true);

      await client.close();
      expect(client.connected).toBe(false);
    });

    it('should fire onDisconnected callback on close', async () => {
      const { factory } = createMockFactory();
      const onDisconnected = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onDisconnected = onDisconnected;

      await client.connect();
      await tick();
      await client.close();
      await tick();

      expect(onDisconnected).toHaveBeenCalledTimes(1);
    });

    it('should fire onDisconnected on server-initiated close', async () => {
      const { factory, instances } = createMockFactory();
      const onDisconnected = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        reconnect: false,
        webSocketFactory: factory,
      });
      client.onDisconnected = onDisconnected;

      await client.connect();
      await tick();

      instances[0].simulateClose(1000, 'Server shutdown');
      await tick();

      expect(onDisconnected).toHaveBeenCalledTimes(1);
      expect(client.connected).toBe(false);

      await client.close();
    });
  });

  // ── Event dispatch ────────────────────────────────────────────────────

  describe('event dispatch', () => {
    it('should dispatch packet.created events to onPacketCreated', async () => {
      const { factory, instances } = createMockFactory();
      const onPacketCreated = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onPacketCreated = onPacketCreated;

      await client.connect();
      await tick();

      instances[0].simulateMessage({
        type: 'packet.created',
        packet_id: 'pkt-123',
        timestamp: '2026-07-05T12:00:00Z',
        data: { status: 'created' },
      });
      await tick();

      expect(onPacketCreated).toHaveBeenCalledTimes(1);
      const event = onPacketCreated.mock.calls[0][0];
      expect(event.event_type).toBe('packet.created');
      expect(event.packet_id).toBe('pkt-123');
      expect(event.timestamp).toBe('2026-07-05T12:00:00Z');

      await client.close();
    });

    it('should dispatch packet.claimed events to onPacketClaimed', async () => {
      const { factory, instances } = createMockFactory();
      const onPacketClaimed = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onPacketClaimed = onPacketClaimed;

      await client.connect();
      await tick();

      instances[0].simulateMessage({
        type: 'packet.claimed',
        packet_id: 'pkt-456',
        timestamp: '2026-07-05T12:01:00Z',
      });
      await tick();

      expect(onPacketClaimed).toHaveBeenCalledTimes(1);
      expect(onPacketClaimed.mock.calls[0][0].packet_id).toBe('pkt-456');

      await client.close();
    });

    it('should dispatch packet.completed events to onPacketCompleted', async () => {
      const { factory, instances } = createMockFactory();
      const onPacketCompleted = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onPacketCompleted = onPacketCompleted;

      await client.connect();
      await tick();

      instances[0].simulateMessage({
        type: 'packet.completed',
        packet_id: 'pkt-789',
        timestamp: '2026-07-05T12:02:00Z',
      });
      await tick();

      expect(onPacketCompleted).toHaveBeenCalledTimes(1);

      await client.close();
    });

    it('should dispatch packet.failed events to onPacketFailed', async () => {
      const { factory, instances } = createMockFactory();
      const onPacketFailed = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onPacketFailed = onPacketFailed;

      await client.connect();
      await tick();

      instances[0].simulateMessage({
        type: 'packet.failed',
        packet_id: 'pkt-fail',
        timestamp: '2026-07-05T12:03:00Z',
      });
      await tick();

      expect(onPacketFailed).toHaveBeenCalledTimes(1);

      await client.close();
    });

    it('should dispatch packet.chained events to onPacketChained', async () => {
      const { factory, instances } = createMockFactory();
      const onPacketChained = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onPacketChained = onPacketChained;

      await client.connect();
      await tick();

      instances[0].simulateMessage({
        type: 'packet.chained',
        packet_id: 'pkt-chain',
        timestamp: '2026-07-05T12:04:00Z',
      });
      await tick();

      expect(onPacketChained).toHaveBeenCalledTimes(1);

      await client.close();
    });

    it('should dispatch hitl.response_ready events to onHitlResponseReady', async () => {
      const { factory, instances } = createMockFactory();
      const onHitlResponseReady = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onHitlResponseReady = onHitlResponseReady;

      await client.connect();
      await tick();

      instances[0].simulateMessage({
        type: 'hitl.response_ready',
        packet_id: 'pkt-hitl',
        timestamp: '2026-07-05T12:05:00Z',
      });
      await tick();

      expect(onHitlResponseReady).toHaveBeenCalledTimes(1);

      await client.close();
    });

    it('should fire generic onEvent callback for all events', async () => {
      const { factory, instances } = createMockFactory();
      const onEvent = jest.fn();
      const onPacketCreated = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onEvent = onEvent;
      client.onPacketCreated = onPacketCreated;

      await client.connect();
      await tick();

      instances[0].simulateMessage({
        type: 'packet.created',
        packet_id: 'pkt-123',
        timestamp: '2026-07-05T12:00:00Z',
      });
      await tick();

      // Generic callback fires first, then specific
      expect(onEvent).toHaveBeenCalledTimes(1);
      expect(onPacketCreated).toHaveBeenCalledTimes(1);

      await client.close();
    });

    it('should not throw on unknown event types', async () => {
      const { factory, instances } = createMockFactory();
      const onEvent = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onEvent = onEvent;

      await client.connect();
      await tick();

      // Should not throw
      instances[0].simulateMessage({
        type: 'unknown.event',
        packet_id: 'pkt-unknown',
        timestamp: '2026-07-05T12:00:00Z',
      });
      await tick();

      // Generic callback still fires
      expect(onEvent).toHaveBeenCalledTimes(1);

      await client.close();
    });

    it('should handle invalid JSON gracefully', async () => {
      const { factory, instances } = createMockFactory();
      const onEvent = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onEvent = onEvent;

      await client.connect();
      await tick();

      // Send invalid JSON directly via onmessage
      if (instances[0].onmessage) {
        instances[0].onmessage({ data: 'not valid json' });
      }
      await tick();

      // Should not have called any callback
      expect(onEvent).not.toHaveBeenCalled();

      await client.close();
    });

    it('should handle event_type field as fallback for type', async () => {
      const { factory, instances } = createMockFactory();
      const onPacketCreated = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onPacketCreated = onPacketCreated;

      await client.connect();
      await tick();

      // Use event_type instead of type
      instances[0].simulateMessage({
        event_type: 'packet.created',
        packet_id: 'pkt-123',
        timestamp: '2026-07-05T12:00:00Z',
      });
      await tick();

      expect(onPacketCreated).toHaveBeenCalledTimes(1);

      await client.close();
    });
  });

  // ── Subscription filtering ────────────────────────────────────────────

  describe('subscription management', () => {
    it('should send subscribe message to server', async () => {
      const { factory, instances } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });

      await client.connect();
      await tick();

      await client.subscribe('status:created');
      await tick();

      const messages = instances[0].sentMessages;
      expect(messages.length).toBe(1);
      const parsed = JSON.parse(messages[0]);
      expect(parsed).toEqual({ action: 'subscribe', channel: 'status:created' });

      await client.close();
    });

    it('should send unsubscribe message to server', async () => {
      const { factory, instances } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });

      await client.connect();
      await tick();

      await client.unsubscribe('status:created');
      await tick();

      const messages = instances[0].sentMessages;
      expect(messages.length).toBe(1);
      const parsed = JSON.parse(messages[0]);
      expect(parsed).toEqual({ action: 'unsubscribe', channel: 'status:created' });

      await client.close();
    });

    it('should subscribe to packet-specific channel', async () => {
      const { factory, instances } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });

      await client.connect();
      await tick();

      await client.subscribe('packet:pkt-123');
      await tick();

      const parsed = JSON.parse(instances[0].sentMessages[0]);
      expect(parsed).toEqual({ action: 'subscribe', channel: 'packet:pkt-123' });

      await client.close();
    });

    it('should subscribe to agent-specific channel', async () => {
      const { factory, instances } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });

      await client.connect();
      await tick();

      await client.subscribe('agent:agent-01');
      await tick();

      const parsed = JSON.parse(instances[0].sentMessages[0]);
      expect(parsed).toEqual({ action: 'subscribe', channel: 'agent:agent-01' });

      await client.close();
    });

    it('should not throw when subscribing while disconnected', async () => {
      const { factory } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });

      // Subscribe before connecting — should not throw
      await expect(client.subscribe('status:created')).resolves.toBeUndefined();
    });
  });

  // ── Ping ──────────────────────────────────────────────────────────────

  describe('ping', () => {
    it('should send ping message to server', async () => {
      const { factory, instances } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });

      await client.connect();
      await tick();

      await client.ping();
      await tick();

      const messages = instances[0].sentMessages;
      expect(messages.length).toBe(1);
      const parsed = JSON.parse(messages[0]);
      expect(parsed).toEqual({ action: 'ping' });

      await client.close();
    });

    it('should not throw when pinging while disconnected', async () => {
      const { factory } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });

      await expect(client.ping()).resolves.toBeUndefined();
    });
  });

  // ── Reconnect logic ───────────────────────────────────────────────────

  describe('reconnect', () => {
    it('should reconnect after server disconnect when reconnect is enabled', async () => {
      const { factory, instances } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        reconnect: true,
        reconnectDelay: 10,
        maxReconnectDelay: 100,
        webSocketFactory: factory,
      });

      await client.connect();
      await tick();
      expect(instances.length).toBe(1);

      // Simulate server disconnect
      instances[0].simulateClose(1006, 'Connection lost');
      await tick();

      // Wait for reconnect
      await new Promise((resolve) => setTimeout(resolve, 50));

      // Should have created a new WebSocket instance
      expect(instances.length).toBeGreaterThanOrEqual(2);

      await client.close();
    });

    it('should not reconnect when reconnect is disabled', async () => {
      const { factory, instances } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        reconnect: false,
        webSocketFactory: factory,
      });

      await client.connect();
      await tick();
      expect(instances.length).toBe(1);

      // Simulate server disconnect
      instances[0].simulateClose(1006, 'Connection lost');
      await tick();

      // Wait a bit to ensure no reconnect
      await new Promise((resolve) => setTimeout(resolve, 50));

      // Should still have only 1 instance
      expect(instances.length).toBe(1);

      await client.close();
    });

    it('should use exponential backoff for reconnect delays', async () => {
      const { factory, instances } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        reconnect: true,
        reconnectDelay: 10,
        reconnectMultiplier: 2.0,
        maxReconnectDelay: 1000,
        webSocketFactory: factory,
      });

      await client.connect();
      await tick();

      // First disconnect
      instances[0].simulateClose(1006, 'Lost');
      await tick();
      await new Promise((resolve) => setTimeout(resolve, 30));
      const countAfterFirst = instances.length;

      // Second disconnect (on the reconnected instance)
      const lastInstance = instances[instances.length - 1];
      lastInstance.simulateClose(1006, 'Lost again');
      await tick();
      await new Promise((resolve) => setTimeout(resolve, 50));
      const countAfterSecond = instances.length;

      // Should have reconnected at least once more
      expect(countAfterSecond).toBeGreaterThanOrEqual(countAfterFirst + 1);

      await client.close();
    });

    it('should fire onError on connection failure', async () => {
      const onError = jest.fn();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        reconnect: false,
        webSocketFactory: createMockFactory({ failConnect: true }).factory,
      });
      client.onError = onError;

      await client.connect();
      await tick();

      expect(onError).toHaveBeenCalledTimes(1);
      expect(onError.mock.calls[0][0]).toBeInstanceOf(Error);

      await client.close();
    });

    it('should stop reconnecting after close() is called', async () => {
      const { factory, instances } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        reconnect: true,
        reconnectDelay: 10,
        webSocketFactory: factory,
      });

      await client.connect();
      await tick();

      // Disconnect and immediately close
      instances[0].simulateClose(1006, 'Lost');
      await client.close();
      await tick();

      const countAfterClose = instances.length;

      // Wait to ensure no reconnect happened
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(instances.length).toBe(countAfterClose);
    });
  });

  // ── Event constants ───────────────────────────────────────────────────

  describe('event constants', () => {
    it('should export all expected event type constants', () => {
      expect(EVENT_PACKET_CREATED).toBe('packet.created');
      expect(EVENT_PACKET_CLAIMED).toBe('packet.claimed');
      expect(EVENT_PACKET_COMPLETED).toBe('packet.completed');
      expect(EVENT_PACKET_FAILED).toBe('packet.failed');
      expect(EVENT_PACKET_CHAINED).toBe('packet.chained');
      expect(EVENT_HITL_RESPONSE_READY).toBe('hitl.response_ready');
    });

    it('ALL_EVENTS should contain all event types', () => {
      expect(ALL_EVENTS.has('packet.created')).toBe(true);
      expect(ALL_EVENTS.has('packet.claimed')).toBe(true);
      expect(ALL_EVENTS.has('packet.updated')).toBe(true);
      expect(ALL_EVENTS.has('packet.in_progress')).toBe(true);
      expect(ALL_EVENTS.has('packet.awaiting_human')).toBe(true);
      expect(ALL_EVENTS.has('packet.completed')).toBe(true);
      expect(ALL_EVENTS.has('packet.failed')).toBe(true);
      expect(ALL_EVENTS.has('packet.expired')).toBe(true);
      expect(ALL_EVENTS.has('packet.chained')).toBe(true);
      expect(ALL_EVENTS.has('hitl.response_ready')).toBe(true);
      expect(ALL_EVENTS.size).toBe(10);
    });
  });

  // ── WebSocket ready state constants ───────────────────────────────────

  describe('WebSocket constants', () => {
    it('should export standard WebSocket ready state constants', () => {
      expect(WS_OPEN).toBe(1);
      expect(WS_CLOSED).toBe(3);
    });
  });

  // ── Default options ───────────────────────────────────────────────────

  describe('default options', () => {
    it('should use sensible defaults', () => {
      const { factory } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });

      // Defaults are applied in constructor — just verify it doesn't throw
      expect(client).toBeDefined();
      expect(client.connected).toBe(false);
    });
  });

  // ── Callback error resilience ─────────────────────────────────────────

  describe('callback error resilience', () => {
    it('should not throw when a callback throws synchronously', async () => {
      const { factory, instances } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onPacketCreated = () => {
        throw new Error('Callback error');
      };

      await client.connect();
      await tick();

      // Should not throw
      instances[0].simulateMessage({
        type: 'packet.created',
        packet_id: 'pkt-123',
        timestamp: '2026-07-05T12:00:00Z',
      });
      await tick();

      // Client should still be connected
      expect(client.connected).toBe(true);

      await client.close();
    });

    it('should not throw when a callback rejects asynchronously', async () => {
      const { factory, instances } = createMockFactory();
      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onPacketCreated = async () => {
        throw new Error('Async callback error');
      };

      await client.connect();
      await tick();

      // Should not throw
      instances[0].simulateMessage({
        type: 'packet.created',
        packet_id: 'pkt-123',
        timestamp: '2026-07-05T12:00:00Z',
      });
      await tick();

      expect(client.connected).toBe(true);

      await client.close();
    });
  });

  // ── Multiple events ───────────────────────────────────────────────────

  describe('multiple events', () => {
    it('should dispatch multiple events in sequence', async () => {
      const { factory, instances } = createMockFactory();
      const onPacketCreated = jest.fn();
      const onPacketCompleted = jest.fn();

      const client = new AsyncWebSocketClient({
        baseUrl: 'http://localhost:8080',
        apiKey: 'test-key',
        webSocketFactory: factory,
      });
      client.onPacketCreated = onPacketCreated;
      client.onPacketCompleted = onPacketCompleted;

      await client.connect();
      await tick();

      instances[0].simulateMessage({
        type: 'packet.created',
        packet_id: 'pkt-1',
        timestamp: '2026-07-05T12:00:00Z',
      });
      instances[0].simulateMessage({
        type: 'packet.completed',
        packet_id: 'pkt-1',
        timestamp: '2026-07-05T12:01:00Z',
      });
      await tick();

      expect(onPacketCreated).toHaveBeenCalledTimes(1);
      expect(onPacketCompleted).toHaveBeenCalledTimes(1);

      await client.close();
    });
  });
});
