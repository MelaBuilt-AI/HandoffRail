# Deployment Guide

Production deployment guide for HandoffRail — Docker, PostgreSQL, Redis, monitoring, and tier configuration.

## Quick Deploy (Docker Compose)

### Development

```bash
git clone https://github.com/MelaBuilt-AI/handoffrail.git
cd handoffrail
docker compose up --build
```

This starts the API on `http://localhost:8080` with SQLite. Good for local development and testing.

### Production

```bash
# Copy environment template
cp .env.example .env

# Edit with your PostgreSQL credentials
# Required: HR_DATABASE_URL, HR_REDIS_URL

# Start production stack
docker compose -f docker-compose.prod.yml up -d
```

Production compose includes:
- **API** server (HandoffRail FastAPI)
- **PostgreSQL 16** (persistent storage with volume)
- **Redis 7** (caching, future Celery task queue)

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HR_ENVIRONMENT` | `dev` | `dev`, `staging`, or `prod` |
| `HR_DATABASE_URL` | `sqlite+aiosqlite:///./handoffrail.db` | Database connection URL |
| `HR_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `HR_TIER_DEFAULT` | `free` | Default tier for new API keys |
| `HR_LOG_LEVEL` | `info` | Log level: `debug`, `info`, `warning`, `error` |
| `HR_PORT` | `8080` | Server port |
| `HR_CORS_ORIGINS` | `["*"]` | CORS allowed origins (JSON list) |

### Database URL Formats

| Database | URL Format |
|----------|------------|
| SQLite (dev) | `sqlite+aiosqlite:///./handoffrail.db` |
| PostgreSQL | `postgresql://user:pass@host:5432/handoffrail` |
| PostgreSQL (alt) | `postgres://user:pass@host:5432/handoffrail` |

The server auto-detects PostgreSQL and uses the `asyncpg` driver. If `DATABASE_URL` is omitted, it falls back to SQLite for development.

---

## PostgreSQL Setup

### 1. Create Database

```sql
CREATE DATABASE handoffrail;
CREATE USER handoffrail WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE handoffrail TO handoffrail;
```

### 2. Set Connection String

```bash
export HR_DATABASE_URL="postgresql://handoffrail:your_secure_password@localhost:5432/handoffrail"
```

### 3. Run Migrations

```bash
cd server
alembic upgrade head
```

### 4. Start the Server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### Production Docker Compose

The `docker-compose.prod.yml` includes:

```yaml
services:
  api:
    build: .
    ports:
      - "8080:8080"
    environment:
      HR_ENVIRONMENT: prod
      HR_DATABASE_URL: postgresql://handoffrail:${DB_PASSWORD}@db:5432/handoffrail
      HR_REDIS_URL: redis://redis:6379/0
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: handoffrail
      POSTGRES_USER: handoffrail
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U handoffrail"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
  redisdata:
```

---

## Tier Configuration

Tier quotas are configured via environment or `config.py`:

| Feature | Free | Pro | Business |
|---------|------|-----|----------|
| Handoffs/day | 5 | Unlimited | Unlimited |
| Max agents | 2 | 10 | 50 |
| Max API keys | 1 | 5 | 25 |
| Max packet size | 64 KB | 256 KB | 1 MB |
| Rate limit (req/hr) | 100 | 1,000 | 10,000 |
| Webhooks | ❌ | ✅ (5) | ✅ (Unlimited) |
| Audit trail | ❌ | ✅ (30 days) | ✅ (Full + export) |

### Custom Tier Configuration

Override in environment (JSON):

```bash
export HR_TIER_QUOTAS='{
  "free": {"handoffs_per_day": 10, "max_agents": 3, "max_api_keys": 2, "max_packet_size": 65536, "unlimited_handoffs": false},
  "pro": {"handoffs_per_day": 0, "max_agents": 20, "max_api_keys": 10, "max_packet_size": 524288, "unlimited_handoffs": true}
}'
```

---

## Health & Monitoring

### Endpoints

| Endpoint | Purpose | Auth Required |
|----------|---------|---------------|
| `GET /health` | Liveness probe — returns 200 if process is running | No |
| `GET /ready` | Readiness probe — returns 200 if DB connected, 503 if not | No |
| `GET /metrics` | Prometheus metrics | No |

### Prometheus Metrics

Standard Prometheus format at `/metrics`:

```
# HELP handoffrail_requests_total Total HTTP requests
# TYPE handoffrail_requests_total counter
handoffrail_requests_total{method="POST",endpoint="/api/v1/packets",status_code="201"} 142

# HELP handoffrail_request_latency_seconds Request latency
# TYPE handoffrail_request_latency_seconds histogram
handoffrail_request_latency_seconds_bucket{method="POST",endpoint="/api/v1/packets",le="0.1"} 128

# HELP handoffrail_active_packets Currently active (non-terminal) packets
# TYPE handoffrail_active_packets gauge
handoffrail_active_packets 23

# HELP handoffrail_handoffs_total Completed handoffs per tenant
# TYPE handoffrail_handoffs_total counter
handoffrail_handoffs_total{tenant_id="abc123"} 89
```

### Prometheus Scrape Config

```yaml
scrape_configs:
  - job_name: 'handoffrail'
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:8080']
    metrics_path: /metrics
```

### Kubernetes Probes

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10
```

---

## Structured Logging

HandoffRail uses `structlog` for structured JSON logging:

```json
{
  "event": "packet_created",
  "packet_id": "a1b2c3d4-...",
  "source_agent": "sales-01",
  "target_agent": "billing-01",
  "priority": "high",
  "tenant_id": "abc123",
  "timestamp": "2026-05-30T19:35:00Z",
  "level": "info"
}
```

Configure log level:

```bash
export HR_LOG_LEVEL=debug  # dev
export HR_LOG_LEVEL=warning # prod
```

---

## CORS

Default: allows all origins (`["*"]`). For production, restrict:

```bash
export HR_CORS_ORIGINS='["https://your-app.com", "https://admin.your-app.com"]'
```

A warning is logged if `CORS_ORIGINS=["*"]` is set in production mode.

---

## Reverse Proxy (nginx)

```nginx
server {
    listen 443 ssl;
    server_name api.handoffrail.dev;

    ssl_certificate /etc/letsencrypt/live/api.handoffrail.dev/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.handoffrail.dev/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## Backups

### SQLite (Dev)

```bash
# Simple file copy (stop the server first)
cp handoffrail.db handoffrail.db.backup
```

### PostgreSQL (Prod)

```bash
# pg_dump
pg_dump -U handoffrail -d handoffrail -F c -f backup_$(date +%Y%m%d).dump

# Restore
pg_restore -U handoffrail -d handoffrail backup_20260530.dump
```

### Automated Backups (Cron)

```bash
# Add to crontab (daily at 2am)
0 2 * * * pg_dump -U handoffrail -d handoffrail -F c -f /backups/handoffrail_$(date +\%Y\%m\%d).dump
```

---

## Scaling Considerations

| Concern | Recommendation |
|---------|---------------|
| **Single-server bottlenecks** | Run multiple API instances behind a load balancer. PostgreSQL handles concurrent connections. |
| **Connection pooling** | SQLAlchemy async pool is built-in. Tune `pool_size` and `max_overflow` for your workload. |
| **Redis caching** | Enable for session caching and rate limit counters. Required for multi-instance deployments. |
| **WebSocket scaling** | (v0.2) Redis Pub/Sub for event broadcasting across instances. |
| **Large packet storage** | Keep artifacts small (<1MB). Reference external storage (S3, GCS) for large files. |

---

## Security Checklist

- [ ] HTTPS enabled (TLS termination at reverse proxy or load balancer)
- [ ] API keys are hashed at rest
- [ ] CORS origins restricted in production
- [ ] Rate limiting enabled per tier
- [ ] Packet size limits enforced
- [ ] PostgreSQL credentials stored securely (env vars, not code)
- [ ] Redis not exposed to public internet
- [ ] Webhook secrets minimum 16 characters
- [ ] HMAC-SHA256 webhook signature verification implemented on receiver
- [ ] Health endpoints don't expose sensitive data
- [ ] Structured logging doesn't leak API keys or packet contents