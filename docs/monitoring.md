# HandoffRail Monitoring Setup

This guide covers how to set up and configure monitoring for HandoffRail using Prometheus and Grafana.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Prometheus Configuration](#prometheus-configuration)
- [Grafana Dashboard Import](#grafana-dashboard-import)
- [Alert Rules](#alert-rules)
- [PagerDuty Integration (Optional)](#pagerduty-integration-optional)
- [Available Metrics Reference](#available-metrics-reference)
- [Troubleshooting](#troubleshooting)

## Architecture Overview

```
┌─────────────────────┐      scrape (30s)      ┌──────────────┐      query       ┌────────┐
│  HandoffRail Server │  ──────────────────▶   │  Prometheus  │  ◀─────────────   │ Grafana │
│                     │    GET /metrics         │              │                  │        │
│  PrometheusClient   │                        │  TSDB         │                  │ Dashboard │
│  Middleware + Router│                        │  Alertmanager │                  │ Alerts  │
└─────────────────────┘                        └──────────────┘                  └────────┘
```

HandoffRail exposes Prometheus-format metrics at the `GET /metrics` endpoint. A Prometheus server scrapes this endpoint, and Grafana visualizes the data. Alerting rules fire through Grafana Alerting or Prometheus Alertmanager.

## Prometheus Configuration

### Step 1: Verify Metrics Endpoint

HandoffRail exposes metrics automatically via `prometheus-client` at `/metrics`:

```bash
curl http://localhost:8000/metrics
```

You should see output like:

```
# HELP handoffrail_requests_total Total count of requests
# TYPE handoffrail_requests_total counter
handoffrail_requests_total{method="GET",endpoint="/health",status_code="200"} 42.0
# HELP handoffrail_active_packets Number of active (non-terminal) packets
# TYPE handoffrail_active_packets gauge
handoffrail_active_packets 7.0
...
```

If the endpoint returns empty or no data, ensure the server is running and Prometheus is correctly configured (see [Troubleshooting](#troubleshooting)).

### Step 2: Add Scrape Target to Prometheus

Add the following job to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'handoffrail'
    scrape_interval: 15s
    scrape_timeout: 10s
    metrics_path: /metrics
    static_configs:
      - targets:
          - 'localhost:8000'    # Adjust host:port to your HandoffRail server
        labels:
          service: handoffrail
          env: production
```

**Important notes:**

- Set `scrape_interval` to `15s` or lower for responsive dashboards. The metrics middleware has negligible overhead.
- If running HandoffRail behind a reverse proxy (nginx, Caddy), ensure `/metrics` is forwarded or add a dedicated port for metrics.
- In production environments, **restrict access** to `/metrics` — it can leak tenant_id labels and operational data. Use firewall rules, a separate metrics port, or authentication.

### Step 3: Reload Prometheus

```bash
# If running as a systemd service
sudo systemctl reload prometheus

# Or send SIGHUP
kill -HUP $(pgrep prometheus)

# Or use the API
curl -X POST http://localhost:9090/-/reload
```

### Docker Compose (Quick Start)

For a quick local setup, add Prometheus to your `docker-compose.yml`:

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
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
      - '--web.enable-lifecycle'

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin  # Change in production!
    depends_on:
      - prometheus

volumes:
  prometheus_data:
  grafana_data:
```

## Grafana Dashboard Import

### Step 1: Add Prometheus Data Source

1. Open Grafana at `http://localhost:3000` (default credentials: `admin`/`admin`)
2. Navigate to **Configuration → Data Sources → Add data source**
3. Select **Prometheus**
4. Configure:
   - **Name:** `HandoffRail Prometheus` (or whatever you prefer)
   - **URL:** `http://prometheus:9090` (Docker) or `http://localhost:9090` (host)
   - **Scrape interval:** `15s`
   - **Timeout:** `10s`
   - **HTTP Method:** `GET`
5. Click **Save & Test** — you should see a green "Data source is working" message

### Step 2: Import the Dashboard

1. Navigate to **Dashboards → New → Import**
2. Upload the `docs/grafana-dashboard.json` file (or paste its contents)
3. Select the **Prometheus** data source when prompted (the one you created above)
4. Click **Import**

The dashboard should immediately populate with panels. If panels show "No data", verify:

- Prometheus can reach `http://handoffrail-server:8000/metrics`
- HandoffRail has received at least some traffic (metrics are zero-initialized)
- The data source UID matches what was selected during import

### Dashboard Layout

The dashboard is organized into section rows:

| Row | Panels | Purpose |
|-----|--------|---------|
| **Overview** | Active Packets, Total Handoffs, DLQ Size, Error Rate, Request Rate, Active Agents | At-a-glance health |
| **Packet Throughput** | Packets by Status (pie), Create/Claim/Complete per Minute (time series) | Packet lifecycle |
| **Webhook Delivery Health** | Success Rate, Deliveries by Result | Webhook reliability |
| **API Latency** | p50/p95/p99, Latency by Endpoint, Request Rate by Endpoint | Performance |
| **HITL & API Ops** | HITL Operations, API Key Operations, Chain Depth, Status Codes | Operational details |

### Dashboard Variables

The dashboard includes two template variables:

- **`$tenant`** — Filter by tenant. Auto-populated from `handoffrail_handoffs_total` labels.
- **`$endpoint`** — Filter by API endpoint. Auto-populated from `handoffrail_requests_total` labels.

Both support multi-select and "All" to view aggregate data.

## Alert Rules

The dashboard includes three built-in alert rules. They fire through **Grafana Alerting** (Grafana-managed alert rules).

### Alert: High Error Rate (Critical)

Fires when HTTP 5xx errors exceed **5%** over a 5-minute rolling window.

- **Query:** `(sum(rate(handoffrail_requests_total{status_code=~"5.."}[5m])) / sum(rate(handoffrail_requests_total[5m]))) * 100`
- **Threshold:** `> 5`
- **Duration:** 2 minutes before firing
- **Severity:** `critical`
- **Typical causes:**
  - Downstream dependencies unavailable (database, Redis, webhook targets)
  - Configuration errors
  - Resource exhaustion (connections, threads, file handles)
- **Response:**
  1. Check HandoffRail server logs
  2. Verify database and Redis connectivity
  3. Inspect webhook target endpoints

### Alert: Webhook Failure Spike (Critical)

Fires when webhook delivery failure rate exceeds **10%** over a 5-minute window.

- **Query:** `(sum(rate(handoffrail_webhook_deliveries_total{result="failed"}[5m])) / sum(rate(handoffrail_webhook_deliveries_total[5m]))) * 100`
- **Threshold:** `> 10`
- **Duration:** 2 minutes before firing
- **Severity:** `critical`
- **Typical causes:**
  - Webhook target endpoint down or timing out
  - TLS certificate expired or misconfigured
  - Network issues between HandoffRail and webhook targets
- **Response:**
  1. Check webhook target availability
  2. Review webhook error logs in HandoffRail
  3. Verify webhook target SSL certificates

### Alert: Queue Depth Exceeded (Warning)

Fires when the webhook dead-letter queue exceeds **100** messages.

- **Query:** `handoffrail_webhook_dlq_size > 100`
- **Threshold:** `> 100`
- **Duration:** 1 minute before firing
- **Severity:** `warning`
- **Typical causes:**
  - Sustained webhook delivery failures
  - Backend processing backlog
  - Misconfigured retry policy
- **Response:**
  1. Examine DLQ contents
  2. Manually retry or replay failed deliveries
  3. Adjust webhook retry configuration if appropriate

### Alert Rule Configuration

To customize the alert rules after import:

1. In Grafana, go to **Alerting → Alert rules**
2. Find the `HandoffRail` rule group
3. Click each rule to edit thresholds, duration, labels, or notification routing
4. For production, add appropriate labels (e.g., `severity`, `team`, `slack_channel`) for routing

### Prometheus Alertmanager Setup (Alternative)

If you prefer Prometheus Alertmanager over Grafana Alerting, add these rules to your `alertmanager.yml`:

```yaml
groups:
  - name: HandoffRail
    rules:
      - alert: HandoffRailHighErrorRate
        expr: (sum(rate(handoffrail_requests_total{status_code=~"5.."}[5m])) / sum(rate(handoffrail_requests_total[5m]))) * 100 > 5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "HandoffRail error rate > 5%"
          description: "Error rate is {{ $value | humanize }}% over 5m"

      - alert: HandoffRailWebhookFailureSpike
        expr: (sum(rate(handoffrail_webhook_deliveries_total{result="failed"}[5m])) / sum(rate(handoffrail_webhook_deliveries_total[5m]))) * 100 > 10
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "HandoffRail webhook failure rate > 10%"
          description: "Webhook failure rate is {{ $value | humanize }}% over 5m"

      - alert: HandoffRailQueueDepthExceeded
        expr: handoffrail_webhook_dlq_size > 100
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "HandoffRail webhook DLQ > 100"
          description: "DLQ size is {{ $value }}"
```

## PagerDuty Integration (Optional)

### Grafana Alerting → PagerDuty

1. In Grafana, go to **Alerting → Contact points**
2. Click **Add contact point**
3. Name it (e.g., `PagerDuty HandoffRail`)
4. Type: **PagerDuty**
5. Enter your **Integration Key** (from PagerDuty Service → Integrations → Events API v2)
6. Click **Test** to verify the connection
7. In **Alerting → Notification policies**, route the `HandoffRail` rule group to this contact point

### Prometheus Alertmanager → PagerDuty

Add to your `alertmanager.yml`:

```yaml
route:
  group_by: ['alertname', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'pagerduty'
  routes:
    - match:
        service: handoffrail
        severity: critical
      receiver: pagerduty-critical

receivers:
  - name: pagerduty-critical
    pagerduty_configs:
      - routing_key: YOUR_PD_INTEGRATION_KEY
        severity: critical
        description: '{{ template "pd.default.description" . }}'
        details:
          firing: '{{ template "pd.default.instances" . }}'
          resolved: '{{ template "pd.default.instances" . }}'
          num_firing: '{{ .Alerts.Firing | len }}'
          num_resolved: '{{ .Alerts.Resolved | len }}'
          group_labels: '{{ template "pd.default.group_labels" . }}'
        images:
          - href: 'https://handoffrail.melabuilt.ai/assets/logo.png'
            alt: 'HandoffRail Logo'
```

### Setting Up the PagerDuty Integration Key

1. Log in to your **PagerDuty** account
2. Go to **Services → Service Directory**
3. Create a new service (or use an existing one) for HandoffRail
4. Under **Integrations**, select **Events API v2**
5. Copy the **Integration Key**
6. Add it to Grafana or Alertmanager as shown above

## Available Metrics Reference

### Request Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `handoffrail_requests_total` | Counter | `method`, `endpoint`, `status_code` | Total HTTP request count |
| `handoffrail_request_latency_seconds` | Histogram | `method`, `endpoint` | Request latency buckets (5ms–10s) |

### Packet Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `handoffrail_active_packets` | Gauge | — | Count of active (non-terminal) packets |
| `handoffrail_handoffs_total` | Counter | `tenant_id` | Handoff packet creations |
| `handoffrail_packet_status_count` | Gauge | `status` | Packets by current lifecycle status |
| `handoffrail_chain_depth` | Histogram | — | Chain depth (ancestor count) distribution |

### Webhook Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `handoffrail_webhook_deliveries_total` | Counter | `webhook_id`, `event_type`, `result` | Webhook delivery attempts |
| `handoffrail_webhook_dlq_size` | Gauge | `tenant_id` | Dead-letter queue depth |

### Human-in-the-Loop Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `handoffrail_hitl_checkpoints_total` | Counter | `tenant_id` | HITL checkpoints created |
| `handoffrail_hitl_responses_total` | Counter | `tenant_id` | HITL responses received |

### API Key Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `handoffrail_api_key_operations_total` | Counter | `operation` | API key operations (created, revoked, rotated) |

### Commonly Used PromQL Queries

```promql
# Request rate (HTTP) over the last 5 minutes
sum(rate(handoffrail_requests_total[5m]))

# Error ratio
sum(rate(handoffrail_requests_total{status_code=~"5.."}[5m])) / sum(rate(handoffrail_requests_total[5m]))

# Handoff creation rate per tenant
sum(rate(handoffrail_handoffs_total[5m])) by (tenant_id)

# Webhook success rate
sum(rate(handoffrail_webhook_deliveries_total{result="success"}[5m])) / sum(rate(handoffrail_webhook_deliveries_total[5m]))

# p95 latency
histogram_quantile(0.95, sum(rate(handoffrail_request_latency_seconds_bucket[5m])) by (le))

# Active packets (check if > 0 serves as health signal)
handoffrail_active_packets
```

## Troubleshooting

### Metrics Endpoint Returns Empty

**Symptom:** `GET /metrics` returns zero data or only comment lines.

**Causes & fixes:**

1. **Server just started** — Some metrics (gauges like `handoffrail_active_packets`) show zero until explicitly set. Generate a few test requests.
2. **Middleware not registered** — Check `main.py` that `PrometheusMiddleware` is added to the ASGI app. It should be registered in `create_app()`.
3. **Wrong endpoint** — Verify the path is `/metrics` (lowercase, no trailing slash).

### Grafana Panels Show "No data"

**Causes & fixes:**

1. **Data source mismatch** — During dashboard import, verify you selected the correct Prometheus data source. Check the data source UID in the JSON.
2. **Prometheus can't reach HandoffRail** — From the Prometheus server, test: `curl http://handoffrail-server:8000/metrics`
3. **Metric names don't match** — Check the exact metric names in your `/metrics` output; ensure they match the PromQL queries. The queries use `handoffrail_` prefix throughout.
4. **No data in time range** — Extend the time range in the dashboard to include periods with traffic.

### Alerts Not Firing

**Causes & fixes:**

1. **Grafana Alerting not enabled** — Ensure Grafana Alerting is enabled in your `grafana.ini`: `[alerting] enabled = true`
2. **Evaluation interval** — Alert rules evaluate every 1 minute by default. The "for" duration must pass before the alert fires.
3. **Insufficient data** — Some alerts need rate data over a 5-minute window. If the server has been running less than 5 minutes, the alert won't evaluate.
4. **No data state** — By default, alerts are OK on no data. If the target is down, alerts won't fire. Adjust `noDataState` in the alert rule if needed.

### Contact Points Not Delivering

1. Verify the contact point type (PagerDuty, Slack, email) is correctly configured
2. Check Grafana logs for delivery errors
3. For PagerDuty: confirm the integration key is active in PagerDuty Events API v2
4. Test the contact point from Grafana's Alerting settings

## Maintenance

- **Dashboard versioning:** The dashboard JSON is stored in `docs/grafana-dashboard.json`. Keep it version-controlled alongside the codebase.
- **Updates:** After modifying the dashboard in Grafana, export it (Dashboard → Share → Export → Save to file) and overwrite the JSON. Then commit the change.
- **Metric additions:** When adding new metrics to `server/app/routers/metrics.py`, update this document and add new panels to the dashboard as needed.

---

_Last updated: 2026-07-08_
