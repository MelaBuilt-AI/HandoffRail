/**
 * HandoffRail SDK — WebSocket client for real-time event streaming.
 *
 * Provides an async client that connects to HandoffRail's `/ws` endpoint
 * and dispatches typed events to callback handlers.
 *
 * Works in both Node.js (using the `ws` package) and browser environments
 * (using the native `WebSocket` API).
 *
 * Usage:
 * ```typescript
 * import { AsyncWebSocketClient } from 'handoffrail-sdk';
 *
 * const client = new AsyncWebSocketClient({
 *   baseUrl: 'http://localhost:8080',
 *   apiKey: 'sk-...',
 * });
 *
 * client.onPacketCreated = (event) => console.log('New packet:', event.packet_id);
 * await client.connect();
 * await client.subscribe('status:created');
 * // ... listen for events ...
 * await client.close();
 * ```
 *
 * @module
 */

// ── Event type constants ─────────────────────────────────────────────────────

/** A new handoff packet was created. */
export const EVENT_PACKET_CREATED = 'packet.created';

/** A packet was claimed by an agent. */
export const EVENT_PACKET_CLAIMED = 'packet.claimed';

/** A packet was updated (generic update). */
export const EVENT_PACKET_UPDATED = 'packet.updated';

/** A packet moved to in-progress status. */
export const EVENT_PACKET_IN_PROGRESS = 'packet.in_progress';

/** A packet is awaiting human input. */
export const EVENT_PACKET_AWAITING_HUMAN = 'packet.awaiting_human';

/** A packet was completed successfully. */
export const EVENT_PACKET_COMPLETED = 'packet.completed';

/** A packet failed. */
export const EVENT_PACKET_FAILED = 'packet.failed';

/** A packet expired. */
export const EVENT_PACKET_EXPIRED = 'packet.expired';

/** A chained follow-up packet was created. */
export const EVENT_PACKET_CHAINED = 'packet.chained';

/** A human-in-the-loop response is ready. */
export const EVENT_HITL_RESPONSE_READY = 'hitl.response_ready';

/** Set of all known event types. */
export const ALL_EVENTS: ReadonlySet<string> = new Set([
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
]);

// ── Event data type ──────────────────────────────────────────────────────────

/**
 * A HandoffRail real-time event received over the WebSocket.
 *
 * @remarks
 * The `data` field contains the full event payload. The shape varies by
 * event type — for packet events it typically includes the full packet
 * response object.
 */
export interface HandoffRailEvent {
  /** The event type string (e.g. `packet.created`). */
  event_type: string;
  /** The ID of the packet this event relates to. */
  packet_id: string;
  /** ISO-8601 timestamp of when the event was emitted. */
  timestamp: string;
  /** The full event payload (varies by event type). */
  data: Record<string, unknown>;
}

// ── Callback types ──────────────────────────────────────────────────────────

/** Callback invoked for a specific event type. */
export type EventCallback = (event: HandoffRailEvent) => void | Promise<void>;

/** Callback invoked on connection established. */
export type ConnectedCallback = () => void | Promise<void>;

/** Callback invoked on disconnection. */
export type DisconnectedCallback = () => void | Promise<void>;

/** Callback invoked on error. */
export type ErrorCallback = (error: Error) => void | Promise<void>;

// ── WebSocket abstraction ───────────────────────────────────────────────────

/**
 * Minimal WebSocket interface that works across Node.js (`ws` package)
 * and browser (`WebSocket` API).
 *
 * @remarks
 * Both the `ws` package and the browser `WebSocket` satisfy this interface.
 * Users can pass a custom factory to create WebSocket instances.
 */
export interface WebSocketLike {
  /** Current ready state. */
  readonly readyState: number;

  /** Send a string message. */
  send(data: string): void;

  /** Close the connection. */
  close(code?: number, reason?: string): void;

  /** Fired when the connection opens. */
  onopen: ((event: unknown) => void) | null;

  /** Fired when a message is received. */
  onmessage: ((event: { data: string }) => void) | null;

  /** Fired when the connection closes. */
  onclose: ((event: { code: number; reason: string }) => void) | null;

  /** Fired on error. */
  onerror: ((event: unknown) => void) | null;
}

/** WebSocket ready state constants (mirrors the standard WebSocket API). */
export const WS_CONNECTING = 0;
export const WS_OPEN = 1;
export const WS_CLOSING = 2;
export const WS_CLOSED = 3;

/**
 * Factory function that creates a WebSocket instance.
 *
 * @param url - The WebSocket URL to connect to.
 * @returns A WebSocket-like instance.
 */
export type WebSocketFactory = (url: string) => WebSocketLike;

// ── Configuration ───────────────────────────────────────────────────────────

/** Configuration options for the WebSocket client. */
export interface AsyncWebSocketClientOptions {
  /**
   * Base HTTP URL of the HandoffRail API (e.g. `http://localhost:8080`).
   *
   * @remarks
   * The WebSocket URL is derived from this by replacing `http://` with
   * `ws://` (or `https://` with `wss://`) and appending `/ws`.
   */
  baseUrl: string;

  /** API key for authentication (sent as `api_key` query parameter). */
  apiKey: string;

  /**
   * Whether to auto-reconnect on disconnect (default: `true`).
   */
  reconnect?: boolean;

  /**
   * Initial reconnect delay in milliseconds (default: `1000`).
   */
  reconnectDelay?: number;

  /**
   * Maximum reconnect delay in milliseconds (default: `30000`).
   */
  maxReconnectDelay?: number;

  /**
   * Multiplier for exponential backoff (default: `2.0`).
   */
  reconnectMultiplier?: number;

  /**
   * Custom WebSocket factory.
   *
   * @remarks
   * In Node.js, pass a factory that uses the `ws` package:
   * ```typescript
   * import WebSocket from 'ws';
   * const factory = (url: string) => new WebSocket(url);
   * ```
   * In the browser, this defaults to the native `WebSocket` constructor.
   */
  webSocketFactory?: WebSocketFactory;
}

// ── Helper: sleep ───────────────────────────────────────────────────────────

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

// ── Client ───────────────────────────────────────────────────────────────────

/**
 * Async WebSocket client for HandoffRail real-time events.
 *
 * @remarks
 * Connects to the HandoffRail `/ws` endpoint and dispatches typed events
 * to callback handlers. Supports auto-reconnect with exponential backoff,
 * channel subscriptions, and heartbeat pings.
 *
 * @example
 * ```typescript
 * const client = new AsyncWebSocketClient({
 *   baseUrl: 'http://localhost:8080',
 *   apiKey: 'sk-...',
 * });
 *
 * client.onPacketCreated = (event) => {
 *   console.log('New packet:', event.packet_id);
 * };
 *
 * await client.connect();
 * await client.subscribe('status:created');
 * // ... listen for events ...
 * await client.close();
 * ```
 */
export class AsyncWebSocketClient {
  /** The derived WebSocket URL. */
  public readonly wsUrl: string;

  private readonly _apiKey: string;
  private readonly _reconnect: boolean;
  private readonly _reconnectDelay: number;
  private readonly _maxReconnectDelay: number;
  private readonly _reconnectMultiplier: number;
  private readonly _webSocketFactory: WebSocketFactory;

  private _ws: WebSocketLike | null = null;
  private _connected = false;
  private _running = false;
  private _currentDelay: number;
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  // ── Event callbacks ───────────────────────────────────────────────────

  /** Called when a packet is created. */
  public onPacketCreated: EventCallback | null = null;

  /** Called when a packet is claimed. */
  public onPacketClaimed: EventCallback | null = null;

  /** Called when a packet is updated. */
  public onPacketUpdated: EventCallback | null = null;

  /** Called when a packet moves to in-progress. */
  public onPacketInProgress: EventCallback | null = null;

  /** Called when a packet is awaiting human input. */
  public onPacketAwaitingHuman: EventCallback | null = null;

  /** Called when a packet is completed. */
  public onPacketCompleted: EventCallback | null = null;

  /** Called when a packet fails. */
  public onPacketFailed: EventCallback | null = null;

  /** Called when a packet expires. */
  public onPacketExpired: EventCallback | null = null;

  /** Called when a chained packet is created. */
  public onPacketChained: EventCallback | null = null;

  /** Called when a HITL response is ready. */
  public onHitlResponseReady: EventCallback | null = null;

  /** Called when the WebSocket connection is established. */
  public onConnected: ConnectedCallback | null = null;

  /** Called when the WebSocket connection is lost. */
  public onDisconnected: DisconnectedCallback | null = null;

  /** Called when a WebSocket error occurs. */
  public onError: ErrorCallback | null = null;

  /** Generic callback for all events (fires before type-specific callbacks). */
  public onEvent: EventCallback | null = null;

  // ── Constructor ───────────────────────────────────────────────────────

  constructor(options: AsyncWebSocketClientOptions) {
    this.wsUrl = this._buildWsUrl(options.baseUrl, options.apiKey);
    this._apiKey = options.apiKey;
    this._reconnect = options.reconnect ?? true;
    this._reconnectDelay = options.reconnectDelay ?? 1000;
    this._maxReconnectDelay = options.maxReconnectDelay ?? 30000;
    this._reconnectMultiplier = options.reconnectMultiplier ?? 2.0;
    this._currentDelay = this._reconnectDelay;

    // Use provided factory, or default to global WebSocket
    this._webSocketFactory =
      options.webSocketFactory ??
      ((url: string): WebSocketLike => {
        if (typeof WebSocket !== 'undefined') {
          return new WebSocket(url) as unknown as WebSocketLike;
        }
        throw new Error(
          'No WebSocket implementation available. ' +
            'Install the `ws` package for Node.js or provide a custom webSocketFactory.',
        );
      });
  }

  // ── Public properties ─────────────────────────────────────────────────

  /** Whether the client is currently connected. */
  get connected(): boolean {
    return this._connected;
  }

  // ── Public lifecycle ──────────────────────────────────────────────────

  /**
   * Connect to the WebSocket server and start listening for events.
   *
   * @remarks
   * Returns once the initial connection is established. Events are dispatched
   * via callbacks. If `reconnect` is enabled (default), the client will
   * automatically reconnect on disconnect with exponential backoff.
   *
   * If the initial connection fails, the error is passed to the
   * {@link onError} callback and the method resolves (does not throw).
   * The client will then attempt to reconnect if `reconnect` is enabled.
   */
  async connect(): Promise<void> {
    this._running = true;
    this._currentDelay = this._reconnectDelay;
    try {
      await this._connectOnce();
    } catch (err) {
      // Initial connection failed — notify via callback, then schedule reconnect
      if (this.onError) {
        try {
          await this.onError(err as Error);
        } catch {
          // Swallow callback errors
        }
      }
      // Schedule reconnect if enabled
      this._scheduleReconnect();
    }
  }

  /**
   * Disconnect from the WebSocket server and stop reconnecting.
   */
  async close(): Promise<void> {
    this._running = false;
    this._connected = false;

    // Cancel any pending reconnect timer
    if (this._reconnectTimer !== null) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }

    if (this._ws) {
      try {
        this._ws.close(1000, 'Client closed');
      } catch {
        // Ignore close errors
      }
      this._ws = null;
    }
  }

  // ── Channel management ────────────────────────────────────────────────

  /**
   * Subscribe to a channel.
   *
   * @param channel - Channel identifier. Format:
   *   - `"status:{status}"` — e.g. `"status:created"`, `"status:completed"`
   *   - `"packet:{id}"` — subscribe to events for a specific packet
   *   - `"agent:{id}"` — subscribe to events for a specific agent
   */
  async subscribe(channel: string): Promise<void> {
    if (this._ws && this._connected) {
      this._ws.send(JSON.stringify({ action: 'subscribe', channel }));
    }
  }

  /**
   * Unsubscribe from a channel.
   *
   * @param channel - Channel identifier to unsubscribe from.
   */
  async unsubscribe(channel: string): Promise<void> {
    if (this._ws && this._connected) {
      this._ws.send(JSON.stringify({ action: 'unsubscribe', channel }));
    }
  }

  /**
   * Send a ping to the server.
   */
  async ping(): Promise<void> {
    if (this._ws && this._connected) {
      this._ws.send(JSON.stringify({ action: 'ping' }));
    }
  }

  // ── Internal: connection ──────────────────────────────────────────────

  /**
   * Build the WebSocket URL from the HTTP base URL and API key.
   */
  private _buildWsUrl(baseUrl: string, apiKey: string): string {
    // Strip trailing slash and /api/v1 path
    let clean = baseUrl.replace(/\/+$/, '');
    // Remove /api/v1 suffix if present (WS endpoint is at root /ws)
    clean = clean.replace(/\/api\/v1\/?$/, '');

    // Replace http/https with ws/wss
    let wsUrl = clean.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:');

    // Append /ws path
    if (!wsUrl.endsWith('/ws')) {
      wsUrl = wsUrl.replace(/\/+$/, '') + '/ws';
    }

    // Append API key as query parameter
    const separator = wsUrl.includes('?') ? '&' : '?';
    return `${wsUrl}${separator}api_key=${encodeURIComponent(apiKey)}`;
  }

  /**
   * Establish a single WebSocket connection.
   *
   * @returns A promise that resolves when the connection opens.
   */
  private _connectOnce(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const ws = this._webSocketFactory(this.wsUrl);
      this._ws = ws;

      let opened = false;

      ws.onopen = () => {
        opened = true;
        this._connected = true;
        this._currentDelay = this._reconnectDelay;

        if (this.onConnected) {
          Promise.resolve(this.onConnected()).catch(() => {
            // Swallow callback errors
          });
        }

        resolve();
      };

      ws.onmessage = (event: { data: string }) => {
        if (!this._running) return;

        try {
          const raw = JSON.parse(event.data) as Record<string, unknown>;
          const handoffEvent: HandoffRailEvent = {
            event_type: (raw.type as string) ?? (raw.event_type as string) ?? '',
            packet_id: (raw.packet_id as string) ?? '',
            timestamp: (raw.timestamp as string) ?? new Date().toISOString(),
            data: raw,
          };
          this._dispatch(handoffEvent);
        } catch {
          // Ignore invalid JSON messages
        }
      };

      ws.onclose = (_event: { code: number; reason: string }) => {
        this._connected = false;
        this._ws = null;

        if (this.onDisconnected) {
          Promise.resolve(this.onDisconnected()).catch(() => {
            // Swallow callback errors
          });
        }

        // Schedule reconnect if enabled and still running
        this._scheduleReconnect();
      };

      ws.onerror = () => {
        if (!opened) {
          // Connection never opened — reject the promise
          reject(new Error('WebSocket connection failed'));
        }
        // If already opened, onclose will fire next and handle reconnect
      };
    });
  }

  /**
   * Schedule a reconnect attempt with exponential backoff.
   */
  private _scheduleReconnect(): void {
    if (!this._reconnect || !this._running) return;

    // Clear any existing timer
    if (this._reconnectTimer !== null) {
      clearTimeout(this._reconnectTimer);
    }

    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      if (!this._running) return;

      // Increase backoff for next time
      this._currentDelay = Math.min(
        this._currentDelay * this._reconnectMultiplier,
        this._maxReconnectDelay,
      );

      // Attempt reconnect
      this._connectOnce().catch((err) => {
        if (this.onError) {
          Promise.resolve(this.onError(err as Error)).catch(() => {
            // Swallow callback errors
          });
        }
        // _scheduleReconnect is called from onclose, which will fire again
      });
    }, this._currentDelay);

    // Don't let the reconnect timer keep the process alive
    if (typeof this._reconnectTimer.unref === 'function') {
      this._reconnectTimer.unref();
    }
  }

  // ── Internal: event dispatch ──────────────────────────────────────────

  /**
   * Dispatch an event to the appropriate callback.
   */
  private _dispatch(event: HandoffRailEvent): void {
    // Call generic event callback first
    if (this.onEvent) {
      Promise.resolve(this.onEvent(event)).catch(() => {
        // Swallow callback errors
      });
    }

    // Map event type to specific callback
    const callbackMap: Record<string, EventCallback | null> = {
      [EVENT_PACKET_CREATED]: this.onPacketCreated,
      [EVENT_PACKET_CLAIMED]: this.onPacketClaimed,
      [EVENT_PACKET_UPDATED]: this.onPacketUpdated,
      [EVENT_PACKET_IN_PROGRESS]: this.onPacketInProgress,
      [EVENT_PACKET_AWAITING_HUMAN]: this.onPacketAwaitingHuman,
      [EVENT_PACKET_COMPLETED]: this.onPacketCompleted,
      [EVENT_PACKET_FAILED]: this.onPacketFailed,
      [EVENT_PACKET_EXPIRED]: this.onPacketExpired,
      [EVENT_PACKET_CHAINED]: this.onPacketChained,
      [EVENT_HITL_RESPONSE_READY]: this.onHitlResponseReady,
    };

    const callback = callbackMap[event.event_type];
    if (callback) {
      try {
        Promise.resolve(callback(event)).catch(() => {
          // Swallow callback errors
        });
      } catch {
        // Swallow synchronous callback errors
      }
    }
  }
}
