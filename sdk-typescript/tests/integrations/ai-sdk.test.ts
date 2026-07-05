/**
 * Tests for the HandoffRail Vercel AI SDK integration.
 */

import { HandoffRailClient } from '../../src/client';
import { HandoffRailToolSet, createHandoffRailTools } from '../../src/integrations/ai-sdk';

// We mock at a higher level — the tool definitions produce AIToolDefinition
// objects. We test the shape and execute the inner logic by mocking the client.

jest.mock('../../src/client');

const MockClient = HandoffRailClient as jest.MockedClass<typeof HandoffRailClient>;

describe('HandoffRailToolSet', () => {
  let mockClient: jest.Mocked<HandoffRailClient>;
  let toolSet: HandoffRailToolSet;

  beforeEach(() => {
    MockClient.prototype.createPacket = jest.fn();
    MockClient.prototype.claimPacket = jest.fn();
    MockClient.prototype.updatePacket = jest.fn();
    MockClient.prototype.completePacket = jest.fn();
    MockClient.prototype.listPackets = jest.fn();
    MockClient.prototype.getPacket = jest.fn();
    MockClient.prototype.respondToHitl = jest.fn();
    MockClient.prototype.getPacketHistory = jest.fn();
    MockClient.prototype.chainPacket = jest.fn();

    mockClient = new MockClient({
      baseUrl: 'http://localhost:8080/api/v1',
      apiKey: 'test-key',
    }) as jest.Mocked<HandoffRailClient>;

    toolSet = new HandoffRailToolSet(mockClient, {
      agentId: 'test-agent',
      agentName: 'TestAgent',
      framework: 'custom',
    });
  });

  describe('createPacket tool', () => {
    it('should return a tool definition with the correct shape', () => {
      const tool = toolSet.createPacket();
      expect(tool.description).toContain('handoff packet');
      expect(tool.parameters).toHaveProperty('type', 'object');
      expect(tool.parameters).toHaveProperty('required');
      expect(tool.execute).toBeDefined();
    });

    it('should create a packet via execute', async () => {
      mockClient.createPacket.mockReturnValue({
        id: 'pkt-1',
        version: '1.0.0',
        metadata: {
          source_agent: { id: 'test-agent', name: 'TestAgent' },
          target_agent: { id: 'target-01', name: 'Target' },
          priority: 'normal',
          created_at: '2026-07-02T20:26:00Z',
        },
        context: { summary: 'Test summary' },
        decisions: [],
        actions: { pending: [], completed: [], failed: [] },
        dependencies: [],
        status: 'created',
        created_at: '2026-07-02T20:26:00Z',
        updated_at: '2026-07-02T20:26:00Z',
      });

      const tool = toolSet.createPacket();
      const result = await tool.execute!({
        target_agent_id: 'target-01',
        target_agent_name: 'Target',
        summary: 'Test summary',
      });

      expect(result).toEqual({
        status: 'created',
        packet_id: 'pkt-1',
        summary: 'Test summary',
        priority: 'normal',
      });
    });

    it('should include HITL when hitl_reason is provided', async () => {
      mockClient.createPacket.mockReturnValue({
        id: 'pkt-1',
        version: '1.0.0',
        metadata: {
          source_agent: { id: 'test-agent', name: 'TestAgent' },
          target_agent: { id: 'target-01', name: 'Target' },
          priority: 'normal',
          created_at: '2026-07-02T20:26:00Z',
        },
        context: { summary: 'Needs approval' },
        decisions: [],
        actions: { pending: [], completed: [], failed: [] },
        dependencies: [],
        hitl: { required: true, reason: 'Need approval', question: 'Approve?' },
        status: 'awaiting_human',
        created_at: '2026-07-02T20:26:00Z',
        updated_at: '2026-07-02T20:26:00Z',
      });

      const tool = toolSet.createPacket();
      const result = await tool.execute!({
        target_agent_id: 'target-01',
        target_agent_name: 'Target',
        summary: 'Needs approval',
        hitl_reason: 'Need approval',
        hitl_question: 'Approve?',
      });

      expect(result).toHaveProperty('packet_id', 'pkt-1');
      expect(mockClient.createPacket).toHaveBeenCalledWith(
        expect.objectContaining({
          hitl: expect.objectContaining({
            reason: 'Need approval',
            question: 'Approve?',
          }),
        }),
      );
    });

    it('should handle HandoffRailError gracefully', async () => {
      const { AuthenticationError } = require('../../src/errors');
      mockClient.createPacket.mockImplementation(() => {
        throw new AuthenticationError('Invalid API key');
      });

      const tool = toolSet.createPacket();
      const result = await tool.execute!({
        target_agent_id: 'target-01',
        target_agent_name: 'Target',
        summary: 'Test',
      });

      expect(result).toEqual({
        error: 'Invalid API key',
        error_type: 'AuthenticationError',
      });
    });
  });

  describe('claimPacket tool', () => {
    it('should claim a packet', async () => {
      mockClient.claimPacket.mockReturnValue({
        id: 'pkt-1',
        version: '1.0.0',
        metadata: {
          source_agent: { id: 'src', name: 'Src' },
          target_agent: { id: 'test-agent', name: 'TestAgent' },
          created_at: '2026-07-02T20:26:00Z',
        },
        context: { summary: 'Claimed packet' },
        status: 'claimed',
        created_at: '2026-07-02T20:26:00Z',
        updated_at: '2026-07-02T20:26:00Z',
      });

      const tool = toolSet.claimPacket();
      const result = await tool.execute!({ packet_id: 'pkt-1' });

      expect(result).toEqual({
        status: 'claimed',
        packet_id: 'pkt-1',
        summary: 'Claimed packet',
      });
    });
  });

  describe('updatePacket tool', () => {
    it('should update a packet', async () => {
      mockClient.updatePacket.mockReturnValue({
        id: 'pkt-1',
        version: '1.0.0',
        metadata: {
          source_agent: { id: 'a', name: 'A' },
          target_agent: { id: 'b', name: 'B' },
          created_at: '2026-07-02T20:26:00Z',
        },
        context: { summary: 'Updated' },
        status: 'in_progress',
        created_at: '2026-07-02T20:26:00Z',
        updated_at: '2026-07-02T20:26:00Z',
      });

      const tool = toolSet.updatePacket();
      const result = await tool.execute!({
        packet_id: 'pkt-1',
        status: 'in_progress',
        summary: 'Updated',
      });

      expect(result).toEqual({
        status: 'updated',
        packet_id: 'pkt-1',
        packet_status: 'in_progress',
      });
    });
  });

  describe('completePacket tool', () => {
    it('should complete a packet', async () => {
      mockClient.completePacket.mockReturnValue({
        id: 'pkt-1',
        version: '1.0.0',
        metadata: {
          source_agent: { id: 'a', name: 'A' },
          target_agent: { id: 'b', name: 'B' },
          created_at: '2026-07-02T20:26:00Z',
        },
        context: { summary: 'Done' },
        status: 'completed',
        created_at: '2026-07-02T20:26:00Z',
        updated_at: '2026-07-02T20:26:00Z',
      });

      const tool = toolSet.completePacket();
      const result = await tool.execute!({ packet_id: 'pkt-1' });

      expect(result).toEqual({ status: 'completed', packet_id: 'pkt-1' });
    });
  });

  describe('listPackets tool', () => {
    it('should list packets', async () => {
      mockClient.listPackets.mockReturnValue({
        packets: [
          {
            id: 'pkt-1',
            version: '1.0.0',
            metadata: {
              source_agent: { id: 'src', name: 'Src' },
              target_agent: { id: 'tgt', name: 'Tgt' },
              priority: 'high',
              created_at: '2026-07-02T20:26:00Z',
            },
            context: { summary: 'Test' },
            status: 'created',
            created_at: '2026-07-02T20:26:00Z',
            updated_at: '2026-07-02T20:26:00Z',
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      });

      const tool = toolSet.listPackets();
      const result = await tool.execute!({});

      expect(result).toHaveProperty('total', 1);
      expect((result as { packets: unknown[] }).packets).toHaveLength(1);
    });
  });

  describe('getPacket tool', () => {
    it('should get a packet', async () => {
      mockClient.getPacket.mockReturnValue({
        id: 'pkt-1',
        version: '1.0.0',
        metadata: {
          source_agent: { id: 'a', name: 'A' },
          target_agent: { id: 'b', name: 'B' },
          created_at: '2026-07-02T20:26:00Z',
        },
        context: { summary: 'Detail' },
        status: 'created',
        created_at: '2026-07-02T20:26:00Z',
        updated_at: '2026-07-02T20:26:00Z',
      });

      const tool = toolSet.getPacket();
      const result = await tool.execute!({ packet_id: 'pkt-1' });

      expect(result).toHaveProperty('id', 'pkt-1');
      expect(result).toHaveProperty('status', 'created');
    });
  });

  describe('respondToHitl tool', () => {
    it('should respond to HITL', async () => {
      mockClient.respondToHitl.mockReturnValue({
        id: 'pkt-1',
        version: '1.0.0',
        metadata: {
          source_agent: { id: 'a', name: 'A' },
          target_agent: { id: 'b', name: 'B' },
          created_at: '2026-07-02T20:26:00Z',
        },
        context: { summary: 'Reviewed' },
        status: 'in_progress',
        created_at: '2026-07-02T20:26:00Z',
        updated_at: '2026-07-02T20:26:00Z',
      });

      const tool = toolSet.respondToHitl();
      const result = await tool.execute!({
        packet_id: 'pkt-1',
        response: 'Approved',
      });

      expect(result).toEqual({
        status: 'responded',
        packet_id: 'pkt-1',
        packet_status: 'in_progress',
      });
    });
  });

  describe('getPacketHistory tool', () => {
    it('should get packet history', async () => {
      mockClient.getPacketHistory.mockReturnValue({
        packet_id: 'pkt-1',
        events: [{ id: 'evt-1', packet_id: 'pkt-1', event_type: 'created', actor: 'agent', timestamp: '2026-07-02T20:26:00Z' }],
      });

      const tool = toolSet.getPacketHistory();
      const result = await tool.execute!({ packet_id: 'pkt-1' });

      expect(result).toHaveProperty('events');
      expect((result as { events: unknown[] }).events).toHaveLength(1);
    });
  });

  describe('chainPacket tool', () => {
    it('should chain a packet', async () => {
      mockClient.chainPacket.mockReturnValue({
        id: 'child-pkt',
        version: '1.0.0',
        parent_packet_id: 'parent-pkt',
        metadata: {
          source_agent: { id: 'a', name: 'A' },
          target_agent: { id: 'b', name: 'B' },
          created_at: '2026-07-02T20:26:00Z',
        },
        context: { summary: 'Chained' },
        status: 'created',
        created_at: '2026-07-02T20:26:00Z',
        updated_at: '2026-07-02T20:26:00Z',
      });

      const tool = toolSet.chainPacket();
      const result = await tool.execute!({
        parent_packet_id: 'parent-pkt',
        target_agent_id: 'target-01',
        target_agent_name: 'Target',
        summary: 'Chained',
      });

      expect(result).toEqual({
        status: 'chained',
        packet_id: 'child-pkt',
        parent_packet_id: 'parent-pkt',
      });
    });
  });

  describe('getAllTools', () => {
    it('should return all tool definitions', () => {
      const allTools = toolSet.getAllTools();
      const toolNames = Object.keys(allTools);

      expect(toolNames).toContain('handoffrail_create_packet');
      expect(toolNames).toContain('handoffrail_claim_packet');
      expect(toolNames).toContain('handoffrail_update_packet');
      expect(toolNames).toContain('handoffrail_complete_packet');
      expect(toolNames).toContain('handoffrail_list_packets');
      expect(toolNames).toContain('handoffrail_get_packet');
      expect(toolNames).toContain('handoffrail_respond_to_hitl');
      expect(toolNames).toContain('handoffrail_get_packet_history');
      expect(toolNames).toContain('handoffrail_chain_packet');
      expect(toolNames).toHaveLength(9);
    });
  });
});

describe('createHandoffRailTools', () => {
  it('should create tools via the factory function', () => {
    const mockClient = new MockClient({
      baseUrl: 'http://localhost:8080/api/v1',
      apiKey: 'test-key',
    }) as jest.Mocked<HandoffRailClient>;

    const tools = createHandoffRailTools(mockClient, {
      agentId: 'agent-01',
      agentName: 'Agent',
    });

    expect(tools).toHaveProperty('handoffrail_create_packet');
    expect(tools).toHaveProperty('handoffrail_claim_packet');
    expect(tools).toHaveProperty('handoffrail_list_packets');
  });
});
