# HandoffRail Production Deployment Guide

> Deploy HandoffRail to production with Docker Compose, PostgreSQL, Redis, TLS, monitoring, and automated backups.

**Estimated time:** 20–30 minutes for a fresh VM.  
**Scope:** Single-server Docker Compose. For Kubernetes, adapt the compose services to manifests using the same images and env vars.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Configuration & Secrets](#configuration--secrets)
- [Database Migrations](#database-migrations)
- [Docker Compose Production Startup](#docker-compose-production-startup)
- [Reverse Proxy & TLS](#reverse-proxy--tls)
- [Health Checks](#health-checks)
- [Observability & Grafana](#observability--grafana)
- [Backups & Restore](#backups--restore)
- [Scaling Considerations](#scaling-considerations)
- [Rollback & Troubleshooting](#rollback--troubleshooting)
- [Security Checklist](#security-checklist)

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Docker Engine | 24.0+ | `docker --version` |
| Docker Compose | 2.20+ | `docker compose version` |
| PostgreSQL client tools | 16+ | For manual `pg_dump` / `pg_restore` |
| TLS certificate | — | Let’s Encrypt, Cloudflare Origin CA, or purchased cert |
| (Optional) Redis CLI | 7+ | For ad-hoc inspection |

### Host sizing (minimum / recommended)

| Workload | CPU | RAM | Disk |
|----------|-----|-----|------|
| Light (< 1k handoffs/day) | 1 core | 2 GB | 20 GB SSD |
| Medium (1–10k handoffs/day) | 2 cores | 4 GB | 40 GB SSD |
| Heavy (> 10k handoffs/day) | 4+ cores | 8 GB | 100 GB SSD |

---

## Configuration & Secrets

### 1. Clone the repository

```bash
git clone https://github.com/MelaBuilt-AI/handoffrail.git
cd handoffrail
```

### 2. Create your environment file

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env` with production values. **Do not commit this file.**

```bash
# ── Core ───────────────────────────────────────
HR_ENVIRONMENT=prod
HR_LOG_LEVEL=warning
HR_PORT=8080

# ── Database ───────────────────────────────────
# Use a strong password. If the DB runs inside Compose, host is 'db'.
HR_DATABASE_URL=postgresql+asyncpg://handoffrail:CHANGE_ME_STRONG_PASSWORD@db:5432/handoffrail
POSTGRES_USER=handoffrail
POSTGRES_PASSWORD=CHANGE_ME_STRONG_PASSWORD
POSTGRES_DB=handoffrail

# ── Redis ──────────────────────────────────────
HR_REDIS_URL=redis://redis:6379/0

# ── CORS ───────────────────────────────────────
# Restrict to your actual front-end domains in production.
HR_CORS_ORIGINS=["https://app.yourdomain.com","https://admin.yourdomain.com"]
```

### Environment variable reference

| Variable | Default | Required in prod? | Description |
|----------|---------|-------------------|-------------|
| `HR_ENVIRONMENT` | `dev` | ✅ | Must be `prod` |
| `HR_DATABASE_URL` | SQLite local | ✅ | PostgreSQL asyncpg URL |
| `HR_REDIS_URL` | `redis://localhost:6379/0` | ✅ | Redis URL (Compose service name `redis`) |
| `HR_LOG_LEVEL` | `info` | Recommended | `debug`, `info`, `warning`, `error` |
| `HR_PORT` | `8080` | Optional | Container port (map via Compose) |
| `HR_CORS_ORIGINS` | `["*"]` | ✅ | JSON list of allowed origins |
| `HR_TIER_DEFAULT` | `free` | Optional | Default tier for new API keys |
| `HR_TIER_QUOTAS` | (built-in) | Optional | Override tier quotas as JSON |
| `POSTGRES_USER` | `handoffrail` | ✅ | DB superuser name |
| `POSTGRES_PASSWORD` | — | ✅ | DB superuser password |
| `POSTGRES_DB` | `handoffrail` | ✅ | Database name |

> **Security note:** HandoffRail logs a warning if `HR_CORS_ORIGINS=["*"]` is used in production. The API key hash is never logged, but webhook payloads and packet summaries may appear in debug logs — use `warning` or `error` in prod.

---

## Database Migrations

HandoffRail uses **Alembic** (SQLAlchemy migrations). The production compose includes a one-shot `migration` service that runs automatically before the API starts.

### How migrations work in production

```yaml
# Inside docker-compose.prod.yml
  migration:
    build:
      context: .
      dockerfile: Dockerfile
    command: ["alembic", "upgrade", "head"]
    environment:
      - HR_DATABASE_URL=...
    depends_on:
      db:
        condition: service_healthy
    restart: "no"
```

The `api` service waits for:
1. `db` healthy (PostgreSQL ready)
2. `redis` healthy
3. `migration` completed successfully

### Manual migration (if needed)

```bash
# Run from the repo root
docker compose -f docker-compose.prod.yml run --rm migration alembic upgrade head
```

### Check migration history

```bash
docker compose -f docker-compose.prod.yml run --rm migration alembic history
```

### Current migration files

| Revision | Description |
|----------|-------------|
| `0001_initial.py` | Base tables: packets, events, webhooks, API keys |
| `0002_tenants.py` | Multi-tenant support |
| `0003_schemas.py` | Schema validation & metadata |
| `0004_rbac.py` | Role-based access control |

> **Tip:** Always back up the database before applying new migrations on a live system.

---

## Docker Compose Production Startup

### 1. Pull and build

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml build
```

### 2. Start the stack

```bash
docker compose -f docker-compose.prod.yml up -d
```

### 3. Verify all services are healthy

```bash
docker compose -f docker-compose.prod.yml ps
```

Expected output:

```
NAME                    STATUS
handoffrail-api-1       Up 30s (healthy)
handoffrail-migration-1 Exited (0)
handoffrail-db-1        Up 30s (healthy)
handoffrail-redis-1     Up 30s (healthy)
```

### 4. Smoke test

```bash
# Liveness
curl http://localhost:8080/health
# → {"status":"ok","service":"handoffrail"}

# Readiness (checks DB)
curl http://localhost:8080/ready
# → {"status":"ready","service":"handoffrail","db":true}

# Metrics
curl http://localhost:8080/metrics | head
```

### What the compose stack includes

| Service | Image | Purpose | Persistence |
|---------|-------|---------|-------------|
| `api` | Built from `Dockerfile` | FastAPI application | None (stateless) |
| `db` | `postgres:16-alpine` | Primary database | `pg-data` volume |
| `redis` | `redis:7-alpine` | Caching, pub/sub | `redis-data` volume |
| `migration` | Built from `Dockerfile` | One-shot Alembic run | None |

### Stopping and restarting

```bash
# Graceful stop
docker compose -f docker-compose.prod.yml down

# Stop and remove volumes (⚠️ destroys data)
docker compose -f docker-compose.prod.yml down -v

# Restart after code update
docker compose -f docker-compose.prod.yml up -d --build
```

---

## Reverse Proxy & TLS

**Never expose the FastAPI container directly to the internet in production.** Use a reverse proxy for TLS termination, rate limiting, and static file serving.

### Option A: Caddy (recommended — automatic TLS)

```bash
# Install Caddy: https://caddyserver.com/docs/install
```

`Caddyfile`:

```caddy
api.handoffrail.yourdomain.com {
    reverse_proxy localhost:8080

    # Security headers
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
    }

    # Optional: restrict /metrics to internal IPs
    @metrics {
        path /metrics
        not remote_ip 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 127.0.0.1
    }
    respond @metrics 403
}
```

```bash
caddy reload
```

### Option B: nginx

```nginx
server {
    listen 443 ssl http2;
    server_name api.handoffrail.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/api.handoffrail.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.handoffrail.yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Optional: block /metrics from public
    location /metrics {
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        allow 192.168.0.0/16;
        allow 127.0.0.1;
        deny all;
        proxy_pass http://127.0.0.1:8080;
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts for long-running HITL operations
        proxy_read_timeout 60s;
        proxy_connect_timeout 10s;
    }
}

# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name api.handoffrail.yourdomain.com;
    return 301 https://$server_name$request_uri;
}
```

### Option C: Cloudflare Tunnel (zero-config TLS)

```bash
cloudflared tunnel --no-autoupdate run --token $TUNNEL_TOKEN
```

Point the tunnel to `http://localhost:8080`. No cert management required.

---

## Health Checks

### Endpoint summary

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/health` | `GET` | No | Liveness — process is running |
| `/ready` | `GET` | No | Readiness — DB connection OK |
| `/metrics` | `GET` | No | Prometheus metrics |

### Docker Compose health checks

Already configured in `docker-compose.prod.yml`:

```yaml
healthcheck:
  test: ["CMD", "python", "-c",
    "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]
  interval: 30s
  timeout: 5s
  start_period: 15s
  retries: 3
```

### Kubernetes probes (if migrating to K8s)

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

### Uptime monitoring (external)

Configure your uptime checker (UptimeRobot, Pingdom, Grafana OnCall) to hit:

- `GET https://api.yourdomain.com/health` — expect 200, < 2s response
- `GET https://api.yourdomain.com/ready` — expect 200 (alerts if DB is down)

---

## Observability & Grafana

HandoffRail exposes **Prometheus** metrics at `/metrics`. For a full monitoring stack, see [`docs/monitoring.md`](monitoring.md) for detailed Prometheus + Grafana setup, dashboard import, and alert rules.

### Quick-start monitoring stack

Add to a new `docker-compose.monitoring.yml`:

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.enable-lifecycle'

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-changeme}

volumes:
  prometheus_data:
  grafana_data:
```

`prometheus.yml`:

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'handoffrail'
    static_configs:
      - targets: ['api:8080']
    metrics_path: /metrics
```

### Key metrics to watch

| Metric | Type | Alert if |
|--------|------|----------|
| `handoffrail_requests_total` | Counter | Rate drops to zero unexpectedly |
| `handoffrail_request_latency_seconds` | Histogram | p95 > 500ms sustained |
| `handoffrail_active_packets` | Gauge | Growing unbounded (leak indicator) |
| `handoffrail_webhook_dlq_size` | Gauge | > 100 (dead letter queue backlog) |
| `handoffrail_webhook_deliveries_total{result="failed"}` | Counter | Failure rate > 10% |

### Grafana dashboard

Import `docs/grafana-dashboard.json` into Grafana. It includes:

- Overview row (active packets, handoffs, error rate)
- Packet throughput panels
- Webhook delivery health
- API latency percentiles (p50 / p95 / p99)
- HITL & API key operations
- Built-in alert rules for error rate, webhook failures, and queue depth

> **Security:** Restrict `/metrics` access in production. It exposes `tenant_id` labels and operational counters that could aid reconnaissance.

---

## Backups & Restore

### Automated PostgreSQL backups

Run this from a cron job on the host or a backup container:

```bash
#!/bin/bash
# /opt/handoffrail/backup.sh
set -e

BACKUP_DIR="/backups/handoffrail"
DATE=$(date +%Y%m%d_%H%M%S)
CONTAINER="handoffrail-db-1"

mkdir -p "$BACKUP_DIR"

docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTAINER" \
  pg_dump -U handoffrail -d handoffrail -F c -f "/tmp/backup_$DATE.dump"

docker cp "$CONTAINER:/tmp/backup_$DATE.dump" "$BACKUP_DIR/"
docker exec "$CONTAINER" rm "/tmp/backup_$DATE.dump"

# Keep last 14 days
find "$BACKUP_DIR" -name "backup_*.dump" -mtime +14 -delete

echo "Backup complete: $BACKUP_DIR/backup_$DATE.dump"
```

Add to crontab (daily at 2 AM):

```bash
0 2 * * * /opt/handoffrail/backup.sh >> /var/log/handoffrail-backup.log 2>&1
```

### Restore from backup

```bash
# 1. Stop the API (keep DB running)
docker compose -f docker-compose.prod.yml stop api

# 2. Restore
docker cp backup_20260709_020000.dump handoffrail-db-1:/tmp/restore.dump
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" -it handoffrail-db-1 \
  pg_restore -U handoffrail -d handoffrail --clean --if-exists /tmp/restore.dump

# 3. Restart
docker compose -f docker-compose.prod.yml start api
```

### Redis backup (RDB)

Redis persists to `/data/dump.rdb` inside the `redis-data` volume by default. Back up the volume:

```bash
docker run --rm -v handoffrail_redis-data:/data -v /backups:/backups alpine \
  tar czf /backups/redis_$(date +%Y%m%d).tar.gz -C /data .
```

> **Note:** Redis is used for caching and pub/sub. Losing Redis data is inconvenient but not catastrophic — no persistent application state lives there.

### Volume-level snapshot (nuclear option)

```bash
# Stop everything first
docker compose -f docker-compose.prod.yml down

# Snapshot volumes
docker run --rm \
  -v handoffrail_pg-data:/pg -v handoffrail_redis-data:/redis \
  -v /backups:/backups alpine tar czf /backups/handoffrail_full_$(date +%Y%m%d).tar.gz -C /pg . -C /redis .

# Restart
docker compose -f docker-compose.prod.yml up -d
```

---

## Scaling Considerations

### Vertical scaling (single server)

- Increase container CPU / memory limits in `docker-compose.prod.yml`
- Tune PostgreSQL: `shared_buffers`, `work_mem`, `max_connections`
- Tune Uvicorn workers: set `UVICORN_WORKERS` or override the CMD

```yaml
  api:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
    environment:
      - UVICORN_WORKERS=4
```

### Horizontal scaling (multi-instance)

For load-balanced deployments:

1. **External PostgreSQL & Redis** — Run DB and cache on dedicated hosts or managed services (AWS RDS, GCP Cloud SQL, Upstash Redis).
2. **Stateless API containers** — Run multiple `api` replicas behind a load balancer. Each replica connects to the same DB and Redis.
3. **Sticky sessions not required** — WebSocket and SSE connections use Redis pub/sub for cross-instance broadcast.
4. **Session affinity** — Not needed for REST API calls. WebSocket clients will reconnect to any healthy instance.

```yaml
# Example: 3 API replicas with external DB
services:
  api:
    deploy:
      replicas: 3
    environment:
      - HR_DATABASE_URL=postgresql+asyncpg://handoffrail:***@db.internal:5432/handoffrail
      - HR_REDIS_URL=redis://redis.internal:6379/0
```

### Connection pooling

SQLAlchemy async pool is built-in. For high-throughput workloads, tune via environment or `config.py`:

```python
# In server/app/config.py or override via env
pool_size = 20
max_overflow = 30
pool_timeout = 30
```

### Large packet storage

Keep packet artifacts under the tier limit (1 MB for Business). For larger files:

- Store references (S3 / GCS URLs) in `artifacts` instead of inline base64
- Use pre-signed URLs for upload/download
- Keep HandoffRail as the metadata layer, not the blob store

---

## Rollback & Troubleshooting

### Rolling back a bad deployment

```bash
# 1. Revert to previous image tag or Git commit
git checkout <previous-commit>
docker compose -f docker-compose.prod.yml up -d --build

# 2. If database schema changed, downgrade migration
docker compose -f docker-compose.prod.yml run --rm migration alembic downgrade -1
```

> **Always back up the database before deploying schema changes.**

### Common issues

#### API container exits immediately

```bash
docker compose -f docker-compose.prod.yml logs api
```

**Causes:**
- DB not ready → check `db` health: `docker compose -f docker-compose.prod.yml logs db`
- Migration failed → run manually and inspect error
- Missing env var → verify `.env` is readable and all required vars are set

#### `/ready` returns 503

```bash
curl http://localhost:8080/ready
```

- PostgreSQL is down or unreachable
- Wrong `HR_DATABASE_URL` host (use `db` inside Compose, not `localhost`)
- Network partition between `api` and `db` containers

#### `/metrics` empty or missing data

- Server just started — generate some traffic first
- Prometheus can't reach the endpoint — verify scrape target and firewall
- Wrong port/path — must be `http://<host>:8080/metrics`

#### High memory usage

- Check for memory leaks in custom adapters or webhook handlers
- Reduce `UVICORN_WORKERS` if over-provisioned
- Monitor `handoffrail_active_packets` — unbounded growth indicates packets not being completed/expired

#### Webhook delivery failures

```bash
# Check DLQ size
curl http://localhost:8080/metrics | grep webhook_dlq_size
```

- Verify webhook target SSL certificates
- Check target endpoint availability and timeout settings
- Review webhook logs for HMAC signature mismatches

#### Database connection errors under load

- Increase PostgreSQL `max_connections`
- Tune SQLAlchemy pool size and overflow
- Consider PgBouncer for connection pooling at the DB layer

### Getting help

1. Check logs: `docker compose -f docker-compose.prod.yml logs -f api`
2. Check metrics: `curl http://localhost:8080/metrics`
3. Review [`docs/monitoring.md`](monitoring.md) for alert troubleshooting
4. Open an issue with: logs, `.env` (redact passwords), and `docker compose ps` output

---

## Security Checklist

- [ ] `.env` file has `chmod 600` and is in `.gitignore`
- [ ] `HR_ENVIRONMENT=prod` is set
- [ ] `HR_CORS_ORIGINS` restricted to actual domains (not `["*"]`)
- [ ] `HR_LOG_LEVEL` is `warning` or `error` in production
- [ ] PostgreSQL password is strong and unique
- [ ] Redis is not exposed to the public internet (no host port mapping, or firewall restricted)
- [ ] `/metrics` is blocked from public access (firewall or reverse proxy)
- [ ] TLS 1.2+ enabled on reverse proxy
- [ ] Security headers set (HSTS, X-Frame-Options, etc.)
- [ ] Automated backups are configured and tested
- [ ] API keys are hashed at rest (handled by application)
- [ ] Webhook secrets are ≥ 16 characters
- [ ] Webhook receivers verify HMAC-SHA256 signatures
- [ ] Health endpoints do not expose sensitive data
- [ ] Container runs as non-root user (`handoffrail`)
- [ ] Docker images are scanned for CVEs before deployment

---

_Last updated: 2026-07-09_
