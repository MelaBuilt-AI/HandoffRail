# HandoffRail — Roadmap & Future Additions

## ✅ Completed (Items 1-4)

| # | Feature | Status | Commit |
|---|---------|--------|--------|
| 1 | NPM Publish (TypeScript SDK) | ✅ `handoffrail-sdk@0.2.0` live | `5daab99` |
| 2 | TypeScript WebSocket Client | ✅ 40 tests, auto-reconnect, cross-platform | `5daab99` |
| 3 | Batch Operations API | ✅ Create/claim/complete, 20 tests, both SDKs | `5daab99` |
| 4 | Full-Text Search | ✅ FTS5 (SQLite) + tsvector (Postgres), 7 tests, both SDKs | `5daab99` |

**Test totals after items 1-4:** Python 457 passed / 24 skipped · TypeScript 139 passed

---

## 📋 Remaining Roadmap (Items 5-15)

These are the features analyzed during the roadmap session on 2026-07-05. Impact and effort ratings are approximate. Pick and choose when ready to implement.

### 5. List Packets Refactor — Cursor Pagination
**Impact:** Medium · **Effort:** Low

Replace offset-based pagination on `GET /packets` with cursor-based pagination for better performance on large datasets. Currently uses `offset`/`limit` which degrades as offset grows.

- Add `cursor` query param (based on `created_at` + `id` tuple)
- Return `next_cursor` in response metadata
- Keep backward compat: if no cursor provided, use offset (deprecation path)
- Update both SDKs with cursor support
- Update docs

### 6. Webhook Retry with Exponential Backoff
**Impact:** High · **Effort:** Medium

Currently webhooks fire once with no retry. If the target is down, the event is lost. Add a robust retry mechanism.

- Redis-backed retry queue (or in-memory for dev)
- Exponential backoff: 1s → 5s → 30s → 5m → 1h → 6h (max 6 attempts)
- Mark webhook deliveries as succeeded/failed in a `webhook_deliveries` table
- Add `GET /hooks/{id}/deliveries` endpoint to inspect delivery history
- Configurable retry policy per webhook
- Dead-letter queue for permanently failed deliveries

### 7. Rate Limiting (Per API Key)
**Impact:** High · **Effort:** Low

Add per-API-key rate limiting to prevent abuse. Currently only global rate limiting via slowapi.

- Track request counts per API key in Redis (sliding window)
- Configurable limits: `RATE_LIMIT_PER_MINUTE` (default 60)
- Return `429 Too Many Requests` with `Retry-After` header
- Add `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers
- Exempt system endpoints (`/health`, `/ready`, `/metrics`)

### 8. CLI Tool (`handoffrail` command)
**Impact:** Medium · **Effort:** Medium

A CLI for interacting with HandoffRail from the terminal — useful for devops and debugging.

```bash
handoffrail packets list --status=created
handoffrail packets create --file=packet.json
handoffrail packets claim <id> --agent=agent-01
handoffrail packets search "error handling"
handoffrail hooks list
handoffrail keys create --name="prod-key"
```

- Python package entry point (`handoffrail-cli`)
- Uses the Python SDK under the hood
- JSON/table output formats (`--format=json|table`)
- Config file (`~/.handoffrail.toml`) for base URL + API key
- Shell completion (bash/zsh)

### 9. OpenAPI Schema Export & API Explorer
**Impact:** Medium · **Effort:** Low

FastAPI already generates OpenAPI but it's not exposed cleanly for consumers.

- `GET /openapi.json` → already exists via FastAPI, ensure it's complete
- Add a Swagger UI or ReDoc endpoint at `/docs` (FastAPI built-in)
- Export schema file to `docs/openapi.json` in repo
- Add downloadable schema link in docs
- Ensure all new batch/search endpoints are documented

### 10. Redis Pub/Sub for Real-Time Events
**Impact:** High · **Effort:** Medium

The WebSocket client currently uses a single connection. Scale to multi-instance deployments with Redis Pub/Sub.

- Publish packet events to Redis channels (`packet:created`, `packet:claimed`, etc.)
- WebSocket server subscribes to Redis channels and fans out to connected clients
- Enable horizontal scaling (multiple server instances behind a load balancer)
- Add Redis fallback when WebSocket unavailable (SSE endpoint as alternative)
- Graceful degradation: if Redis is down, fall back to in-process event dispatch

### 11. Multi-Tenant Isolation
**Impact:** High · **Effort:** High

Currently `tenant_id` is stored but not enforced. Add proper tenant isolation.

- Enforce `tenant_id` on all queries (filter at the SQLAlchemy session level)
- API keys scoped to a single tenant
- Tenant management endpoints (`POST /tenants`, `GET /tenants/{id}`)
- Per-tenant rate limits and webhook configurations
- Migration path: default tenant for existing single-tenant users

### 12. RBAC (Role-Based Access Control)
**Impact:** Medium · **Effort:** High

Add roles to API keys for finer-grained permissions.

- Roles: `admin`, `writer`, `reader`, `agent`
- `admin`: all operations including key management
- `writer`: create/update/claim/complete packets
- `reader`: list/get/search only
- `agent`: claim/complete packets only (no create)
- Store role on API key, enforce in middleware
- Add `role` field to API key creation endpoint

### 13. Structured Audit Log
**Impact:** Medium · **Effort:** Low

Currently audit events are stored in the `events` table but not easily queryable for compliance.

- Separate `audit_log` table with structured fields (actor, action, resource, timestamp, ip, user_agent)
- `GET /audit` endpoint with filtering (by actor, action, date range)
- Export to JSON/CSV
- Retention policy (configurable TTL)
- Add audit entries for: key creation/revocation, webhook registration/deletion, packet lifecycle events

### 14. Schema Validation & Migration Tooling
**Impact:** Medium · **Effort:** Medium

The `context` JSON field is freeform. Add optional schema validation.

- Define JSON Schema for packet `context` field (per use case / framework)
- `POST /packets` accepts optional `schema_id` → validate context against schema
- Schema registry endpoint (`POST /schemas`, `GET /schemas/{id}`)
- Alembic migration helper for schema changes
- Versioned API (`/api/v2/`) preparation

### 15. Metrics Dashboard (Grafana)
**Impact:** Low · **Effort:** Medium

Prometheus metrics are already exposed at `/metrics`. Add a pre-built Grafana dashboard.

- JSON dashboard export in `docs/grafana-dashboard.json`
- Panels: packets by status, throughput (create/claim/complete per minute), webhook delivery success rate, API latency p50/p95/p99, active agents
- Alert rules: high error rate, webhook failure spike, queue depth
- Add `docs/monitoring.md` with setup instructions
- Optional: integrate with PagerDuty for critical alerts

---

## How to Use This Document

When ready to implement the next batch:
1. Pick items by priority (impact × effort ratio)
2. Update the status column
3. Create a branch or work on `master` directly (project preference)
4. Follow the existing code patterns (async SQLAlchemy 2.0, Pydantic v2, structlog)
5. Run quality gates: `pytest tests/ -x -q` + `npm test` + `npm run typecheck`
6. Update `docs/api-reference.md` for any new endpoints
7. Update both Python and TypeScript SDKs
8. Commit and push

## Suggested Next Batch (High Impact, Low Effort)

If picking the next 3-4 items for maximum value with minimal effort:
- **Item 7** (Rate Limiting) — essential for production hardening
- **Item 9** (OpenAPI Export) — quick win, improves DX
- **Item 5** (Cursor Pagination) — performance fix before scale
- **Item 13** (Audit Log) — compliance-ready, straightforward

---

_Last updated: 2026-07-05_