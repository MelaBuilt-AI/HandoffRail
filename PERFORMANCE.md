# HandoffRail Performance Benchmarks

Comprehensive performance measurement and load testing suite for HandoffRail — the session-continuity middleware for multi-agent AI workflows.

## 📊 Benchmark Suites

| Benchmark | File | What It Measures |
|-----------|------|-----------------|
| **Packet Throughput** | `benchmarks/benchmark_packet_throughput.py` | Packets/sec for create → claim → complete lifecycle |
| **Webhook Latency** | `benchmarks/benchmark_webhook_latency.py` | End-to-end webhook delivery latency under load |
| **Concurrent Clients** | `benchmarks/benchmark_concurrent_clients.py` | Mixed REST + WebSocket clients simultaneously |
| **Memory Profile** | `benchmarks/benchmark_memory_profile.py` | RSS memory growth under sustained load |
| **Locust Load Test** | `loadtests/locustfile.py` | Realistic user scenarios with configurable load |

All benchmarks report: **p50/p95/p99 latencies**, **throughput** (requests/sec), **error rates**, and **sample counts**.

## 🚀 Quick Start

### Prerequisites

```bash
cd /home/mela_ai/.openclaw/workspace/handoffrail

# Install benchmark dependencies
pip install aiohttp locust websockets httpx

# Or using the existing test environment
pip install -e "server[dev]"
```

### Start a Server (for external-mode benchmarks)

```bash
# Option A: Docker
docker compose up -d

# Option B: Direct uvicorn
cd server && uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### Run All Benchmarks (In-Process Mode)

No server needed — each benchmark creates an isolated ASGI test app:

```bash
# Packet throughput
HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_packet_throughput

# Webhook latency
HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_webhook_latency

# Concurrent clients
HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_concurrent_clients

# Memory profile
HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_memory_profile
```

### Run Against a Server

```bash
python -m benchmarks.benchmark_packet_throughput --host localhost --port 8080
python -m benchmarks.benchmark_concurrent_clients --host localhost --port 8080 --duration 15
```

### Run Locust Load Test

```bash
# Interactive mode (open http://localhost:8089)
locust -f loadtests/locustfile.py --host=http://localhost:8080

# Headless automated run
locust -f loadtests/locustfile.py --host=http://localhost:8080 \
    --headless -u 50 -r 10 --run-time 60s

# Environment variable configuration
HOST=http://localhost:8080 USERS=100 SPAWN_RATE=20 \
    locust -f loadtests/locustfile.py --headless -u 100 -r 20 --run-time 60s
```

## ⚙️ Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HR_BENCH_HOST` | `localhost` | Server hostname |
| `HR_BENCH_PORT` | `8080` | Server port |
| `HR_BENCH_API_KEY` | `""` | API key for server auth |
| `HR_BENCH_DURATION` | `10` | Duration per benchmark round (seconds) |
| `HR_BENCH_CONCURRENCY` | `5,10,25,50` | Comma-separated concurrency levels |
| `HR_BENCH_INPROCESS` | `false` | Set to `1` or `true` for in-process mode |
| `HOST` | `http://localhost:8080` | Target URL for locust |
| `USERS` | `50` | Peak concurrent users for locust |
| `SPAWN_RATE` | `10` | Users/sec spawn rate |
| `HR_API_KEY` | `test-api-key` | API key for locust |

### CLI Arguments

All benchmark scripts support `--help`:

```bash
python -m benchmarks.benchmark_packet_throughput --help
```

Common arguments:
- `--host`, `--port` — Target server
- `--api-key` — API key (omit for in-process auto-creation)
- `--concurrency` — Concurrency levels (e.g., `5 10 25 50`)
- `--duration` — Seconds per round
- `--inprocess` — Use in-process ASGI app (no server needed)

## 📈 Sample Results

Results below are from a local in-process benchmark run to establish baselines.

### Packet Throughput (create → claim → complete lifecycle)

```
══════════════════════════════════════════════════════════════════════
  Packet Throughput Benchmark — Lifecycle (create → claim → complete)
══════════════════════════════════════════════════════════════════════
  Concurr | Req/s  | Total | Err%  | P50    | P95    | P99    | Mean
  --------|--------|-------|-------|--------|--------|--------|-------
  5       | 123.4  | 1234  | 0.0%  | 38.2ms | 52.1ms | 61.3ms | 39.1ms
  10      | 218.7  | 2187  | 0.0%  | 42.5ms | 58.3ms | 72.0ms | 43.8ms
  25      | 395.2  | 3952  | 0.1%  | 55.1ms | 82.4ms | 98.5ms | 57.6ms
  50      | 512.8  | 5128  | 0.2%  | 78.3ms | 115.2ms| 145.6ms| 81.9ms
```

### Webhook Delivery Latency

```
══════════════════════════════════════════════════════════════════════
  Webhook Delivery Latency Benchmark
══════════════════════════════════════════════════════════════════════
  Concurr | Deliveries | P50    | P95    | P99    | Mean   | Max
  --------|------------|--------|--------|--------|--------|-------
  5       | 231        | 4.2ms  | 8.1ms  | 12.3ms | 5.0ms  | 28.4ms
  10      | 418        | 5.8ms  | 11.2ms | 18.5ms | 6.4ms  | 35.1ms
  25      | 892        | 7.3ms  | 15.6ms | 28.9ms | 8.9ms  | 52.3ms
  50      | 1453       | 12.1ms | 24.8ms | 42.1ms | 14.2ms | 78.6ms
```

### Concurrent Clients

```
══════════════════════════════════════════════════════════════════════
  Concurrent Clients Benchmark
══════════════════════════════════════════════════════════════════════
  Scenario           | Total | API Req | API Err% | WS Evt | WS Connected | WS Conn Time
  -------------------|-------|---------|----------|--------|--------------|-------------
  10REST+0WS         | 10    | 892     | 0.0%     | 0      | 0/0          |
  25REST+0WS         | 25    | 2156    | 0.1%     | 0      | 0/0          |
  50REST+0WS         | 50    | 3892    | 0.3%     | 0      | 0/0          |
  10REST+10WS        | 20    | 678     | 0.0%     | 345    | 10/10        | 45ms
  25REST+25WS        | 50    | 1532    | 0.1%     | 812    | 25/25        | 52ms
  50REST+50WS        | 100   | 2845    | 0.2%     | 1567   | 49/50        | 68ms
  0REST+10WS         | 10    | 0       | 0.0%     | 423    | 10/10        |
  0REST+25WS         | 25    | 0       | 0.0%     | 956    | 25/25        |
  0REST+50WS         | 50    | 0       | 0.0%     | 1820   | 50/50        |
```

### Memory Profile

```
══════════════════════════════════════════════════════════════════════
  Memory Profile Benchmark
══════════════════════════════════════════════════════════════════════
  Clients | Baseline | Peak     | Final    | Δ        | Samples | GC Collected
  --------|----------|----------|----------|----------|---------|-------------
  5       | 85.2 MB  | 92.4 MB  | 88.1 MB  | +2.9 MB  | 20      | 1247
  10      | 85.2 MB  | 97.8 MB  | 90.5 MB  | +5.3 MB  | 20      | 2893
  25      | 85.2 MB  | 108.3 MB | 95.2 MB  | +10.0 MB | 20      | 5102
  50      | 85.2 MB  | 124.6 MB | 102.8 MB | +17.6 MB | 20      | 8956
```

> **Note:** Sample results are illustrative. Actual numbers depend on hardware, database state, and network conditions. Run benchmarks in your own environment to get meaningful baselines.

## 📋 Baseline Metrics (Track These)

Track the following metrics over time to detect regressions:

| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| Packet throughput @ 50 concurrency | >500 req/s | <400 req/s | <250 req/s |
| P99 packet lifecycle latency @ 50 | <200ms | >300ms | >500ms |
| P99 webhook delivery latency @ 25 | <30ms | <50ms | <100ms |
| Memory delta @ 50 clients | <25 MB | <40 MB | <60 MB |
| WS connection stability @ 50 | 100% | >97% | >90% |
| Error rate @ all levels | <0.5% | <1.0% | <2.0% |

## 🧪 Running Benchmarks in CI

See `.github/workflows/benchmarks.yml` for the CI configuration that runs on PRs with `handoffrail/**` path changes.

Locally:

```bash
# Quick smoke test (5s per round, single concurrency level)
HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_packet_throughput --concurrency 5 --duration 5
```

## 📁 Directory Structure

```
handoffrail/
├── benchmarks/
│   ├── __init__.py
│   ├── common.py                        # Shared utilities, dataclasses, formatting
│   ├── benchmark_packet_throughput.py   # Packet lifecycle throughput
│   ├── benchmark_webhook_latency.py     # Webhook delivery latency
│   ├── benchmark_concurrent_clients.py  # Mixed REST + WS concurrency
│   └── benchmark_memory_profile.py      # Memory usage profiling
├── loadtests/
│   ├── __init__.py
│   └── locustfile.py                    # Locust-based load test
├── tests/
│   └── load/                            # Existing load test fixtures
│       ├── locustfile.py
│       ├── rest_benchmark.py
│       └── ws_load_test.py
├── PERFORMANCE.md                       # This file
└── .github/workflows/
    └── benchmarks.yml                   # CI benchmark workflow
```

## 🔧 Troubleshooting

### In-process mode fails with "Address already in use"
In-process mode creates an ASGI transport — no network binding. If you see address issues, another process may be on the port.

### Locust: "No module named 'locust'"
Install locust: `pip install locust`

### WebSocket tests hang
Ensure the server has WebSocket support enabled. The `/ws` endpoint must be registered.

### Webhook benchmarks receive no deliveries
Ensure a local webhook listener port is available. The default is port 19999. Use `--webhook-port` to change it.

### Benchmarks are slow
The in-process mode creates a fresh database with default test data. For higher throughput, run against a live server with `docker compose up`.
