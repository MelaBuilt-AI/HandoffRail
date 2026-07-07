/**
 * HandoffRail SDK — Synchronous HTTP client.
 *
 * Uses a child Node.js process (via temp file) to make HTTP requests
 * synchronously. Each request writes a script to a temp file, executes it
 * with `node`, and parses stdout as JSON.
 *
 * Usage:
 * ```typescript
 * import { HandoffRailClient, PacketBuilder } from 'handoffrail-sdk';
 *
 * const client = new HandoffRailClient({
 *   baseUrl: 'http://localhost:8080/api/v1',
 *   apiKey: 'sk-...',
 * });
 *
 * const packet = client.createPacket(
 *   new PacketBuilder()
 *     .to('billing-01', 'BillingBot')
 *     .from('sales-01', 'SalesBot')
 *     .withSummary('Customer wants Business tier')
 *     .build()
 * );
 * ```
 *
 * @module
 */

import { execSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

import type {
  PacketCreate,
  PacketResponse,
  PacketListResponse,
  AuditLogResponse,
  PacketUpdate,
  PacketHistoryResponse,
  ChainHandoffRequest,
  WebhookResponse,
  ListPacketsOptions,
  ListAuditOptions,
  ClaimPacketOptions,
  HitlRespondOptions,
  RegisterWebhookOptions,
  WebhookDelivery,
  BatchCreateResponse,
  BatchClaimOptions,
  BatchClaimResponse,
  BatchCompleteResponse,
  SearchOptions,
} from './models';

import {
  serializePacketCreate,
  serializePacketUpdate,
  serializeChainHandoffRequest,
} from './models';

import {
  HandoffRailError,
  AuthenticationError,
  NotFoundError,
  ValidationError,
  ConflictError,
  RateLimitError,
  ServerError,
  ConnectionError,
} from './errors';

// ── Configuration ────────────────────────────────────────────────────────

/** Configuration options for the HandoffRail client. */
export interface HandoffRailClientOptions {
  /** Base URL of the HandoffRail API (e.g. `http://localhost:8080/api/v1`). */
  baseUrl: string;
  /** API key for authentication (sent as `X-API-Key` header). */
  apiKey: string;
  /** Request timeout in milliseconds (default 30000). */
  timeout?: number;
  /** Maximum number of retries on transient errors (default 3). */
  maxRetries?: number;
  /** Base delay in milliseconds between retries (uses exponential backoff, default 500). */
  retryDelay?: number;
}

// ── Internal types ───────────────────────────────────────────────────────

interface SyncResponse {
  status: number;
  headers: Record<string, string>;
  data: string;
}

// ── Counter for unique temp file names ───────────────────────────────────

let _scriptCounter = 0;

// ── Sync Transport ───────────────────────────────────────────────────────

const SYNC_SCRIPT_DIR = path.join(os.tmpdir(), 'handoffrail-sdk');

/**
 * Build the request script source that will be written to a temp file.
 * Uses the built-in `http`/`https` module in a child process and outputs
 * JSON to stdout.
 */
function buildSyncScript(input: {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: string | null;
}): string {
  const { method, url, headers, body } = input;
  const isHttps = url.startsWith('https:');
  const mod = isHttps ? 'https' : 'http';

  return [
    `const m = require('${mod}');`,
    `const u = new URL(${JSON.stringify(url)});`,
    `const opt = {`,
    `  hostname: u.hostname,`,
    `  port: u.port || ${isHttps ? 443 : 80},`,
    `  path: u.pathname + u.search,`,
    `  method: ${JSON.stringify(method)},`,
    `  headers: ${JSON.stringify(headers)},`,
    `};`,
    `const r = m.request(opt, (res) => {`,
    `  const c = [];`,
    `  res.on('data', (d) => c.push(d));`,
    `  res.on('end', () => {`,
    `    const result = {`,
    `      status: res.statusCode,`,
    `      headers: {},`,
    `      data: Buffer.concat(c).toString('utf-8'),`,
    `    };`,
    `    if (res.headers) {`,
    `      for (const [k, v] of Object.entries(res.headers)) {`,
    `        result.headers[k] = Array.isArray(v) ? v.join(', ') : String(v);`,
    `      }`,
    `    }`,
    `    console.log(JSON.stringify(result));`,
    `  });`,
    `});`,
    `r.on('error', (e) => console.log(JSON.stringify({error: e.message})));`,
    body ? `r.write(${JSON.stringify(body)});` : '',
    `r.end();`,
  ].join('\n');
}

/**
 * Make a synchronous HTTP request by spawning a child Node.js process.
 * Writes a temp script file, executes it, and parses stdout.
 */
function syncHttpRequest(
  method: string,
  url: string,
  headers: Record<string, string>,
  body?: string,
  timeoutMs: number = 30_000,
): SyncResponse {
  // Ensure temp directory exists
  if (!fs.existsSync(SYNC_SCRIPT_DIR)) {
    fs.mkdirSync(SYNC_SCRIPT_DIR, { recursive: true });
  }

  _scriptCounter++;
  const scriptPath = path.join(SYNC_SCRIPT_DIR, `req-${_scriptCounter}-${Date.now()}.js`);
  const script = buildSyncScript({ method, url, headers, body: body ?? null });

  try {
    fs.writeFileSync(scriptPath, script, 'utf-8');

    const stdout = execSync(`"${process.execPath}" "${scriptPath}"`, {
      encoding: 'utf-8',
      timeout: timeoutMs + 10_000,
      maxBuffer: 10 * 1024 * 1024,
      windowsHide: true,
    });

    const parsed = JSON.parse(stdout.trim()) as SyncResponse & { error?: string };

    if (parsed.error) {
      throw new ConnectionError(parsed.error);
    }

    return {
      status: parsed.status,
      headers: parsed.headers,
      data: parsed.data,
    };
  } catch (err) {
    if (err instanceof HandoffRailError) {
      throw err;
    }
    throw new ConnectionError(
      (err as Error).message,
      { originalError: err as Error },
    );
  } finally {
    // Clean up temp file
    try {
      if (fs.existsSync(scriptPath)) {
        fs.unlinkSync(scriptPath);
      }
    } catch {
      // Ignore cleanup errors
    }
  }
}

// ── Client ───────────────────────────────────────────────────────────────

/**
 * Synchronous HTTP client for the HandoffRail API.
 *
 * @remarks
 * All methods make blocking HTTP calls. For non-blocking usage, see
 * {@link AsyncHandoffRailClient}.
 */
export class HandoffRailClient {
  public readonly baseUrl: string;
  public readonly apiKey: string;
  public readonly timeout: number;
  public readonly maxRetries: number;
  public readonly retryDelay: number;

  constructor(options: HandoffRailClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.apiKey = options.apiKey;
    this.timeout = options.timeout ?? 30_000;
    this.maxRetries = options.maxRetries ?? 3;
    this.retryDelay = options.retryDelay ?? 500;
  }

  /** No-op for sync client; exists for interface compatibility. */
  close(): void {
    // Nothing to clean up
  }

  // ── Internal helpers ──────────────────────────────────────────────────

  /**
   * Make an HTTP request with retry logic and error mapping.
   */
  protected _request(
    method: string,
    path: string,
    options?: {
      jsonData?: Record<string, unknown>;
      params?: Record<string, string | number | undefined>;
    },
  ): Record<string, unknown> | Record<string, unknown>[] {
    const url = new URL(`${this.baseUrl}${path}`);

    if (options?.params) {
      for (const [key, value] of Object.entries(options.params)) {
        if (value !== undefined && value !== null) {
          url.searchParams.set(key, String(value));
        }
      }
    }

    const headers: Record<string, string> = {
      'X-API-Key': this.apiKey,
    };

    let body: string | undefined;
    if (options?.jsonData !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(options.jsonData);
    }

    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        const response = syncHttpRequest(method, url.toString(), headers, body, this.timeout);
        return this._handleResponse(response, url.toString());
      } catch (err) {
        if (err instanceof HandoffRailError) {
          throw err;
        }
        lastError = err as Error;
        if (attempt < this.maxRetries) {
          const backoff = this.retryDelay * Math.pow(2, attempt);
          this._sleep(backoff);
          continue;
        }
      }
    }

    throw new ConnectionError(
      `Unable to connect to HandoffRail server after ${this.maxRetries + 1} attempts`,
      { originalError: lastError ?? undefined },
    );
  }

  /**
   * Handle the HTTP response and map status codes to SDK errors.
   */
  private _handleResponse(
    response: SyncResponse,
    url: string,
  ): Record<string, unknown> | Record<string, unknown>[] {
    const { status, headers, data } = response;

    // Parse the response body
    let body: Record<string, unknown> | Record<string, unknown>[] | null = null;
    try {
      if (data) {
        const parsed = JSON.parse(data);
        if (Array.isArray(parsed)) {
          body = parsed;
        } else if (typeof parsed === 'object' && parsed !== null) {
          body = parsed as Record<string, unknown>;
        }
      }
    } catch {
      body = { raw: data };
    }

    const responseBody = (body as Record<string, unknown>) ?? {};

    // Map HTTP status codes to SDK errors
    if (status === 401) {
      throw new AuthenticationError(
        (responseBody.detail as string) ?? 'Authentication failed',
        { responseBody },
      );
    }
    if (status === 404 || status === 410) {
      throw new NotFoundError(
        (responseBody.detail as string) ?? 'Resource not found',
        { statusCode: status, responseBody, resourceId: url },
      );
    }
    if (status === 400) {
      throw new ValidationError(
        (responseBody.detail as string) ?? 'Validation error',
        { field: responseBody.field as string | undefined, responseBody },
      );
    }
    if (status === 409) {
      const detail = responseBody.detail ?? responseBody;
      throw new ConflictError(
        typeof detail === 'string' ? detail : 'Resource conflict',
        { responseBody },
      );
    }
    if (status === 429) {
      const retryHeader = headers['retry-after'];
      const retryAfter = Array.isArray(retryHeader) ? retryHeader[0] : retryHeader;
      throw new RateLimitError(
        'Rate limit exceeded',
        { retryAfter: retryAfter ? parseInt(retryAfter, 10) : undefined, responseBody },
      );
    }
    if (status >= 500) {
      throw new ServerError(
        `Server error: ${status}`,
        { statusCode: status, responseBody },
      );
    }
    if (status === 204) {
      return {};
    }

    // Success
    return body ?? {};
  }

  /**
   * Synchronous sleep between retries.
   */
  private _sleep(ms: number): void {
    const deadline = Date.now() + ms;
    while (Date.now() < deadline) {
      // Busy-wait — not ideal but acceptable for retry delays
    }
  }

  // ── Packet CRUD ────────────────────────────────────────────────────────

  /** Create a new handoff packet. */
  createPacket(packet: PacketCreate): PacketResponse {
    const data = this._request('POST', '/packets', {
      jsonData: serializePacketCreate(packet) as Record<string, unknown>,
    });
    return this._toPacketResponse(data);
  }

  /** Get a single packet by ID. */
  getPacket(packetId: string): PacketResponse {
    const data = this._request('GET', `/packets/${encodeURIComponent(packetId)}`);
    return this._toPacketResponse(data);
  }

  /** List packets with filtering and pagination. */
  listPackets(options?: ListPacketsOptions): PacketListResponse {
    const params: Record<string, string | number | undefined> = {
      limit: options?.limit ?? 50,
      offset: options?.offset ?? 0,
    };
    if (options?.status) params.status = options.status;
    if (options?.source_agent) params.source_agent = options.source_agent;
    if (options?.target_agent) params.target_agent = options.target_agent;
    if (options?.tags) params.tags = options.tags;
    if (options?.priority) params.priority = options.priority;
    if (options?.created_after) params.created_after = options.created_after;
    if (options?.created_before) params.created_before = options.created_before;
    if (options?.cursor) params.cursor = options.cursor;

    const data = this._request('GET', '/packets', { params });
    return this._toPacketListResponse(data);
  }

  /** List structured audit log entries. */
  listAuditLog(options?: ListAuditOptions): AuditLogResponse {
    const params: Record<string, string | number | undefined> = {
      limit: options?.limit ?? 50,
      offset: options?.offset ?? 0,
    };
    if (options?.actor) params.actor = options.actor;
    if (options?.action) params.action = options.action;
    if (options?.packet_id) params.packet_id = options.packet_id;
    if (options?.created_after) params.created_after = options.created_after;
    if (options?.created_before) params.created_before = options.created_before;

    const data = this._request('GET', '/audit', { params });
    return data as unknown as AuditLogResponse;
  }

  /** Claim a packet for processing. */
  claimPacket(packetId: string, options: ClaimPacketOptions): PacketResponse {
    const data = this._request('POST', `/packets/${encodeURIComponent(packetId)}/claim`, {
      jsonData: {
        agent_id: options.agent_id,
        agent_name: options.agent_name,
        framework: options.framework,
      },
    });
    return this._toPacketResponse(data);
  }

  /** Partially update a packet. */
  updatePacket(packetId: string, update: PacketUpdate): PacketResponse {
    const data = this._request('PATCH', `/packets/${encodeURIComponent(packetId)}`, {
      jsonData: serializePacketUpdate(update) as Record<string, unknown>,
    });
    return this._toPacketResponse(data);
  }

  /** Mark a packet as completed. */
  completePacket(packetId: string): PacketResponse {
    return this.updatePacket(packetId, { status: 'completed' });
  }

  /** Soft-delete a packet (marks as expired). */
  deletePacket(packetId: string): void {
    this._request('DELETE', `/packets/${encodeURIComponent(packetId)}`);
  }

  /** Submit a human response to a HITL checkpoint. */
  respondToHitl(packetId: string, options: HitlRespondOptions): PacketResponse {
    const data = this._request('POST', `/packets/${encodeURIComponent(packetId)}/respond`, {
      jsonData: {
        response: options.response,
        responded_by: options.responded_by,
        notes: options.notes,
      },
    });
    return this._toPacketResponse(data);
  }

  /** Get packets awaiting human review. */
  listAwaitingHuman(options?: { limit?: number; offset?: number }): PacketListResponse {
    const params: Record<string, string | number | undefined> = {
      limit: options?.limit ?? 50,
      offset: options?.offset ?? 0,
    };
    const data = this._request('GET', '/packets/awaiting', { params });
    return this._toPacketListResponse(data);
  }

  /** Get the event history for a packet. */
  getPacketHistory(packetId: string): PacketHistoryResponse {
    const data = this._request('GET', `/packets/${encodeURIComponent(packetId)}/history`);
    return this._toPacketHistoryResponse(data);
  }

  /** Create a chained follow-up packet. */
  chainPacket(parentPacketId: string, request: ChainHandoffRequest): PacketResponse {
    const data = this._request(
      'POST',
      `/packets/${encodeURIComponent(parentPacketId)}/chain`,
      { jsonData: serializeChainHandoffRequest(request) as Record<string, unknown> },
    );
    return this._toPacketResponse(data);
  }

  // ── Webhook CRUD ───────────────────────────────────────────────────────

  /** Register a new webhook. */
  registerWebhook(options: RegisterWebhookOptions): WebhookResponse {
    const data = this._request('POST', '/hooks', {
      jsonData: {
        url: options.url,
        events: options.events ?? [
          'packet.created',
          'packet.claimed',
          'packet.completed',
          'packet.failed',
        ],
        secret: options.secret,
      },
    });
    return this._toWebhookResponse(data);
  }

  /** List all webhooks for the authenticated tenant. */
  listWebhooks(): WebhookResponse[] {
    const data = this._request('GET', '/hooks');
    if (Array.isArray(data)) {
      return data.map((w) => this._toWebhookResponse(w));
    }
    return [];
  }

  /** Deactivate (soft-delete) a webhook. */
  deleteWebhook(webhookId: string): void {
    this._request('DELETE', `/hooks/${encodeURIComponent(webhookId)}`);
  }

  /** List delivery history for one webhook. */
  listWebhookDeliveries(
    webhookId: string,
    options?: { status?: string; limit?: number; offset?: number },
  ): WebhookDelivery[] {
    const params: Record<string, string | number | undefined> = {
      limit: options?.limit ?? 50,
      offset: options?.offset ?? 0,
    };
    if (options?.status) params.status = options.status;

    const data = this._request('GET', `/hooks/${encodeURIComponent(webhookId)}/deliveries`, { params });
    return Array.isArray(data) ? (data as unknown as WebhookDelivery[]) : [];
  }

  // ── Batch Operations ───────────────────────────────────────────────────

  /**
   * Create multiple packets in a single request (max 50).
   */
  batchCreatePackets(packets: PacketCreate[]): BatchCreateResponse {
    const payload = { packets: packets.map(p => serializePacketCreate(p)) };
    const data = this._request('POST', '/packets/batch', { jsonData: payload });
    return data as unknown as BatchCreateResponse;
  }

  /**
   * Claim multiple packets in a single request.
   */
  batchClaimPackets(packetIds: string[], options: BatchClaimOptions): BatchClaimResponse {
    const payload = {
      packet_ids: packetIds,
      agent_id: options.agentId,
      agent_name: options.agentName,
      ...(options.framework && { framework: options.framework }),
    };
    const data = this._request('POST', '/packets/batch/claim', { jsonData: payload });
    return data as unknown as BatchClaimResponse;
  }

  /**
   * Complete multiple packets in a single request.
   */
  batchCompletePackets(packetIds: string[]): BatchCompleteResponse {
    const payload = { packet_ids: packetIds };
    const data = this._request('POST', '/packets/batch/complete', { jsonData: payload });
    return data as unknown as BatchCompleteResponse;
  }

  // ── Search ─────────────────────────────────────────────────────────────

  /**
   * Full-text search across packet summaries and context.
   */
  searchPackets(query: string, options?: SearchOptions): PacketListResponse {
    const params: Record<string, string | number | undefined> = { q: query };
    if (options) {
      if (options.limit !== undefined) params.limit = options.limit;
      if (options.offset !== undefined) params.offset = options.offset;
      if (options.status) params.status = options.status;
      if (options.priority) params.priority = options.priority;
    }
    const data = this._request('GET', '/packets/search', { params });
    return data as unknown as PacketListResponse;
  }

  // ── Response helpers ───────────────────────────────────────────────────

  private _toPacketResponse(data: Record<string, unknown> | Record<string, unknown>[]): PacketResponse {
    return data as unknown as PacketResponse;
  }

  private _toPacketListResponse(data: Record<string, unknown> | Record<string, unknown>[]): PacketListResponse {
    return data as unknown as PacketListResponse;
  }

  private _toPacketHistoryResponse(data: Record<string, unknown> | Record<string, unknown>[]): PacketHistoryResponse {
    return data as unknown as PacketHistoryResponse;
  }

  private _toWebhookResponse(data: Record<string, unknown> | Record<string, unknown>[]): WebhookResponse {
    return data as unknown as WebhookResponse;
  }
}
