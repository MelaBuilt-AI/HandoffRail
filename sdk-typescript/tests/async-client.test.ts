/**
 * Tests for the async HandoffRailClient using mocked fetch.
 */

import { AsyncHandoffRailClient } from '../src/async-client';
import { PacketBuilder } from '../src/builders';

// Helper: create a mock Response
function mockResponse(status: number, body: unknown, headers?: Record<string, string>): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: {
      get: (name: string) => {
        if (headers && name in headers) return headers[name];
        return null;
      },
      forEach: () => {},
    } as unknown as Headers,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

// Store original fetch
const originalFetch = globalThis.fetch;

describe('AsyncHandoffRailClient', () => {
  let client: AsyncHandoffRailClient;

  beforeEach(() => {
    client = new AsyncHandoffRailClient({
      baseUrl: 'http://localhost:8080/api/v1',
      apiKey: 'test-key-123',
      maxRetries: 0, // Disable retries for test predictability
    });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  describe('createPacket', () => {
    it('should create a packet successfully', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(200, {
          id: '550e8400-e29b-41d4-a716-446655440000',
          version: '1.0.0',
          metadata: {
            source_agent: { id: 'sales-01', name: 'SalesBot' },
            target_agent: { id: 'billing-01', name: 'BillingBot' },
            priority: 'normal',
          },
          context: { summary: 'Test handoff' },
          decisions: [],
          actions: { pending: [], completed: [], failed: [] },
          dependencies: [],
          status: 'created',
          created_at: '2026-07-02T20:26:00Z',
          updated_at: '2026-07-02T20:26:00Z',
        }),
      );

      const packet = new PacketBuilder()
        .from('sales-01', 'SalesBot')
        .to('billing-01', 'BillingBot')
        .withSummary('Test handoff')
        .build();

      const result = await client.createPacket(packet);
      expect(result.id).toBe('550e8400-e29b-41d4-a716-446655440000');
      expect(result.status).toBe('created');
    });

    it('should throw ValidationError on 400', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(400, { detail: 'Invalid field', field: 'priority' }),
      );

      const packet = new PacketBuilder()
        .from('a', 'A')
        .to('b', 'B')
        .withSummary('test')
        .build();

      await expect(client.createPacket(packet)).rejects.toThrow('Invalid field');
    });
  });

  describe('getPacket', () => {
    it('should get a packet by ID', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(200, {
          id: 'pkt-1',
          metadata: {
            source_agent: { id: 'a', name: 'A' },
            target_agent: { id: 'b', name: 'B' },
          },
          context: { summary: 'test' },
          status: 'created',
          created_at: '2026-07-02T20:26:00Z',
          updated_at: '2026-07-02T20:26:00Z',
        }),
      );

      const result = await client.getPacket('pkt-1');
      expect(result.id).toBe('pkt-1');
    });

    it('should throw NotFoundError on 404', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(404, { detail: 'Not found' }),
      );

      await expect(client.getPacket('missing')).rejects.toThrow('Not found');
    });
  });

  describe('listPackets', () => {
    it('should list packets with filters', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(200, {
          packets: [
            {
              id: 'pkt-1',
              metadata: {
                source_agent: { id: 'a', name: 'A' },
                target_agent: { id: 'b', name: 'B' },
              },
              context: { summary: 'test' },
              status: 'created',
              created_at: '2026-07-02T20:26:00Z',
              updated_at: '2026-07-02T20:26:00Z',
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      );

      const result = await client.listPackets({ status: 'created', limit: 10 });
      expect(result.total).toBe(1);
      expect(result.packets).toHaveLength(1);
    });
  });

  describe('claimPacket', () => {
    it('should claim a packet', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(200, {
          id: 'pkt-1',
          status: 'claimed',
          metadata: {
            source_agent: { id: 'a', name: 'A' },
            target_agent: { id: 'b', name: 'B' },
          },
          context: { summary: 'test' },
          created_at: '2026-07-02T20:26:00Z',
          updated_at: '2026-07-02T20:26:00Z',
        }),
      );

      const result = await client.claimPacket('pkt-1', {
        agent_id: 'billing-01',
        agent_name: 'BillingBot',
      });
      expect(result.status).toBe('claimed');
    });
  });

  describe('updatePacket', () => {
    it('should update a packet', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(200, {
          id: 'pkt-1',
          status: 'in_progress',
          context: { summary: 'updated' },
          metadata: {
            source_agent: { id: 'a', name: 'A' },
            target_agent: { id: 'b', name: 'B' },
          },
          created_at: '2026-07-02T20:26:00Z',
          updated_at: '2026-07-02T20:26:00Z',
        }),
      );

      const result = await client.updatePacket('pkt-1', {
        status: 'in_progress',
      });
      expect(result.status).toBe('in_progress');
    });
  });

  describe('completePacket', () => {
    it('should complete a packet', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(200, {
          id: 'pkt-1',
          status: 'completed',
          context: { summary: 'done' },
          metadata: {
            source_agent: { id: 'a', name: 'A' },
            target_agent: { id: 'b', name: 'B' },
          },
          created_at: '2026-07-02T20:26:00Z',
          updated_at: '2026-07-02T20:26:00Z',
        }),
      );

      const result = await client.completePacket('pkt-1');
      expect(result.status).toBe('completed');
    });
  });

  describe('deletePacket', () => {
    it('should delete a packet', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(mockResponse(204, {}));

      await expect(client.deletePacket('pkt-1')).resolves.toBeUndefined();
    });
  });

  describe('respondToHitl', () => {
    it('should respond to HITL checkpoint', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(200, {
          id: 'pkt-1',
          status: 'in_progress',
          hitl: { response: 'Approved' },
          metadata: {
            source_agent: { id: 'a', name: 'A' },
            target_agent: { id: 'b', name: 'B' },
          },
          context: { summary: 'test' },
          created_at: '2026-07-02T20:26:00Z',
          updated_at: '2026-07-02T20:26:00Z',
        }),
      );

      const result = await client.respondToHitl('pkt-1', {
        response: 'Approved',
        responded_by: 'human-01',
      });
      expect(result.hitl?.response).toBe('Approved');
    });
  });

  describe('listAwaitingHuman', () => {
    it('should list packets awaiting human review', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(200, {
          packets: [
            {
              id: 'pkt-1',
              status: 'awaiting_human',
              metadata: {
                source_agent: { id: 'a', name: 'A' },
                target_agent: { id: 'b', name: 'B' },
              },
              context: { summary: 'needs review' },
              created_at: '2026-07-02T20:26:00Z',
              updated_at: '2026-07-02T20:26:00Z',
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      );

      const result = await client.listAwaitingHuman();
      expect(result.packets[0].status).toBe('awaiting_human');
    });
  });

  describe('getPacketHistory', () => {
    it('should get packet history', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(200, {
          packet_id: 'pkt-1',
          events: [
            {
              id: 'evt-1',
              packet_id: 'pkt-1',
              event_type: 'packet.created',
              actor: 'agent-1',
              timestamp: '2026-07-02T20:26:00Z',
            },
          ],
        }),
      );

      const result = await client.getPacketHistory('pkt-1');
      expect(result.events).toHaveLength(1);
      expect(result.events[0].event_type).toBe('packet.created');
    });
  });

  describe('chainPacket', () => {
    it('should create a chained packet', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(200, {
          id: 'child-pkt',
          parent_packet_id: 'parent-pkt',
          status: 'created',
          metadata: {
            source_agent: { id: 'a', name: 'A' },
            target_agent: { id: 'b', name: 'B' },
          },
          context: { summary: 'chain test' },
          created_at: '2026-07-02T20:26:00Z',
          updated_at: '2026-07-02T20:26:00Z',
        }),
      );

      const request = {
        metadata: {
          source_agent: { id: 'a', name: 'A' },
          target_agent: { id: 'b', name: 'B' },
        },
        context: { summary: 'chain test' },
      };

      const result = await client.chainPacket('parent-pkt', request);
      expect(result.parent_packet_id).toBe('parent-pkt');
    });
  });

  describe('webhooks', () => {
    it('should register a webhook', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(200, {
          id: 'wh-001',
          url: 'https://example.com/hooks',
          events: ['packet.created'],
          tenant_id: 't1',
          active: true,
          created_at: '2026-07-02T20:26:00Z',
        }),
      );

      const result = await client.registerWebhook({
        url: 'https://example.com/hooks',
        secret: 'supersecretkey12345',
      });
      expect(result.active).toBe(true);
    });

    it('should list webhooks', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(200, [
          {
            id: 'wh-001',
            url: 'https://example.com/hooks',
            events: ['packet.created'],
            tenant_id: 't1',
            active: true,
            created_at: '2026-07-02T20:26:00Z',
          },
        ]),
      );

      const result = await client.listWebhooks();
      expect(result).toHaveLength(1);
    });

    it('should delete a webhook', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(mockResponse(204, {}));

      await expect(client.deleteWebhook('wh-001')).resolves.toBeUndefined();
    });
  });

  describe('error handling', () => {
    it('should throw AuthenticationError on 401', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(401, { detail: 'Invalid key' }),
      );

      await expect(client.getPacket('test')).rejects.toThrow('Invalid key');
    });

    it('should throw NotFoundError on 404', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(404, { detail: 'Not found' }),
      );

      await expect(client.getPacket('missing')).rejects.toThrow('Not found');
    });

    it('should throw ConflictError on 409', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(409, { detail: 'Already claimed' }),
      );

      await expect(
        client.claimPacket('test', { agent_id: 'a', agent_name: 'A' }),
      ).rejects.toThrow('Already claimed');
    });

    it('should throw RateLimitError on 429', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(429, { detail: 'Rate limited' }),
      );

      await expect(client.getPacket('test')).rejects.toThrow('Rate limit');
    });

    it('should throw ServerError on 500', async () => {
      globalThis.fetch = jest.fn().mockResolvedValue(
        mockResponse(500, { detail: 'Server error' }),
      );

      await expect(client.getPacket('test')).rejects.toThrow('Server error');
    });

    it('should throw ConnectionError on network failure', async () => {
      globalThis.fetch = jest.fn().mockRejectedValue(new Error('ECONNREFUSED'));

      await expect(client.getPacket('test')).rejects.toThrow('Unable to connect');
    });
  });
});
