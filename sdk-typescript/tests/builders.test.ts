/**
 * Tests for HandoffRail SDK fluent builders.
 */

import { PacketBuilder, ChainBuilder } from '../src/builders';

describe('PacketBuilder', () => {
  it('should build a minimal valid packet', () => {
    const packet = new PacketBuilder()
      .from('sales-01', 'SalesBot')
      .to('billing-01', 'BillingBot')
      .withSummary('Customer wants upgrade')
      .build();

    expect(packet.metadata.source_agent).toEqual({
      id: 'sales-01',
      name: 'SalesBot',
    });
    expect(packet.metadata.target_agent).toEqual({
      id: 'billing-01',
      name: 'BillingBot',
    });
    expect(packet.context.summary).toBe('Customer wants upgrade');
    expect(packet.metadata.priority).toBe('normal');
  });

  it('should throw when source agent is missing', () => {
    expect(() => {
      new PacketBuilder()
        .to('billing-01', 'BillingBot')
        .withSummary('test')
        .build();
    }).toThrow('Source agent is required');
  });

  it('should throw when target agent is missing', () => {
    expect(() => {
      new PacketBuilder()
        .from('sales-01', 'SalesBot')
        .withSummary('test')
        .build();
    }).toThrow('Target agent is required');
  });

  it('should throw when summary is missing', () => {
    expect(() => {
      new PacketBuilder()
        .from('sales-01', 'SalesBot')
        .to('billing-01', 'BillingBot')
        .build();
    }).toThrow('Summary is required');
  });

  it('should set priority and tags', () => {
    const packet = new PacketBuilder()
      .from('a', 'Agent A')
      .to('b', 'Agent B')
      .withSummary('test')
      .withPriority('high')
      .withTags(['urgent', 'business'])
      .build();

    expect(packet.metadata.priority).toBe('high');
    expect(packet.metadata.tags).toEqual(['urgent', 'business']);
  });

  it('should accept framework and version for source agent', () => {
    const packet = new PacketBuilder()
      .from('sales-01', 'SalesBot', { framework: 'langchain', version: '0.1.0' })
      .to('billing-01', 'BillingBot', { framework: 'crewai' })
      .withSummary('test')
      .build();

    expect(packet.metadata.source_agent.framework).toBe('langchain');
    expect(packet.metadata.source_agent.version).toBe('0.1.0');
    expect(packet.metadata.target_agent.framework).toBe('crewai');
  });

  it('should add conversation entries', () => {
    const packet = new PacketBuilder()
      .from('a', 'Agent A')
      .to('b', 'Agent B')
      .withSummary('test')
      .withConversation([
        { role: 'user', content: 'Hello' },
        { role: 'agent', content: 'Hi there' },
      ])
      .build();

    expect(packet.context.conversation_state).toHaveLength(2);
    expect(packet.context.conversation_state![0].role).toBe('user');
    expect(packet.context.conversation_state![0].content).toBe('Hello');
  });

  it('should add individual conversation entries', () => {
    const packet = new PacketBuilder()
      .from('a', 'Agent A')
      .to('b', 'Agent B')
      .withSummary('test')
      .addConversationEntry('user', 'Question?')
      .addConversationEntry('agent', 'Answer!', { foo: 'bar' })
      .build();

    expect(packet.context.conversation_state).toHaveLength(2);
    expect(packet.context.conversation_state![1].metadata).toEqual({ foo: 'bar' });
  });

  it('should add decisions', () => {
    const packet = new PacketBuilder()
      .from('a', 'Agent A')
      .to('b', 'Agent B')
      .withSummary('test')
      .withDecision('Proceed', { rationale: 'Good to go', alternatives: ['Reject'] })
      .withDecision('Escalate', { decided_by: 'manager' })
      .build();

    expect(packet.decisions).toHaveLength(2);
    expect(packet.decisions![0].id).toBe('d1');
    expect(packet.decisions![0].decision).toBe('Proceed');
    expect(packet.decisions![0].alternatives).toEqual(['Reject']);
    expect(packet.decisions![1].id).toBe('d2');
    expect(packet.decisions![1].decided_by).toBe('manager');
  });

  it('should add pending actions', () => {
    const packet = new PacketBuilder()
      .from('a', 'Agent A')
      .to('b', 'Agent B')
      .withSummary('test')
      .withAction({
        description: 'Process payment',
        assignee: 'billing-01',
        priority: 'high',
        depends_on: ['d1'],
      })
      .build();

    expect(packet.actions?.pending).toHaveLength(1);
    expect(packet.actions!.pending![0].description).toBe('Process payment');
    expect(packet.actions!.pending![0].priority).toBe('high');
    expect(packet.actions!.pending![0].depends_on).toEqual(['d1']);
  });

  it('should add dependencies', () => {
    const packet = new PacketBuilder()
      .from('a', 'Agent A')
      .to('b', 'Agent B')
      .withSummary('test')
      .withDependency({
        id: 'stripe',
        type: 'api',
        description: 'Payment gateway',
        status: 'available',
        source: 'system',
      })
      .build();

    expect(packet.dependencies).toHaveLength(1);
    expect(packet.dependencies![0].type).toBe('api');
    expect(packet.dependencies![0].source).toBe('system');
  });

  it('should add HITL checkpoint', () => {
    const packet = new PacketBuilder()
      .from('a', 'Agent A')
      .to('b', 'Agent B')
      .withSummary('test')
      .withHitl({
        reason: 'High-value transaction',
        question: 'Approve payment of $10,000?',
        options: ['yes', 'no'],
        timeout_seconds: 300,
      })
      .build();

    expect(packet.hitl).toBeDefined();
    expect(packet.hitl!.reason).toBe('High-value transaction');
    expect(packet.hitl!.question).toBe('Approve payment of $10,000?');
    expect(packet.hitl!.timeout_seconds).toBe(300);
  });

  it('should set parent packet ID', () => {
    const packet = new PacketBuilder()
      .from('a', 'Agent A')
      .to('b', 'Agent B')
      .withSummary('test')
      .withParent('parent-123')
      .build();

    expect(packet.parent_packet_id).toBe('parent-123');
  });

  it('should set custom context', () => {
    const packet = new PacketBuilder()
      .from('a', 'Agent A')
      .to('b', 'Agent B')
      .withSummary('test')
      .withCustom({ source_language: 'en', confidence: 0.95 })
      .build();

    expect(packet.context.custom).toEqual({ source_language: 'en', confidence: 0.95 });
  });

  it('should support method chaining', () => {
    const packet = new PacketBuilder()
      .from('a', 'A')
      .to('b', 'B')
      .withSummary('chain test')
      .withPriority('critical')
      .withTags(['test'])
      .withConversation([{ role: 'user', content: 'hi' }])
      .withDecision('Go', { rationale: 'ok' })
      .withAction({ description: 'Do it', assignee: 'b' })
      .withDependency({ id: 'dep1', type: 'data', description: 'some data' })
      .withHitl({ reason: 'reason' })
      .build();

    expect(packet).toBeDefined();
    expect(packet.metadata.priority).toBe('critical');
    expect(packet.decisions).toHaveLength(1);
    expect(packet.actions?.pending).toHaveLength(1);
    expect(packet.dependencies).toHaveLength(1);
    expect(packet.hitl).toBeDefined();
  });
});

describe('ChainBuilder', () => {
  it('should build a minimal valid chain request', () => {
    const request = new ChainBuilder()
      .from('billing-01', 'BillingBot')
      .to('followup-01', 'FollowUpBot')
      .withSummary('Follow up on upgrade')
      .build();

    expect(request.metadata.source_agent.id).toBe('billing-01');
    expect(request.metadata.target_agent.id).toBe('followup-01');
    expect(request.context.summary).toBe('Follow up on upgrade');
  });

  it('should throw when source agent is missing', () => {
    expect(() => {
      new ChainBuilder()
        .to('b', 'B')
        .withSummary('test')
        .build();
    }).toThrow('Source agent is required');
  });

  it('should throw when target agent is missing', () => {
    expect(() => {
      new ChainBuilder()
        .from('a', 'A')
        .withSummary('test')
        .build();
    }).toThrow('Target agent is required');
  });

  it('should throw when summary is missing', () => {
    expect(() => {
      new ChainBuilder()
        .from('a', 'A')
        .to('b', 'B')
        .build();
    }).toThrow('Summary is required');
  });

  it('should add actions, decisions, and HITL', () => {
    const request = new ChainBuilder()
      .from('a', 'A')
      .to('b', 'B')
      .withSummary('chain test')
      .withDecision('Proceed', { rationale: 'Ready' })
      .withAction({ description: 'Do work', assignee: 'b' })
      .withDependency({ id: 'd1', type: 'api', description: 'API call' })
      .withHitl({ reason: 'Check required' })
      .build();

    expect(request.decisions).toHaveLength(1);
    expect(request.actions?.pending).toHaveLength(1);
    expect(request.dependencies).toHaveLength(1);
    expect(request.hitl).toBeDefined();
  });
});
