/**
 * HandoffRail SDK — Custom error hierarchy.
 *
 * All SDK errors extend {@link HandoffRailError} so callers can catch
 * the base class or any specific subclass.
 *
 * @module
 */

/** Base options for all HandoffRail errors. */
export interface HandoffRailErrorOptions {
  statusCode?: number;
  responseBody?: Record<string, unknown>;
}

/**
 * Base error for all HandoffRail SDK errors.
 */
export class HandoffRailError extends Error {
  /** HTTP status code, if applicable. */
  public readonly statusCode?: number;

  /** Parsed response body from the API, if available. */
  public readonly responseBody: Record<string, unknown>;

  constructor(
    message: string,
    options: HandoffRailErrorOptions = {},
  ) {
    super(message);
    this.name = 'HandoffRailError';
    this.statusCode = options.statusCode;
    this.responseBody = options.responseBody ?? {};
  }
}

/**
 * Raised when the API key is missing, invalid, or revoked (401).
 */
export class AuthenticationError extends HandoffRailError {
  constructor(
    message = 'Authentication failed: invalid or missing API key',
    options: HandoffRailErrorOptions = {},
  ) {
    super(message, { statusCode: 401, ...options });
    this.name = 'AuthenticationError';
  }
}

/**
 * Raised when the requested resource does not exist (404 / 410).
 */
export class NotFoundError extends HandoffRailError {
  /** The resource identifier that was not found, if available. */
  public readonly resourceId?: string;

  constructor(
    message = 'Resource not found',
    options: HandoffRailErrorOptions & { resourceId?: string } = {},
  ) {
    super(message, { statusCode: 404, ...options });
    this.name = 'NotFoundError';
    this.resourceId = options.resourceId;
  }
}

/**
 * Raised when the request payload fails server-side validation (400 / 409).
 */
export class ValidationError extends HandoffRailError {
  /** The specific field that failed validation, if available. */
  public readonly field?: string;

  constructor(
    message = 'Validation error',
    options: HandoffRailErrorOptions & { field?: string } = {},
  ) {
    super(message, { statusCode: 400, ...options });
    this.name = 'ValidationError';
    this.field = options.field;
  }
}

/**
 * Raised when a conflict occurs (409).
 *
 * This is distinct from {@link ValidationError} and represents cases where
 * the request is valid but cannot be completed due to a conflicting state.
 */
export class ConflictError extends HandoffRailError {
  constructor(
    message = 'Resource conflict',
    options: HandoffRailErrorOptions = {},
  ) {
    super(message, { statusCode: 409, ...options });
    this.name = 'ConflictError';
  }
}

/**
 * Raised when the API rate limit has been exceeded (429).
 */
export class RateLimitError extends HandoffRailError {
  /** Number of seconds to wait before retrying, if provided by the server. */
  public readonly retryAfter?: number;

  constructor(
    message = 'Rate limit exceeded',
    options: HandoffRailErrorOptions & { retryAfter?: number } = {},
  ) {
    super(message, { statusCode: 429, ...options });
    this.name = 'RateLimitError';
    this.retryAfter = options.retryAfter;
  }
}

/**
 * Raised when the server returns a 5xx error.
 */
export class ServerError extends HandoffRailError {
  constructor(
    message = 'Internal server error',
    options: HandoffRailErrorOptions = {},
  ) {
    super(message, { ...options });
    this.name = 'ServerError';
  }
}

/**
 * Raised when the SDK cannot reach the HandoffRail server (network / timeout).
 */
export class ConnectionError extends HandoffRailError {
  /** The original error that caused the connection failure, if available. */
  public readonly originalError?: Error;

  constructor(
    message = 'Unable to connect to HandoffRail server',
    options: { originalError?: Error } & HandoffRailErrorOptions = {},
  ) {
    super(message, options);
    this.name = 'ConnectionError';
    this.originalError = options.originalError;
  }
}
