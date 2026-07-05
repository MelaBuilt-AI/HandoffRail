/**
 * Tests for the HandoffRail SDK error classes.
 */

import {
  HandoffRailError,
  AuthenticationError,
  NotFoundError,
  ValidationError,
  ConflictError,
  RateLimitError,
  ServerError,
  ConnectionError,
} from '../src/errors';

describe('HandoffRailError', () => {
  it('should create a basic error with message', () => {
    const err = new HandoffRailError('Something went wrong');
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe('HandoffRailError');
    expect(err.message).toBe('Something went wrong');
    expect(err.statusCode).toBeUndefined();
    expect(err.responseBody).toEqual({});
  });

  it('should accept status code and response body', () => {
    const err = new HandoffRailError('Server error', {
      statusCode: 500,
      responseBody: { detail: 'Internal error' },
    });
    expect(err.statusCode).toBe(500);
    expect(err.responseBody).toEqual({ detail: 'Internal error' });
  });
});

describe('AuthenticationError', () => {
  it('should default to 401', () => {
    const err = new AuthenticationError();
    expect(err.name).toBe('AuthenticationError');
    expect(err.statusCode).toBe(401);
    expect(err.message).toContain('Authentication failed');
  });

  it('should accept custom message and response body', () => {
    const err = new AuthenticationError('Invalid key', {
      responseBody: { detail: 'API key expired' },
    });
    expect(err.message).toBe('Invalid key');
    expect(err.responseBody).toEqual({ detail: 'API key expired' });
  });
});

describe('NotFoundError', () => {
  it('should default to 404 with resourceId', () => {
    const err = new NotFoundError('Packet not found', {
      resourceId: 'abc-123',
      statusCode: 404,
    });
    expect(err.name).toBe('NotFoundError');
    expect(err.message).toBe('Packet not found');
    expect(err.resourceId).toBe('abc-123');
    expect(err.statusCode).toBe(404);
  });

  it('should support 410 status code', () => {
    const err = new NotFoundError('Resource gone', {
      statusCode: 410,
      resourceId: '/packets/old-id',
    });
    expect(err.statusCode).toBe(410);
  });
});

describe('ValidationError', () => {
  it('should include field information', () => {
    const err = new ValidationError('Invalid priority', {
      field: 'priority',
      statusCode: 400,
    });
    expect(err.name).toBe('ValidationError');
    expect(err.field).toBe('priority');
    expect(err.statusCode).toBe(400);
  });
});

describe('ConflictError', () => {
  it('should default to 409', () => {
    const err = new ConflictError();
    expect(err.name).toBe('ConflictError');
    expect(err.statusCode).toBe(409);
  });

  it('should accept custom detail', () => {
    const err = new ConflictError('Packet already claimed', {
      responseBody: { detail: 'Packet already claimed by another agent' },
    });
    expect(err.message).toBe('Packet already claimed');
  });
});

describe('RateLimitError', () => {
  it('should include retry_after', () => {
    const err = new RateLimitError('Too many requests', { retryAfter: 30 });
    expect(err.name).toBe('RateLimitError');
    expect(err.retryAfter).toBe(30);
    expect(err.statusCode).toBe(429);
  });

  it('should handle undefined retry_after', () => {
    const err = new RateLimitError();
    expect(err.retryAfter).toBeUndefined();
  });
});

describe('ServerError', () => {
  it('should capture status code', () => {
    const err = new ServerError('Internal server error', { statusCode: 502 });
    expect(err.name).toBe('ServerError');
    expect(err.statusCode).toBe(502);
  });
});

describe('ConnectionError', () => {
  it('should capture original error', () => {
    const original = new Error('ECONNREFUSED');
    const err = new ConnectionError('Connection refused', {
      originalError: original,
    });
    expect(err.name).toBe('ConnectionError');
    expect(err.originalError).toBe(original);
    expect(err.message).toBe('Connection refused');
  });
});
