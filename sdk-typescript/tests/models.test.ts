/**
 * Tests for HandoffRail SDK data models and serialization helpers.
 */

import {
  nowISO,
  excludeNil,
  serializePacketCreate,
  serializePacketUpdate,
  serializeChainHandoffRequest,
} from '../src/models';

import type {
  PacketCreate,
  PacketResponse,
  PacketUpdate,
  ChainHandoffRequest,
  Metadata,
  PacketContext,
} from '../src/models';

describe('nowISO', () => {
  it('should return an ISO 8601 string', () => {
    const result = nowISO();
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
  });
});

describe('excludeNil', () => {
  it('should remove undefined and null values', () => {
    const result = excludeNil({
      a: 'hello',
      b: undefined,
      c: null,
      d: 0,
      e: false,
      f: '',
    });
    expect(result).toEqual({
      a: 'hello',
      d: 0,
      e: false,
      f: '',
    });
  });

  it('should return empty object for all-nil input', () => {
    expect(excludeNil({ a: undefined, b: null })).toEqual({});
  });
});

describe('serializePacketCreate', () => {
  it('should serialize a minimal packet create payload', () => {
    const packet: PacketCreate = {
      metadata: {
        source_agent: { id: 'agent-1', name: 'Agent One' },
        target_agent: { id: 'agent-2', name: 'Agent Two' },
      },
      context: {
        summary: 'Test handoff',
      },
    };

    const result = serializePacketCreate(packet);
    expect(result.metadata).toBeDefined();
    expect(result.context).toBeDefined();
    expect((result.metadata as Record<string, unknown>).source_agent).toEqual({
      id: 'agent-1',
      name: 'Agent One',
    });
    expect((result.context as Record<string, unknown>).summary).toBe('Test handoff');
  });

  it('should include optional fields when present', () => {
    const packet: PacketCreate = {
      parent_packet_id: 'parent-123',
      metadata: {
        source_agent: { id: 'src-1', name: 'Source' },
        target_agent: { id: 'tgt-1', name: 'Target' },
        priority: 'high',
        tags: ['urgent', 'test'],
      },
      context: {
        summary: 'With all options',
        conversation_state: [{ role: 'user', content: 'Hello' }],
        custom: { key: 'value' },
      },
      decisions: [{ id: 'd1', decision: 'Proceed', rationale: 'All good' }],
      hitl: { required: true, reason: 'Approve this' },
    };

    const result = serializePacketCreate(packet);
    expect(result.parent_packet_id).toBe('parent-123');
    expect((result.metadata as Record<string, unknown>).priority).toBe('high');
    expect((result.context as Record<string, unknown>).conversation_state).toHaveLength(1);
  });
});

describe('serializePacketUpdate', () => {
  it('should serialize a status-only update', () => {
    const update: PacketUpdate = { status: 'completed' };
    const result = serializePacketUpdate(update);
    expect(result.status).toBe('completed');
  });

  it('should serialize a context update', () => {
    const update: PacketUpdate = {
      status: 'in_progress',
      context: { summary: 'Updated summary' },
    };
    const result = serializePacketUpdate(update);
    expect(result.status).toBe('in_progress');
    expect((result.context as Record<string, unknown>).summary).toBe('Updated summary');
  });
});

describe('serializeChainHandoffRequest', () => {
  it('should serialize a chain request', () => {
    const request: ChainHandoffRequest = {
      metadata: {
        source_agent: { id: 'src', name: 'Source' },
        target_agent: { id: 'tgt', name: 'Target' },
      },
      context: {
        summary: 'Chain test',
      },
    };

    const result = serializeChainHandoffRequest(request);
    expect(result.metadata).toBeDefined();
    expect(result.context).toBeDefined();
    expect((result.context as Record<string, unknown>).summary).toBe('Chain test');
  });
});
