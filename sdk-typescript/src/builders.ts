/**
 * HandoffRail SDK — Fluent builder pattern for constructing packets and chains.
 *
 * Usage:
 * ```typescript
 * const packetData = new PacketBuilder()
 *   .to('billing-01', 'BillingBot', { framework: 'custom' })
 *   .from('sales-01', 'SalesBot', { framework: 'langchain' })
 *   .withSummary('Customer wants Business tier')
 *   .withPriority('high')
 *   .withTags(['upgrade', 'business'])
 *   .withConversation([{ role: 'user', content: 'I want to upgrade' }])
 *   .withDecision('Proceed', { rationale: 'Customer is eligible' })
 *   .withAction({ description: 'Process payment', assignee: 'billing-01', priority: 'high' })
 *   .withDependency({ id: 'stripe', type: 'api', description: 'Payment gateway' })
 *   .withHitl({ reason: 'High-value upgrade needs approval', question: 'Approve?' })
 *   .build();
 * ```
 *
 * @module
 */

import type {
  PacketCreate,
  ChainHandoffRequest,
  Metadata,
  PacketContext,
  AgentInfo,
  TargetAgentInfo,
  ContextEntry,
  Artifact,
  Decision,
  Actions,
  PendingAction,
  CompletedAction,
  FailedAction,
  Dependency,
  HitlCheckpoint,
  Priority,
  ConversationRole,
} from './models';

// ── Helper ────────────────────────────────────────────────────────────────

function asPriority(p: string | Priority): Priority {
  const valid: Priority[] = ['low', 'normal', 'high', 'critical'];
  if (valid.includes(p as Priority)) return p as Priority;
  return 'normal';
}

// ── PacketBuilder ─────────────────────────────────────────────────────────

/**
 * Fluent builder for constructing {@link PacketCreate} payloads.
 *
 * Each method returns `this` so calls can be chained. Call {@link build}
 * at the end to get a validated {@link PacketCreate} object.
 */
export class PacketBuilder {
  protected _sourceId?: string;
  protected _sourceName?: string;
  protected _sourceFramework?: string;
  protected _sourceVersion?: string;
  protected _targetId?: string;
  protected _targetName?: string;
  protected _targetFramework?: string;
  protected _summary?: string;
  protected _priority: Priority = 'normal';
  protected _tags: string[] = [];
  protected _conversationState: ContextEntry[] = [];
  protected _artifacts: Artifact[] = [];
  protected _custom: Record<string, unknown> = {};
  protected _decisions: Decision[] = [];
  protected _pendingActions: PendingAction[] = [];
  protected _completedActions: CompletedAction[] = [];
  protected _failedActions: FailedAction[] = [];
  protected _dependencies: Dependency[] = [];
  protected _hitl?: HitlCheckpoint;
  protected _parentPacketId?: string;

  // ── Agent setters ────────────────────────────────────────────────────

  /**
   * Set the source (sending) agent.
   */
  from(agentId: string, agentName: string, options?: { framework?: string; version?: string }): this {
    this._sourceId = agentId;
    this._sourceName = agentName;
    this._sourceFramework = options?.framework;
    this._sourceVersion = options?.version;
    return this;
  }

  /**
   * Set the target (receiving) agent.
   */
  to(agentId: string, agentName: string, options?: { framework?: string }): this {
    this._targetId = agentId;
    this._targetName = agentName;
    this._targetFramework = options?.framework;
    return this;
  }

  // ── Context setters ──────────────────────────────────────────────────

  /** Set the context summary. */
  withSummary(summary: string): this {
    this._summary = summary;
    return this;
  }

  /** Set the packet priority. */
  withPriority(priority: string | Priority): this {
    this._priority = asPriority(priority);
    return this;
  }

  /** Set tags for filtering. */
  withTags(tags: string[]): this {
    this._tags = [...tags];
    return this;
  }

  /** Set the conversation state from a list of message-like entries. */
  withConversation(messages: ContextEntry[]): this {
    this._conversationState = [...messages];
    return this;
  }

  /** Add a single conversation entry. */
  addConversationEntry(role: ConversationRole, content: string, metadata?: Record<string, unknown>): this {
    this._conversationState.push({ role, content, metadata });
    return this;
  }

  /** Set named artifacts produced during the session. */
  withArtifacts(artifacts: Artifact[]): this {
    this._artifacts = [...artifacts];
    return this;
  }

  /** Set framework-specific custom context fields. */
  withCustom(custom: Record<string, unknown>): this {
    this._custom = { ...custom };
    return this;
  }

  // ── Decision / Action / Dependency helpers ───────────────────────────

  /**
   * Add a decision to the packet. An auto-incrementing ID is assigned.
   */
  withDecision(
    decision: string,
    options?: {
      rationale?: string;
      alternatives?: string[];
      decided_by?: string;
    },
  ): this {
    const id = `d${this._decisions.length + 1}`;
    this._decisions.push({
      id,
      decision,
      rationale: options?.rationale ?? '',
      alternatives: options?.alternatives,
      decided_by: options?.decided_by,
    });
    return this;
  }

  /**
   * Add a pending action to the packet.
   */
  withAction(options: {
    description: string;
    assignee: string;
    priority?: string | Priority;
    depends_on?: string[];
    action_id?: string;
  }): this {
    const id = options.action_id ?? `a${this._pendingActions.length + 1}`;
    this._pendingActions.push({
      id,
      description: options.description,
      assignee: options.assignee,
      priority: options.priority ? asPriority(options.priority) : undefined,
      depends_on: options.depends_on,
    });
    return this;
  }

  /**
   * Add an external dependency.
   */
  withDependency(options: {
    id: string;
    type?: 'data' | 'api' | 'human_approval' | 'external_event' | 'resource';
    description?: string;
    status?: 'blocked' | 'available' | 'unknown';
    source?: string;
  }): this {
    this._dependencies.push({
      id: options.id,
      type: options.type ?? 'api',
      description: options.description ?? '',
      status: options.status ?? 'unknown',
      source: options.source,
    });
    return this;
  }

  // ── HITL ─────────────────────────────────────────────────────────────

  /**
   * Add a human-in-the-loop checkpoint.
   */
  withHitl(options: {
    reason: string;
    question?: string;
    options?: string[];
    timeout_seconds?: number;
    required?: boolean;
  }): this {
    this._hitl = {
      required: options.required ?? true,
      reason: options.reason,
      question: options.question,
      options: options.options,
      timeout_seconds: options.timeout_seconds,
    };
    return this;
  }

  // ── Parent ───────────────────────────────────────────────────────────

  /** Set the parent packet ID for chained handoffs. */
  withParent(parentPacketId: string): this {
    this._parentPacketId = parentPacketId;
    return this;
  }

  // ── Build ────────────────────────────────────────────────────────────

  /**
   * Validate accumulated data and return a {@link PacketCreate} object.
   *
   * @throws {Error} If required fields (source agent, target agent, summary) are missing.
   */
  build(): PacketCreate {
    if (!this._sourceId || !this._sourceName) {
      throw new Error('Source agent is required. Call .from() before .build().');
    }
    if (!this._targetId || !this._targetName) {
      throw new Error('Target agent is required. Call .to() before .build().');
    }
    if (!this._summary) {
      throw new Error('Summary is required. Call .withSummary() before .build().');
    }

    const sourceAgent: AgentInfo = {
      id: this._sourceId,
      name: this._sourceName,
      framework: this._sourceFramework,
      version: this._sourceVersion,
    };

    const targetAgent: TargetAgentInfo = {
      id: this._targetId,
      name: this._targetName,
      framework: this._targetFramework,
    };

    const metadata: Metadata = {
      source_agent: sourceAgent,
      target_agent: targetAgent,
      priority: this._priority,
      tags: this._tags,
    };

    const context: PacketContext = {
      summary: this._summary,
      conversation_state: this._conversationState.length > 0 ? this._conversationState : undefined,
      artifacts: this._artifacts.length > 0 ? this._artifacts : undefined,
      custom: Object.keys(this._custom).length > 0 ? this._custom : undefined,
    };

    const actions: Actions = {
      pending: this._pendingActions.length > 0 ? this._pendingActions : undefined,
      completed: this._completedActions.length > 0 ? this._completedActions : undefined,
      failed: this._failedActions.length > 0 ? this._failedActions : undefined,
    };

    // Only include actions if at least one list is non-empty
    const actionsMaybe = actions.pending || actions.completed || actions.failed ? actions : undefined;

    return {
      parent_packet_id: this._parentPacketId,
      metadata,
      context,
      decisions: this._decisions.length > 0 ? this._decisions : undefined,
      actions: actionsMaybe,
      dependencies: this._dependencies.length > 0 ? this._dependencies : undefined,
      hitl: this._hitl,
    };
  }
}

// ── ChainBuilder ──────────────────────────────────────────────────────────

/**
 * Fluent builder for constructing {@link ChainHandoffRequest} payloads.
 *
 * Similar to {@link PacketBuilder} but produces a {@link ChainHandoffRequest}
 * (no `parent_packet_id` — that is provided as a separate argument to
 * the client method).
 */
export class ChainBuilder {
  protected _sourceId?: string;
  protected _sourceName?: string;
  protected _sourceFramework?: string;
  protected _targetId?: string;
  protected _targetName?: string;
  protected _targetFramework?: string;
  protected _summary?: string;
  protected _priority: Priority = 'normal';
  protected _tags: string[] = [];
  protected _conversationState: ContextEntry[] = [];
  protected _artifacts: Artifact[] = [];
  protected _custom: Record<string, unknown> = {};
  protected _decisions: Decision[] = [];
  protected _pendingActions: PendingAction[] = [];
  protected _dependencies: Dependency[] = [];
  protected _hitl?: HitlCheckpoint;

  /** Set the source (sending) agent. */
  from(agentId: string, agentName: string, options?: { framework?: string }): this {
    this._sourceId = agentId;
    this._sourceName = agentName;
    this._sourceFramework = options?.framework;
    return this;
  }

  /** Set the target (receiving) agent. */
  to(agentId: string, agentName: string, options?: { framework?: string }): this {
    this._targetId = agentId;
    this._targetName = agentName;
    this._targetFramework = options?.framework;
    return this;
  }

  /** Set the context summary. */
  withSummary(summary: string): this {
    this._summary = summary;
    return this;
  }

  /** Set the packet priority. */
  withPriority(priority: string | Priority): this {
    this._priority = asPriority(priority);
    return this;
  }

  /** Set tags for filtering. */
  withTags(tags: string[]): this {
    this._tags = [...tags];
    return this;
  }

  /** Set the conversation state. */
  withConversation(messages: ContextEntry[]): this {
    this._conversationState = [...messages];
    return this;
  }

  /** Set artifacts. */
  withArtifacts(artifacts: Artifact[]): this {
    this._artifacts = [...artifacts];
    return this;
  }

  /** Set custom context. */
  withCustom(custom: Record<string, unknown>): this {
    this._custom = { ...custom };
    return this;
  }

  /** Add a decision. */
  withDecision(
    decision: string,
    options?: { rationale?: string; decided_by?: string },
  ): this {
    const id = `d${this._decisions.length + 1}`;
    this._decisions.push({
      id,
      decision,
      rationale: options?.rationale ?? '',
      decided_by: options?.decided_by,
    });
    return this;
  }

  /** Add a pending action. */
  withAction(options: { description: string; assignee: string; priority?: string | Priority }): this {
    const id = `a${this._pendingActions.length + 1}`;
    this._pendingActions.push({
      id,
      description: options.description,
      assignee: options.assignee,
      priority: options.priority ? asPriority(options.priority) : undefined,
    });
    return this;
  }

  /** Add an external dependency. */
  withDependency(options: { id: string; type?: 'data' | 'api' | 'human_approval' | 'external_event' | 'resource'; description?: string }): this {
    this._dependencies.push({
      id: options.id,
      type: options.type ?? 'api',
      description: options.description ?? '',
      status: 'unknown',
    });
    return this;
  }

  /** Add a HITL checkpoint. */
  withHitl(options: { reason: string; question?: string; options?: string[] }): this {
    this._hitl = {
      required: true,
      reason: options.reason,
      question: options.question,
      options: options.options,
    };
    return this;
  }

  /**
   * Validate and return a {@link ChainHandoffRequest}.
   *
   * @throws {Error} If required fields are missing.
   */
  build(): ChainHandoffRequest {
    if (!this._sourceId || !this._sourceName) {
      throw new Error('Source agent is required. Call .from() before .build().');
    }
    if (!this._targetId || !this._targetName) {
      throw new Error('Target agent is required. Call .to() before .build().');
    }
    if (!this._summary) {
      throw new Error('Summary is required. Call .withSummary() before .build().');
    }

    const metadata: Metadata = {
      source_agent: { id: this._sourceId, name: this._sourceName, framework: this._sourceFramework },
      target_agent: { id: this._targetId, name: this._targetName, framework: this._targetFramework },
      priority: this._priority,
      tags: this._tags,
    };

    const context: PacketContext = {
      summary: this._summary,
      conversation_state: this._conversationState.length > 0 ? this._conversationState : undefined,
      artifacts: this._artifacts.length > 0 ? this._artifacts : undefined,
      custom: Object.keys(this._custom).length > 0 ? this._custom : undefined,
    };

    const actions: Actions = {
      pending: this._pendingActions.length > 0 ? this._pendingActions : undefined,
    };

    return {
      metadata,
      context,
      decisions: this._decisions.length > 0 ? this._decisions : undefined,
      actions: actions.pending ? actions : undefined,
      dependencies: this._dependencies.length > 0 ? this._dependencies : undefined,
      hitl: this._hitl,
    };
  }
}
