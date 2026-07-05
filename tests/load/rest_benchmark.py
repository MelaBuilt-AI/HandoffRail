"""HandoffRail REST API benchmark — throughput and latency measurement.

Benchmarks POST /api/v1/packets, GET /api/v1/packets, and GET /api/v1/stats
endpoints under various concurrencies.

Measures:
- Requests per second (throughput)
- p50/p95/p99 latency
- Error rate
- Connection overhead

Usage:
    python -m tests.load.rest_benchmark [--host localhost] [--port 8080]
        [--api-key <key>] [--concurrency 10 25 50]
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

# ── Test configuration ─────────────────────────────────────────────────────────

DEFAULT_CONCURRENCIES = [5, 10, 25, 50]
DEFAULT_DURATION = 10  # seconds per benchmark round
WARMUP_REQUESTS = 5     # warmup requests before measurement


@dataclass
class EndpointMetrics:
    """Metrics for a single endpoint benchmark."""

    endpoint: str
    method: str
    concurrency: int
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    latencies: list[float] = field(default_factory=list)
    total_bytes: int = 0
    duration: float = 0.0

    @property
    def requests_per_second(self) -> float:
        return self.total_requests / self.duration if self.duration > 0 else 0.0

    @property
    def error_rate(self) -> float:
        return self.failed / self.total_requests * 100 if self.total_requests > 0 else 0.0

    def latency_stats(self) -> dict[str, float]:
        if not self.latencies:
            return {"min": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0, "mean": 0, "samples": 0}
        sorted_lat = sorted(self.latencies)
        return {
            "min": min(self.latencies),
            "p50": statistics.median(sorted_lat),
            "p95": sorted_lat[int(len(sorted_lat) * 0.95)],
            "p99": sorted_lat[int(len(sorted_lat) * 0.99)],
            "max": max(self.latencies),
            "mean": statistics.mean(self.latencies),
            "stdev": statistics.stdev(self.latencies) if len(self.latencies) > 1 else 0.0,
            "samples": len(self.latencies),
        }


@dataclass
class BenchmarkResult:
    """Complete benchmark result."""

    target: str
    results: list[EndpointMetrics]
    total_duration: float


# ── Test data ──────────────────────────────────────────────────────────────────

SAMPLE_PACKET = {
    "metadata": {
        "source_agent": {"id": "bench-source", "name": "Bench Source", "framework": "test"},
        "target_agent": {"id": "bench-target", "name": "Bench Target", "framework": "test"},
        "priority": "normal",
        "tags": ["benchmark"],
    },
    "context": {
        "conversation_state": [{"role": "user", "content": "Benchmark test message"}],
        "summary": "Benchmark test packet",
    },
    "decisions": [
        {"id": "dec-1", "decision": "proceed", "rationale": "Benchmark", "timestamp": time.time()},
    ],
    "actions": {"pending": [], "completed": [], "failed": []},
    "dependencies": [],
}


async def _warmup(
    session: aiohttp.ClientSession, base_url: str, api_key: str, endpoints: list[tuple[str, str]],
) -> None:
    """Send warmup requests to avoid cold-start skew."""
    for method, path in endpoints:
        for _ in range(WARMUP_REQUESTS):
            try:
                if method == "GET":
                    await session.get(f"{base_url}{path}")
                else:
                    await session.post(f"{base_url}{path}", json=SAMPLE_PACKET)
            except Exception:
                pass


async def _benchmark_worker(
    session: aiohttp.ClientSession,
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    worker_id: int,
    metrics: EndpointMetrics,
    stop_event: asyncio.Event,
    post_body: dict[str, Any] | None = None,
) -> None:
    """Continuously hit an endpoint until stop_event is set."""
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    while not stop_event.is_set():
        try:
            start = time.perf_counter()

            if method == "GET":
                resp = await session.get(f"{base_url}{path}", headers=headers)
            else:
                resp = await session.post(f"{base_url}{path}", json=post_body or {}, headers=headers)

            elapsed = time.perf_counter() - start
            body = await resp.read()

            metrics.total_requests += 1
            metrics.total_bytes += len(body)
            metrics.latencies.append(elapsed)

            if resp.ok:
                metrics.successful += 1
            else:
                metrics.failed += 1

        except Exception:
            metrics.total_requests += 1
            metrics.failed += 1


async def benchmark_endpoint(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    concurrency: int,
    duration: float = DEFAULT_DURATION,
    post_body: dict[str, Any] | None = None,
) -> EndpointMetrics:
    """Benchmark a single endpoint at a given concurrency level."""
    metrics = EndpointMetrics(
        endpoint=path,
        method=method,
        concurrency=concurrency,
    )

    async with aiohttp.ClientSession() as session:
        stop_event = asyncio.Event()
        workers = [
            _benchmark_worker(session, base_url, api_key, method, path, i, metrics, stop_event, post_body)
            for i in range(concurrency)
        ]

        # Run workers
        tasks = [asyncio.create_task(w) for w in workers]

        await asyncio.sleep(duration)
        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    metrics.duration = duration
    return metrics


async def run_benchmark(
    host: str = "localhost",
    port: int = 8080,
    api_key: str | None = None,
    concurrencies: list[int] | None = None,
    duration: float = DEFAULT_DURATION,
) -> BenchmarkResult:
    """Run full REST API benchmark across all endpoints and concurrency levels."""
    base_url = f"http://{host}:{port}"
    if concurrencies is None:
        concurrencies = DEFAULT_CONCURRENCIES

    # Endpoints to benchmark
    endpoints = [
        ("GET", "/api/v1/stats"),
        ("GET", "/api/v1/packets?limit=10"),
        ("POST", "/api/v1/packets"),
    ]

    # Resolve API key
    if not api_key:
        async with aiohttp.ClientSession() as session:
            try:
                resp = await session.post(f"{base_url}/api/v1/keys", json={"name": "bench-key"})
                if resp.ok:
                    data = await resp.json()
                    api_key = data.get("key", "")
            except Exception:
                pass

    if not api_key:
        api_key = "test-api-key"

    all_results: list[EndpointMetrics] = []
    overall_start = time.monotonic()

    # Warmup
    print("  Warming up...")
    async with aiohttp.ClientSession() as session:
        await _warmup(session, base_url, api_key, endpoints)
    print("  Warmup complete.\n")

    for method, path in endpoints:
        for concurrency in concurrencies:
            print(f"  Benchmarking {method} {path} @ concurrency={concurrency}...")

            body = SAMPLE_PACKET if method == "POST" else None
            metrics = await benchmark_endpoint(
                base_url=base_url,
                api_key=api_key,
                method=method,
                path=path,
                concurrency=concurrency,
                duration=duration,
                post_body=body,
            )
            all_results.append(metrics)

            # Brief cooldown
            await asyncio.sleep(1)

    overall_end = time.monotonic()

    return BenchmarkResult(
        target=f"http://{host}:{port}",
        results=all_results,
        total_duration=overall_end - overall_start,
    )


def _print_benchmark(result: BenchmarkResult) -> None:
    """Pretty-print benchmark results."""
    print(f"\n{'#'*70}")
    print("  HandoffRail REST API Benchmark")
    print(f"  Target: {result.target}")
    print(f"  Total Duration: {result.total_duration:.1f}s")
    print(f"{'#'*70}")

    # Group by endpoint
    from collections import defaultdict
    by_endpoint: dict[str, list[EndpointMetrics]] = defaultdict(list)
    for r in result.results:
        key = f"{r.method} {r.endpoint}"
        by_endpoint[key].append(r)

    for endpoint_key, metrics_list in by_endpoint.items():
        metrics_list.sort(key=lambda m: m.concurrency)

        print(f"\n{'─'*70}")
        print(f"  {endpoint_key}")
        print(f"{'─'*70}")
        headers = (
            f"  {'Concurr':>8} | {'RPS':>10} | {'Err%':>8}"
            f" | {'P50':>8} | {'P95':>8} | {'P99':>8}"
            f" | {'Mean':>8} | {'Samples':>8}"
        )
        print(headers)
        print(f"  {'-'*8}-+-{'-'*10}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}")

        for m in metrics_list:
            ls = m.latency_stats()
            print(f"  {m.concurrency:>8} | {m.requests_per_second:>10.1f} | {m.error_rate:>7.1f}% | "
                  f"{ls['p50']*1000:>7.1f}ms | {ls['p95']*1000:>7.1f}ms | {ls['p99']*1000:>7.1f}ms | "
                  f"{ls['mean']*1000:>7.1f}ms | {ls['samples']:>8}")

    # Summary
    print(f"\n{'─'*70}")
    print("  SUMMARY")
    print(f"{'─'*70}")
    all_rps = [r.requests_per_second for r in result.results]
    if all_rps:
        print(f"  Total benchmark time: {result.total_duration:.1f}s")
        print(f"  Best RPS: {max(all_rps):.1f}")
        print(f"  Worst RPS: {min(all_rps):.1f}")
        print(f"  Endpoints tested: {len(by_endpoint)}")
        print(f"  Benchmark rounds: {len(result.results)}")
    print(f"{'#'*70}\n")


async def main():
    parser = argparse.ArgumentParser(description="HandoffRail REST API Benchmark")
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    parser.add_argument("--api-key", default=None, help="API key")
    parser.add_argument("--concurrency", type=int, nargs="+", default=DEFAULT_CONCURRENCIES, help="Concurrency levels")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION, help="Test duration per round (seconds)")
    args = parser.parse_args()

    print("🧪 HandoffRail REST API Benchmark")
    print(f"   Target: http://{args.host}:{args.port}")
    print(f"   Concurrency levels: {args.concurrency}")
    print(f"   Duration per round: {args.duration}s")
    print()

    result = await run_benchmark(
        host=args.host,
        port=args.port,
        api_key=args.api_key,
        concurrencies=args.concurrency,
        duration=args.duration,
    )

    _print_benchmark(result)


if __name__ == "__main__":
    asyncio.run(main())
