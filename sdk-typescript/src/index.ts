/**
 * HandoffRail TypeScript SDK — session-continuity middleware for multi-agent AI workflows.
 *
 * @module
 */

// ── Client ───────────────────────────────────────────────────────────────

export { HandoffRailClient } from './client';
export type { HandoffRailClientOptions } from './client';

// ── Async Client ─────────────────────────────────────────────────────────

export { AsyncHandoffRailClient } from './async-client';
export type { AsyncHandoffRailClientOptions } from './async-client';

// ── WebSocket Client ───────────────────────────────────────────────────

export {
  AsyncWebSocketClient,
  EVENT_PACKET_CREATED,
  EVENT_PACKET_CLAIMED,
  EVENT_PACKET_UPDATED,
  EVENT_PACKET_IN_PROGRESS,
  EVENT_PACKET_AWAITING_HUMAN,
  EVENT_PACKET_COMPLETED,
  EVENT_PACKET_FAILED,
  EVENT_PACKET_EXPIRED,
  EVENT_PACKET_CHAINED,
  EVENT_HITL_RESPONSE_READY,
  ALL_EVENTS,
  WS_CONNECTING,
  WS_OPEN,
  WS_CLOSING,
  WS_CLOSED,
} from './ws-client';

export type {
  HandoffRailEvent,
  EventCallback,
  ConnectedCallback,
  DisconnectedCallback,
  ErrorCallback,
  WebSocketLike,
  WebSocketFactory,
  AsyncWebSocketClientOptions,
} from './ws-client';

// ── Builders ─────────────────────────────────────────────────────────────

export { PacketBuilder, ChainBuilder } from './builders';

// ── Models ───────────────────────────────────────────────────────────────

export type {
  // Enums
  Priority,
  PacketStatus,
  ConversationRole,
  DependencyType,
  DependencyStatus,
  // Core models
  PacketCreate,
  PacketResponse,
  PacketListResponse,
  PacketClaim,
  PacketUpdate,
  PacketHistoryResponse,
  PacketEvent,
  AuditLogEntry,
  AuditLogResponse,
  ChainHandoffRequest,
  HitlRespondRequest,
  WebhookCreate,
  WebhookResponse,
  // Sub-models
  Metadata,
  PacketContext,
  AgentInfo,
  TargetAgentInfo,
  ContextEntry,
  Artifact,
  Decision,
  PendingAction,
  CompletedAction,
  FailedAction,
  Actions,
  Dependency,
  HitlCheckpoint,
  // Options
  ListPacketsOptions,
  ListAuditOptions,
  ClaimPacketOptions,
  HitlRespondOptions,
  RegisterWebhookOptions,
  WebhookDelivery,
  // Batch
  BatchCreateError,
  BatchCreateResponse,
  BatchClaimOptions,
  BatchClaimError,
  BatchClaimResponse,
  BatchCompleteError,
  BatchCompleteResponse,
  SearchOptions,
} from './models';

export {
  nowISO,
  excludeNil,
  serializePacketCreate,
  serializePacketUpdate,
  serializeChainHandoffRequest,
  serializeMetadata,
  serializePacketContext,
} from './models';

// ── Errors ───────────────────────────────────────────────────────────────

export {
  HandoffRailError,
  AuthenticationError,
  NotFoundError,
  ValidationError,
  ConflictError,
  RateLimitError,
  ServerError,
  ConnectionError,
} from './errors';

export type { HandoffRailErrorOptions } from './errors';

// ── Package version ──────────────────────────────────────────────────────

/** The SDK version string. */
export const VERSION: string = '0.2.0';
