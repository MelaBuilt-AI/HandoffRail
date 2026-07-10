# HandoffRail Performance Benchmark Report

**Date:** 2026-07-09 20:27 ET  
**Environment:** WSL2 Linux, Python 3.14, SQLite (aioSQLite), in-process ASGI  
**Mode:** `HR_BENCH_INPROCESS=1` (no server needed)  
**Benchmark Suite:** `handoffrail/benchmarks/`

---

## Results Summary

| Benchmark | Status | Key Metric | Result |
|-----------|--------|-----------|--------|
| Packet Throughput | ✅ PASS | req/s @ 25 conc | 89.1 req/s |
| Memory Profile | ✅ PASS | Δ @ 25 clients | +43.6 MB |
| Concurrent Clients | ❌ BLOCKED | — | REST workers don't use in-process transport |
| Webhook Latency | ❌ BLOCKED | — | Hangs during listener setup |
| Locust Load Test | ⏭️ SKIPPED | — | Requires live server |
| Unit Tests | ❌ OOM | — | Killed (SIGKILL) — in-process server + test suite too heavy |

---

## 1. Packet Throughput Benchmark ✅

**Command:** `HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_packet_throughput --concurrency 5 10 25 --duration 8`

**Lifecycle: create → claim → complete**

```
Concurr | Req/s | Total | Err% | P50     | P95      | P99       | Mean
--------|-------|-------|------|---------|----------|-----------|--------
5       | 90.0  | 720   | 0.0% | 27.0ms  | 144.4ms  | 373.3ms   | 47.4ms
10      | 95.5  | 764   | 0.0% | 30.2ms  | 442.0ms  | 1144.6ms  | 97.2ms
25      | 89.1  | 713   | 0.0% | 103.3ms | 797.1ms  | 2068.9ms  | 216.7ms
```

**Analysis:**
- ✅ Zero errors across all concurrency levels
- ⚠️ Throughput flat (~90 req/s) — does not scale with concurrency
- ⚠️ P99 latency spikes dramatically: 373ms → 2069ms at 25 workers
- 🔴 Well below target of 500 req/s @ 50 concurrency

**Bottleneck:** SQLite write contention. Each packet lifecycle involves 3 POSTs (create, claim, complete) plus FTS inserts. SQLite serializes writes, so 25 concurrent workers queue up.

---

## 2. Memory Profile ✅

**Command:** `HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_memory_profile --concurrency 5 10 25 --duration 8`

```
Clients | Baseline | Peak     | Final    | Δ        | GC Collected
--------|----------|----------|----------|----------|-------------
5       | 83.5 MB  | 106.3 MB | 106.3 MB | +22.9 MB | 5851
10      | 83.5 MB  | 123.0 MB | 123.5 MB | +40.0 MB | 4951
25      | 83.5 MB  | 142.8 MB | 127.1 MB | +43.6 MB | 7355
```

**Analysis:**
- 🔴 Memory delta exceeds target: +43.6 MB at 25 clients (target: <25 MB at 50)
- ⚠️ Final memory stays high — objects not fully released after test
- ⚠️ GC collected 5K–7K objects — significant allocation churn
- Small recovery after peak (142.8 → 127.1 MB at 25) but not full

**Bottleneck:** SQLAlchemy session caching, FTS index memory, and packet accumulation in DB. Memory grows roughly linearly with client count.

---

## 3. Concurrent Clients ❌ BLOCKED

**Command:** `HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_concurrent_clients --duration 8`

**Issue:** The REST worker (`_rest_client_worker`) always uses `aiohttp` to connect to `http://localhost:8080`, even in in-process mode. It never uses the ASGI transport created by `_setup_inprocess()`. All REST requests fail with connection errors.

**Also:** `_setup_inprocess()` was called once per scenario, hitting UNIQUE constraint on API key re-insert. Fixed with singleton caching, but the REST worker transport issue remains a structural problem.

**Required fix:** Refactor `run_scenario()` to accept and pass the in-process transport to REST workers, or have REST workers use `httpx.AsyncClient(transport=transport)` when available.

---

## 4. Webhook Latency ❌ BLOCKED

**Command:** `HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_webhook_latency --concurrency 5 10 --duration 8`

**Issue:** Hangs with no output after the header. Likely the local aiohttp webhook listener (`_run_webhook_listener`) fails to bind or the webhook registration with the in-process server silently fails. The benchmark tries to create a real TCP listener on 127.0.0.1:19999 while also running the in-process ASGI app.

**Required fix:** Debug the listener binding in the in-process context, or use a different port that doesn't conflict.

---

## Bugs Found & Fixed

| # | File | Bug | Fix |
|---|------|-----|-----|
| 1 | `benchmarks/common.py:135` | `print_table` format string used auto-numbered `{}` placeholders with `**kwargs` — mixing positional and named args is disallowed in `str.format()` | Changed to named placeholders `{key:<width}` |
| 2 | `benchmarks/benchmark_packet_throughput.py:47` | `os.environ.setdefault()` called without importing `os` | Added `import os` inside function |
| 3 | `benchmarks/benchmark_webhook_latency.py:54` | Same `os` import missing | Added `import os` inside function |
| 4 | `benchmarks/benchmark_concurrent_clients.py:74` | Same `os` import missing | Added `import os` inside function |
| 5 | `benchmarks/benchmark_memory_profile.py:171` | Same `os` import missing | Added `import os` inside function |
| 6 | All 4 `_inprocess_app/_setup_inprocess` functions | API key hash stored as `f"hash_{plain_key}"` instead of actual SHA256 hash from `generate_api_key()` | Use `hashed_key` return value from `generate_api_key()` |
| 7 | `benchmarks/benchmark_concurrent_clients.py:_setup_inprocess` | Called once per scenario, re-inserting same API key | Added module-level singleton cache |

---

## Recommendations

1. **Switch to PostgreSQL for benchmarks.** SQLite serializes writes — throughput will never scale. Running `docker compose up -d` with the prod compose file uses PostgreSQL. Expect 5-10x throughput improvement.

2. **Fix concurrent clients in-process mode.** The REST worker needs to accept and use the ASGI transport instead of always hitting `localhost:8080`.

3. **Reduce benchmark duration for smoke tests.** 8s per concurrency level is good for quick runs. Consider adding `--smoke` flag for 3s/level.

4. **Add DB cleanup between benchmarks.** Each benchmark should either use `:memory:` SQLite or clean up `handoffrail.db` between runs. Currently they share state.

5. **Fix webhook listener.** The local listener appears to hang during startup. Consider using a simpler `asyncio.Queue` callback instead of a real TCP listener for in-process mode.

6. **Memory optimization.** The +43 MB delta at 25 clients is high. Consider:
   - Using connection pooling with smaller pool sizes
   - Adding periodic GC in the benchmark loop
   - Limiting FTS index size in benchmark mode

7. **Run against Docker.** The quickest path to meaningful results:
   ```bash
   docker compose up -d
   python -m benchmarks.benchmark_packet_throughput --host localhost --port 8080
   locust -f loadtests/locustfile.py --host=http://localhost:8080 --headless -u 50 -r 10 --run-time 60s
   ```

---

## Files Changed

- `benchmarks/common.py` — Fixed `print_table` format string
- `benchmarks/benchmark_packet_throughput.py` — Added `import os`, fixed API key hash
- `benchmarks/benchmark_webhook_latency.py` — Added `import os`, fixed API key hash
- `benchmarks/benchmark_concurrent_clients.py` — Added `import os`, fixed API key hash, singleton cache
- `benchmarks/benchmark_memory_profile.py` — Added `import os`, fixed API key hash
- `benchmarks/BENCHMARK-REPORT-2026-07-09.md` — This report
