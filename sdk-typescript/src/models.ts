/**
 * HandoffRail SDK — Data models that mirror the server's Pydantic schemas.
 *
 * These models are plain TypeScript interfaces with factory helpers for
 * serialization/deserialization. They intentionally avoid class-based
 * models for simplicity and tree-shaking compatibility.
 *
 * @module
 */

// ── Enums ────────────────────────────────────────────────────────────────

/** Packet priority levels. */
export type Priority = 'low' | 'normal' | 'high' | 'critical';

/** Standard packet status values. */
export type PacketStatus =
  | 'created'
  | 'claimed'
  | 'in_progress'
  | 'awaiting_human'
  | 'completed'
  | 'failed'
  | 'expired';

/** Role identifiers for conversation entries. */
export type ConversationRole = 'user' | 'agent' | 'system' | 'human';

/** Dependency type identifiers. */
export type DependencyType =
  | 'data'
  | 'api'
  | 'human_approval'
  | 'external_event'
  | 'resource';

/** Dependency status values. */
export type DependencyStatus = 'blocked' | 'available' | 'unknown';

// ── Helper functions ─────────────────────────────────────────────────────

/** Create an ISO-8601 timestamp string for "now" in UTC. */
export function nowISO(): string {
  return new Date().toISOString();
}

/** Remove keys with `undefined` or `null` values from an object. */
export function excludeNil<T extends Record<string, unknown>>(obj: T): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    if (value !== undefined && value !== null) {
      result[key] = value;
    }
  }
  return result;
}

// ── Nested Data Models ───────────────────────────────────────────────────

/** Agent identity information. */
export interface AgentInfo {
  id: string;
  name: string;
  framework?: string;
  version?: string;
}

/** Target agent identity — framework is optional. */
export interface TargetAgentInfo {
  id: string;
  name: string;
  framework?: string;
}

/** A single conversation turn in the packet context. */
export interface ContextEntry {
  role: ConversationRole;
  content: string;
  timestamp?: string;
  metadata?: Record<string, unknown>;
}

/** A named artifact produced during the session. */
export interface Artifact {
  key: string;
  value: string | Record<string, unknown> | unknown[];
  content_type?: string;
}

/** A decision made during the session. */
export interface Decision {
  id: string;
  decision: string;
  rationale: string;
  alternatives?: string[];
  decided_by?: string;
  timestamp?: string;
}

/** A pending action to be handled by the target agent. */
export interface PendingAction {
  id: string;
  description: string;
  assignee: string;
  priority?: Priority;
  depends_on?: string[];
  deadline?: string;
}

/** A completed action. */
export interface CompletedAction {
  id: string;
  description: string;
  result: string;
  completed_by?: string;
  completed_at?: string;
}

/** A failed action. */
export interface FailedAction {
  id: string;
  description: string;
  error: string;
  retries_remaining?: number;
}

/** All actions associated with the packet. */
export interface Actions {
  pending?: PendingAction[];
  completed?: CompletedAction[];
  failed?: FailedAction[];
}

/** An external dependency the receiving agent should know about. */
export interface Dependency {
  id: string;
  type: DependencyType;
  description: string;
  status?: DependencyStatus;
  source?: string;
}

/** Human-in-the-loop checkpoint. */
export interface HitlCheckpoint {
  required: boolean;
  reason: string;
  question?: string;
  options?: string[];
  response?: string;
  responded_at?: string;
  responded_by?: string;
  notes?: string;
  timeout_seconds?: number;
}

/** Packet metadata — source/target agents, timestamps, priority. */
export interface Metadata {
  source_agent: AgentInfo;
  target_agent: TargetAgentInfo;
  created_at?: string;
  claimed_at?: string;
  completed_at?: string;
  priority?: Priority;
  tags?: string[];
}

/** The context section of a handoff packet. */
export interface PacketContext {
  summary: string;
  conversation_state?: ContextEntry[];
  artifacts?: Artifact[];
  custom?: Record<string, unknown>;
}

// ── Request / Response Models ────────────────────────────────────────────

/** Request body for creating a new handoff packet. */
export interface PacketCreate {
  parent_packet_id?: string;
  metadata: Metadata;
  context: PacketContext;
  decisions?: Decision[];
  actions?: Actions;
  dependencies?: Dependency[];
  hitl?: HitlCheckpoint;
  schema_id?: string;
}

/** Full packet response returned from the API. */
export interface PacketResponse {
  id: string;
  version?: string;
  parent_packet_id?: string;
  metadata: Metadata;
  context: PacketContext;
  decisions?: Decision[];
  actions?: Actions;
  dependencies?: Dependency[];
  hitl?: HitlCheckpoint;
  status: PacketStatus;
  created_at: string;
  updated_at: string;
}

/** Paginated list of packet responses. */
export interface PacketListResponse {
  packets: PacketResponse[];
  total: number;
  limit: number;
  offset: number;
  next_cursor?: string;
}

/** Request body for claiming a packet. */
export interface PacketClaim {
  agent_id: string;
  agent_name: string;
  framework?: string;
}

/** Request body for partially updating a packet. */
export interface PacketUpdate {
  status?: PacketStatus;
  context?: PacketContext;
  decisions?: Decision[];
  actions?: Actions;
  dependencies?: Dependency[];
  hitl?: HitlCheckpoint;
  schema_id?: string;
}

/** A single event in the packet history audit trail. */
export interface PacketEvent {
  id: string;
  packet_id: string;
  event_type: string;
  actor: string;
  details?: Record<string, unknown>;
  timestamp: string;
}

/** Response for packet event history. */
export interface PacketHistoryResponse {
  packet_id: string;
  events: PacketEvent[];
}

/** Structured audit log entry. */
export interface AuditLogEntry {
  id: string;
  packet_id: string;
  actor: string;
  action: string;
  resource: string;
  details?: Record<string, unknown>;
  timestamp: string;
}

/** Paginated structured audit log response. */
export interface AuditLogResponse {
  entries: AuditLogEntry[];
  total: number;
  limit: number;
  offset: number;
}

/** Request body for responding to a HITL checkpoint. */
export interface HitlRespondRequest {
  response: string;
  responded_by: string;
  notes?: string;
}

/** Request body for creating a chained follow-up packet. */
export interface ChainHandoffRequest {
  metadata: Metadata;
  context: PacketContext;
  decisions?: Decision[];
  actions?: Actions;
  dependencies?: Dependency[];
  hitl?: HitlCheckpoint;
  schema_id?: string;
}

/** Request body for registering a webhook. */
export interface WebhookCreate {
  url: string;
  events?: string[];
  secret: string;
}

/** Response for a registered webhook. */
export interface WebhookResponse {
  id: string;
  url: string;
  events: string[];
  tenant_id: string;
  active: boolean;
  created_at: string;
}

// ── Factory helpers ──────────────────────────────────────────────────────

/** Options for listing packets. */
export interface ListPacketsOptions {
  status?: string;
  source_agent?: string;
  target_agent?: string;
  tags?: string;
  priority?: string;
  created_after?: string;
  created_before?: string;
  limit?: number;
  offset?: number;
  cursor?: string;
}

/** Options for listing audit log entries. */
export interface ListAuditOptions {
  actor?: string;
  action?: string;
  packet_id?: string;
  created_after?: string;
  created_before?: string;
  limit?: number;
  offset?: number;
}

/** Webhook delivery history entry. */
export interface WebhookDelivery {
  id: string;
  webhook_id: string;
  packet_id: string;
  event_type: string;
  status: string;
  attempts: number;
  last_error?: string | null;
  last_status_code?: number | null;
  next_retry_at?: string | null;
  delivered_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** Options for claiming a packet. */
export interface ClaimPacketOptions {
  agent_id: string;
  agent_name: string;
  framework?: string;
}

/** Options for responding to HITL. */
export interface HitlRespondOptions {
  response: string;
  responded_by: string;
  notes?: string;
}

/** Options for registering a webhook. */
export interface RegisterWebhookOptions {
  url: string;
  events?: string[];
  secret: string;
}

// ── Serialization helpers ────────────────────────────────────────────────

/**
 * Serialize a Metadata object to a plain JSON-compatible dictionary.
 */
export function serializeMetadata(m: Metadata): Record<string, unknown> {
  return excludeNil({
    source_agent: m.source_agent,
    target_agent: m.target_agent,
    created_at: m.created_at,
    claimed_at: m.claimed_at,
    completed_at: m.completed_at,
    priority: m.priority,
    tags: m.tags,
  });
}

/**
 * Serialize a PacketContext object to a plain JSON-compatible dictionary.
 */
export function serializePacketContext(ctx: PacketContext): Record<string, unknown> {
  return excludeNil({
    summary: ctx.summary,
    conversation_state: ctx.conversation_state,
    artifacts: ctx.artifacts,
    custom: ctx.custom,
  });
}

/**
 * Serialize a PacketCreate to a plain JSON-compatible dictionary.
 */
export function serializePacketCreate(p: PacketCreate): Record<string, unknown> {
  return excludeNil({
    parent_packet_id: p.parent_packet_id,
    metadata: serializeMetadata(p.metadata),
    context: serializePacketContext(p.context),
    decisions: p.decisions,
    actions: p.actions,
    dependencies: p.dependencies,
    hitl: p.hitl,
    schema_id: p.schema_id,
  });
}

/**
 * Serialize a PacketUpdate to a plain JSON-compatible dictionary.
 */
export function serializePacketUpdate(p: PacketUpdate): Record<string, unknown> {
  return excludeNil({
    status: p.status,
    context: p.context ? serializePacketContext(p.context) : undefined,
    decisions: p.decisions,
    actions: p.actions,
    dependencies: p.dependencies,
    hitl: p.hitl,
    schema_id: p.schema_id,
  });
}

/**
 * Serialize a ChainHandoffRequest to a plain JSON-compatible dictionary.
 */
export function serializeChainHandoffRequest(r: ChainHandoffRequest): Record<string, unknown> {
  return excludeNil({
    metadata: serializeMetadata(r.metadata),
    context: serializePacketContext(r.context),
    decisions: r.decisions,
    actions: r.actions,
    dependencies: r.dependencies,
    hitl: r.hitl,
    schema_id: r.schema_id,
  });
}

// ── Batch Operations ───────────────────────────────────────────────────────────

/**
 * Error entry for a single packet in a batch create response.
 */
export interface BatchCreateError {
  index: number;
  error: string;
}

/**
 * Response for batch packet creation.
 */
export interface BatchCreateResponse {
  created: PacketResponse[];
  errors: BatchCreateError[];
}

/**
 * Options for batch claiming packets.
 */
export interface BatchClaimOptions {
  agentId: string;
  agentName: string;
  framework?: string;
}

/**
 * Error entry for a single packet in a batch claim response.
 */
export interface BatchClaimError {
  packet_id: string;
  error: string;
}

/**
 * Response for batch packet claiming.
 */
export interface BatchClaimResponse {
  claimed: PacketResponse[];
  errors: BatchClaimError[];
}

/**
 * Error entry for a single packet in a batch complete response.
 */
export interface BatchCompleteError {
  packet_id: string;
  error: string;
}

/**
 * Response for batch packet completion.
 */
export interface BatchCompleteResponse {
  completed: PacketResponse[];
  errors: BatchCompleteError[];
}

// ── Search ─────────────────────────────────────────────────────────────────────

/**
 * Options for packet search.
 */
export interface SearchOptions {
  limit?: number;
  offset?: number;
  status?: string;
  priority?: string;
}
