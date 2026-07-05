/**
 * HandoffRail SDK — Asynchronous HTTP client.
 *
 * Uses the native `fetch` API (available in Node.js 18+).
 *
 * Usage:
 * ```typescript
 * import { AsyncHandoffRailClient, PacketBuilder } from 'handoffrail-sdk';
 *
 * const client = new AsyncHandoffRailClient({
 *   baseUrl: 'http://localhost:8080/api/v1',
 *   apiKey: 'sk-...',
 * });
 *
 * const packet = await client.createPacket(
 *   new PacketBuilder()
 *     .to('billing-01', 'BillingBot')
 *     .from('sales-01', 'SalesBot')
 *     .withSummary('Customer wants Business tier')
 *     .build()
 * );
 *
 * await client.close();
 * ```
 *
 * @module
 */

import type {
  PacketCreate,
  PacketResponse,
  PacketListResponse,
  PacketUpdate,
  PacketHistoryResponse,
  ChainHandoffRequest,
  WebhookCreate,
  WebhookResponse,
  ListPacketsOptions,
  ClaimPacketOptions,
  HitlRespondOptions,
  RegisterWebhookOptions,
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

/** Configuration options for the async HandoffRail client. */
export interface AsyncHandoffRailClientOptions {
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

// ── Helper: sleep ────────────────────────────────────────────────────────

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// ── Client ───────────────────────────────────────────────────────────────

/**
 * Asynchronous HTTP client for the HandoffRail API.
 *
 * @remarks
 * All methods return Promises. For blocking/synchronous usage, see
 * {@link HandoffRailClient}.
 */
export class AsyncHandoffRailClient {
  public readonly baseUrl: string;
  public readonly apiKey: string;
  public readonly timeout: number;
  public readonly maxRetries: number;
  public readonly retryDelay: number;
  private _abortController: AbortController | null = null;

  constructor(options: AsyncHandoffRailClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.apiKey = options.apiKey;
    this.timeout = options.timeout ?? 30_000;
    this.maxRetries = options.maxRetries ?? 3;
    this.retryDelay = options.retryDelay ?? 500;
  }

  // ── Public lifecycle ──────────────────────────────────────────────────

  /**
   * Close any pending connections.
   */
  async close(): Promise<void> {
    if (this._abortController) {
      this._abortController.abort();
      this._abortController = null;
    }
  }

  // ── Internal helpers ──────────────────────────────────────────────────

  /**
   * Build default headers for every request.
   */
  private _headers(): Record<string, string> {
    return {
      'X-API-Key': this.apiKey,
      'Content-Type': 'application/json',
    };
  }

  /**
   * Parse the JSON response body.
   */
  private async _parseBody(
    response: Response,
  ): Promise<Record<string, unknown> | Record<string, unknown>[] | null> {
    const text = await response.text();
    if (!text) return null;
    try {
      const parsed = JSON.parse(text);
      if (Array.isArray(parsed)) return parsed;
      if (typeof parsed === 'object' && parsed !== null) return parsed as Record<string, unknown>;
      return null;
    } catch {
      return { raw: text };
    }
  }

  /**
   * Handle the HTTP response and map status codes to SDK errors.
   */
  private async _handleResponse(
    response: Response,
    url: string,
  ): Promise<Record<string, unknown> | Record<string, unknown>[]> {
    const body = await this._parseBody(response);
    const responseBody = (body as Record<string, unknown>) ?? {};

    if (response.status === 401) {
      throw new AuthenticationError(
        (responseBody.detail as string) ?? 'Authentication failed',
        { responseBody },
      );
    }
    if (response.status === 404 || response.status === 410) {
      throw new NotFoundError(
        (responseBody.detail as string) ?? 'Resource not found',
        { statusCode: response.status, responseBody, resourceId: url },
      );
    }
    if (response.status === 400) {
      throw new ValidationError(
        (responseBody.detail as string) ?? 'Validation error',
        { field: responseBody.field as string | undefined, responseBody },
      );
    }
    if (response.status === 409) {
      const detail = responseBody.detail ?? responseBody;
      throw new ConflictError(
        typeof detail === 'string' ? detail : 'Resource conflict',
        { responseBody },
      );
    }
    if (response.status === 429) {
      const retryAfter = response.headers.get('Retry-After');
      throw new RateLimitError('Rate limit exceeded', {
        retryAfter: retryAfter ? parseInt(retryAfter, 10) : undefined,
        responseBody,
      });
    }
    if (response.status >= 500) {
      throw new ServerError(`Server error: ${response.status}`, {
        statusCode: response.status,
        responseBody,
      });
    }
    if (response.status === 204) {
      return {};
    }

    // Success
    return body ?? {};
  }

  /**
   * Make an HTTP request with retry logic and error mapping.
   */
  protected async _request(
    method: string,
    path: string,
    options?: {
      jsonData?: Record<string, unknown>;
      params?: Record<string, string | number | undefined>;
    },
  ): Promise<Record<string, unknown> | Record<string, unknown>[]> {
    const url = new URL(`${this.baseUrl}${path}`);

    if (options?.params) {
      for (const [key, value] of Object.entries(options.params)) {
        if (value !== undefined && value !== null) {
          url.searchParams.set(key, String(value));
        }
      }
    }

    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      let timeoutId: ReturnType<typeof setTimeout> | null = null;
      try {
        this._abortController = new AbortController();
        timeoutId = setTimeout(() => this._abortController?.abort(), this.timeout);

        const fetchOptions: RequestInit & { signal: AbortSignal } = {
          method,
          headers: {
            'X-API-Key': this.apiKey,
            ...(options?.jsonData ? { 'Content-Type': 'application/json' } : {}),
          },
          signal: this._abortController.signal,
        };

        if (options?.jsonData !== undefined) {
          fetchOptions.body = JSON.stringify(options.jsonData);
        }

        const response = await fetch(url.toString(), fetchOptions);
        const result = await this._handleResponse(response, url.toString());
        return result;
      } catch (err) {
        // Rethrow HandoffRailErrors directly (e.g., 4xx/5xx from _handleResponse)
        if (err instanceof HandoffRailError) {
          throw err;
        }

        lastError = err as Error;

        // Don't retry on abort (timeout)
        if (err instanceof DOMException && err.name === 'AbortError') {
          throw new ConnectionError('Request timed out', { originalError: err as Error });
        }

        if (attempt < this.maxRetries) {
          const backoff = this.retryDelay * Math.pow(2, attempt);
          await sleep(backoff);
          continue;
        }
      } finally {
        // Always clear timeout and controller — prevents open handles in tests
        if (timeoutId !== null) {
          clearTimeout(timeoutId);
        }
        this._abortController = null;
      }
    }

    throw new ConnectionError(
      `Unable to connect to HandoffRail server after ${this.maxRetries + 1} attempts`,
      { originalError: lastError ?? undefined },
    );
  }

  // ── Packet CRUD ────────────────────────────────────────────────────────

  /**
   * Create a new handoff packet.
   */
  async createPacket(packet: PacketCreate): Promise<PacketResponse> {
    const data = await this._request('POST', '/packets', {
      jsonData: serializePacketCreate(packet) as Record<string, unknown>,
    });
    return data as unknown as PacketResponse;
  }

  /**
   * Get a single packet by ID.
   */
  async getPacket(packetId: string): Promise<PacketResponse> {
    const data = await this._request('GET', `/packets/${encodeURIComponent(packetId)}`);
    return data as unknown as PacketResponse;
  }

  /**
   * List packets with filtering and pagination.
   */
  async listPackets(options?: ListPacketsOptions): Promise<PacketListResponse> {
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

    const data = await this._request('GET', '/packets', { params });
    return data as unknown as PacketListResponse;
  }

  /**
   * Claim a packet for processing.
   */
  async claimPacket(
    packetId: string,
    options: ClaimPacketOptions,
  ): Promise<PacketResponse> {
    const data = await this._request(
      'POST',
      `/packets/${encodeURIComponent(packetId)}/claim`,
      {
        jsonData: {
          agent_id: options.agent_id,
          agent_name: options.agent_name,
          framework: options.framework,
        },
      },
    );
    return data as unknown as PacketResponse;
  }

  /**
   * Partially update a packet.
   */
  async updatePacket(
    packetId: string,
    update: PacketUpdate,
  ): Promise<PacketResponse> {
    const data = await this._request(
      'PATCH',
      `/packets/${encodeURIComponent(packetId)}`,
      { jsonData: serializePacketUpdate(update) as Record<string, unknown> },
    );
    return data as unknown as PacketResponse;
  }

  /**
   * Mark a packet as completed.
   *
   * Convenience method that sets status to `completed`.
   */
  async completePacket(packetId: string): Promise<PacketResponse> {
    return this.updatePacket(packetId, { status: 'completed' });
  }

  /**
   * Soft-delete a packet (marks as expired).
   */
  async deletePacket(packetId: string): Promise<void> {
    await this._request('DELETE', `/packets/${encodeURIComponent(packetId)}`);
  }

  /**
   * Submit a human response to a HITL checkpoint.
   */
  async respondToHitl(
    packetId: string,
    options: HitlRespondOptions,
  ): Promise<PacketResponse> {
    const data = await this._request(
      'POST',
      `/packets/${encodeURIComponent(packetId)}/respond`,
      {
        jsonData: {
          response: options.response,
          responded_by: options.responded_by,
          notes: options.notes,
        },
      },
    );
    return data as unknown as PacketResponse;
  }

  /**
   * Get packets awaiting human review.
   */
  async listAwaitingHuman(
    options?: { limit?: number; offset?: number },
  ): Promise<PacketListResponse> {
    const params: Record<string, string | number | undefined> = {
      limit: options?.limit ?? 50,
      offset: options?.offset ?? 0,
    };
    const data = await this._request('GET', '/packets/awaiting', { params });
    return data as unknown as PacketListResponse;
  }

  /**
   * Get the event history for a packet.
   */
  async getPacketHistory(packetId: string): Promise<PacketHistoryResponse> {
    const data = await this._request(
      'GET',
      `/packets/${encodeURIComponent(packetId)}/history`,
    );
    return data as unknown as PacketHistoryResponse;
  }

  /**
   * Create a chained follow-up packet.
   */
  async chainPacket(
    parentPacketId: string,
    request: ChainHandoffRequest,
  ): Promise<PacketResponse> {
    const data = await this._request(
      'POST',
      `/packets/${encodeURIComponent(parentPacketId)}/chain`,
      { jsonData: serializeChainHandoffRequest(request) as Record<string, unknown> },
    );
    return data as unknown as PacketResponse;
  }

  // ── Webhook CRUD ───────────────────────────────────────────────────────

  /**
   * Register a new webhook.
   */
  async registerWebhook(options: RegisterWebhookOptions): Promise<WebhookResponse> {
    const data = await this._request('POST', '/hooks', {
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
    return data as unknown as WebhookResponse;
  }

  /**
   * List all webhooks for the authenticated tenant.
   */
  async listWebhooks(): Promise<WebhookResponse[]> {
    const data = await this._request('GET', '/hooks');
    if (Array.isArray(data)) {
      return data.map((w) => w as unknown as WebhookResponse);
    }
    return [];
  }

  /**
   * Deactivate (soft-delete) a webhook.
   */
  async deleteWebhook(webhookId: string): Promise<void> {
    await this._request('DELETE', `/hooks/${encodeURIComponent(webhookId)}`);
  }
}
