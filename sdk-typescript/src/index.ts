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
  ClaimPacketOptions,
  HitlRespondOptions,
  RegisterWebhookOptions,
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
