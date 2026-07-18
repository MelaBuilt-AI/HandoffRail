# HandoffRail — Roadmap & Future Additions

## ✅ Completed (Items 1-15)

All roadmap items are now complete.

| # | Feature | Status | Commit |
|---|---------|--------|--------|
| 1 | NPM Publish (TypeScript SDK) | ✅ `handoffrail-sdk@0.2.0` live | `5daab99` |
| 2 | TypeScript WebSocket Client | ✅ 40 tests, auto-reconnect, cross-platform | `5daab99` |
| 3 | Batch Operations API | ✅ Create/claim/complete, 20 tests, both SDKs | `5daab99` |
| 4 | Full-Text Search | ✅ FTS5 (SQLite) + tsvector (Postgres), 7 tests, both SDKs | `5daab99` |
| 5 | Cursor Pagination | ✅ `cursor` + `next_cursor`, backward-compatible offset, SDKs | this commit |
| 6 | Webhook Retry + Delivery History | ✅ scheduled retry, DLQ, replay, `GET /hooks/{id}/deliveries` | this commit |
| 7 | Rate Limiting (Per API Key) | ✅ per-minute sliding window + hourly tier quotas, Redis/fallback | this commit |
| 9 | OpenAPI Schema Export & API Explorer | ✅ `/docs`, `/redoc`, `/openapi.json`, exported `docs/openapi.json` | this commit |
| 10 | Redis Pub/Sub for Real-Time Events | ✅ SSEManager, /events endpoint, batch event publishing, Python SDK SSE client, 515 tests | this commit |
| 11 | Multi-Tenant Isolation | ✅ tenant_id enforced on all queries, per-tenant rate limits, tenant CRUD, migration | this commit |
| 13 | Structured Audit Log | ✅ tenant-scoped `GET /api/v1/audit` over lifecycle events | this commit |
| 14 | Schema Validation & Migration Tooling | ✅ Schema Registry CRUD, packet validation, Alembic migration, SDK updates | `b30970b2` |

**Test totals after items 1-14:** 563 Python + 139 TypeScript passing

---

## 📋 Remaining Roadmap (Items 12, 14-15)

These are the features analyzed during the roadmap session on 2026-07-05. Impact and effort ratings are approximate. Pick and choose when ready to implement.

### 8. CLI Tool (`handoffrail` command)
**Impact:** Medium · **Effort:** Medium · **Status:** ✅ Complete (2026-07-08)

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
- 78 CLI tests, all quality gates passing
- Docs added to docs/api-reference.md





### 12. RBAC (Role-Based Access Control)
**Impact:** Medium · **Effort:** High · **Status:** ✅ Complete

Roles added to API keys for finer-grained permissions.

- Roles: `admin` (4), `writer` (3), `agent` (2), `reader` (1)
- `admin`: all operations including key management
- `writer`: create/update/claim/complete packets
- `reader`: list/get/search only
- `agent`: claim/complete packets only (no create)
- Stored on API key, enforced via RBACMiddleware + `require_role()` dependency
- `role` field on API key creation endpoint
- In-memory role cache (5 min TTL) for performance
- Non-admin keys can only create keys with same or lower role

### 14. Schema Validation & Migration Tooling
**Impact:** Medium · **Effort:** Medium · **Status:** ✅ Complete (2026-07-08)

The `context` JSON field is freeform. Add optional schema validation.

- Define JSON Schema for packet `context` field (per use case / framework)
- `POST /packets` accepts optional `schema_id` → validate context against schema
- Schema registry endpoint (`POST /schemas`, `GET /schemas/{id}`)
- Alembic migration helper for schema changes
- Versioned API (`/api/v2/`) preparation
- ✅ 14 new tests, all 563 Python tests passing
- ✅ Schema Registry with full CRUD (SQLAlchemy + Alembic migration 0003_schemas.py)
- ✅ Packet context validation with jsonschema (422 on invalid)
- ✅ Python SDK (SchemaCreate, SchemaResponse, create/list/get)
- ✅ TypeScript SDK (createSchema/listSchema/getSchema)

### 15. Metrics Dashboard (Grafana)
**Impact:** Low · **Effort:** Medium · **Status:** ✅ Complete

Prometheus metrics exposed at `/metrics`. Pre-built Grafana dashboard + monitoring docs.

- JSON dashboard export: `docs/grafana-dashboard.json` (1861 lines)
- Monitoring docs: `docs/monitoring.md` (434 lines) with setup instructions
- Panels: packets by status, throughput, webhook delivery success rate, API latency p50/p95/p99, active agents
- Alert rules: high error rate, webhook failure spike, queue depth

---

## How to Use This Document

When ready to implement the next batch:
1. Pick items by priority (impact × effort ratio)
2. Update the status column
3. Create a branch or work on `master` directly (project preference)
4. Follow the existing code patterns (async SQLAlchemy 2.0, Pydantic v2, structlog)
5. Run quality gates: `pytest tests/ -x -q` + `npm test` + `npm run typecheck`
6. Update `docs/api-reference.md` and regenerate `docs/openapi.json` for any new endpoints
7. Update both Python and TypeScript SDKs
8. Commit and push

All 15 roadmap items are implemented and tested. The project is feature-complete for v0.3.0.

**Next phase:** Advanced features (analytics, event sourcing, production hardening) or new release.

---

_Last updated: 2026-07-05_
