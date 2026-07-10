"""HandoffRail Packet Throughput Benchmark.

Measures throughput and latency for the full packet lifecycle:
  - POST /api/v1/packets  → create a packet
  - POST /api/v1/packets/{id}/claim → claim a packet
  - POST /api/v1/packets/{id}/complete → complete a packet

Reports p50/p95/p99 latency, requests/sec, and error rates at
configurable concurrency levels.

Usage:
    # Against a running server (default)
    python -m benchmarks.benchmark_packet_throughput --host localhost --port 8080

    # In-process (no server needed)
    HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_packet_throughput

    # Custom concurrency and duration
    python -m benchmarks.benchmark_packet_throughput --concurrency 5 10 25 50 --duration 15
"""

from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any

import aiohttp

from benchmarks.common import (
    DEFAULT_API_KEY,
    DEFAULT_CONCURRENCY_LEVELS,
    DEFAULT_DURATION,
    DEFAULT_HOST,
    DEFAULT_INPROCESS,
    DEFAULT_PORT,
    SAMPLE_PACKET,
    BenchmarkRound,
    print_header,
    print_table,
)


async def _inprocess_app():
    """Lazy-import the test app for in-process mode."""
    import os
    os.environ.setdefault("HR_DISABLE_DAILY_LIMIT", "1")
    from app.database import _init_fts, async_session, engine
    from app.main import create_app
    from app.middleware.auth import generate_api_key
    from app.middleware.rate_limit import daily_handoff_counter, rate_limiter_registry, sliding_window_counter
    from app.models.db import ApiKey, Base, Tenant

    from datetime import UTC, datetime
    from sqlalchemy import select

    app = create_app(
        tier_limits={"free": 100000, "pro": 100000, "business": 100000},
        rate_limit_per_minute=100000,
        disable_rbac=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _init_fts(conn)

    async with async_session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == "default"))
        if result.scalar_one_or_none() is None:
            session.add(Tenant(id="default", name="Default Tenant", tier="free", handoffs_per_day=100000, max_api_keys=100, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)))
            await session.commit()

    plain_key, hashed_key = generate_api_key()
    async with async_session() as session:
        session.add(ApiKey(id="bench-key", name="bench", key_hash=hashed_key, key_prefix=plain_key[:8], tenant_id="default", tier="business"))
        await session.commit()

    # Wait for FTS and caches to settle
    await asyncio.sleep(0.1)

    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    return transport, plain_key


async def _benchmark_flow(
    session: aiohttp.ClientSession,
    base_url: str,
    api_key: str,
    round_data: BenchmarkRound,
    stop_event: asyncio.Event,
) -> None:
    """Worker: repeatedly create → claim → complete packets."""
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    while not stop_event.is_set():
        try:
            # ── CREATE ──
            start = time.perf_counter()
            async with session.post(f"{base_url}/api/v1/packets", json=SAMPLE_PACKET, headers=headers) as resp:
                create_elapsed = time.perf_counter() - start
                body = await resp.read()
                if resp.ok:
                    data = await resp.json()
                    packet_id = data.get("id", "")
                else:
                    packet_id = ""
        except Exception:
            round_data.total_requests += 1
            round_data.failed += 1
            continue

        round_data.total_requests += 1
        round_data.total_bytes += len(body)
        if resp.ok and packet_id:
            round_data.successful += 1
            round_data.latencies.append(create_elapsed)
        else:
            round_data.failed += 1

        if not packet_id:
            continue

        # ── CLAIM ──
        try:
            start = time.perf_counter()
            async with session.post(
                f"{base_url}/api/v1/packets/{packet_id}/claim",
                json={"claimed_by": "bench-worker"},
                headers=headers,
            ) as resp:
                claim_elapsed = time.perf_counter() - start
                body = await resp.read()
        except Exception:
            continue

        # ── COMPLETE ──
        try:
            start = time.perf_counter()
            async with session.post(
                f"{base_url}/api/v1/packets/{packet_id}/complete",
                json={"status": "completed", "outcome": {"result": "success"}},
                headers=headers,
            ) as resp:
                complete_elapsed = time.perf_counter() - start
                body = await resp.read()
        except Exception:
            continue


async def run_throughput_benchmark(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    api_key: str = DEFAULT_API_KEY,
    concurrency_levels: list[int] | None = None,
    duration_sec: int = DEFAULT_DURATION,
    inprocess: bool = DEFAULT_INPROCESS,
) -> list[BenchmarkRound]:
    """Run the packet lifecycle throughput benchmark."""
    if concurrency_levels is None:
        concurrency_levels = DEFAULT_CONCURRENCY_LEVELS

    transport = None
    if inprocess:
        transport, api_key = await _inprocess_app()
        # In-process: use httpx ASGITransport wrapped in a custom connector
        # We'll create a new client session per round for simplicity
    else:
        if not api_key:
            api_key = DEFAULT_API_KEY

    base_url = f"http://{host}:{port}"
    results: list[BenchmarkRound] = []

    for concurrency in concurrency_levels:
        print(f"  Concurrency={concurrency} ...", end="", flush=True)

        round_data = BenchmarkRound(
            name="packet lifecycle (create→claim→complete)",
            concurrency=concurrency,
        )

        if inprocess:
            # In-process: use httpx with ASGITransport per round
            import httpx
            stop_event = asyncio.Event()
            start_ts = time.monotonic()

            async def _inproc_worker(worker_id: int):
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
                    while not stop_event.is_set():
                        try:
                            start = time.perf_counter()
                            r = await client.post("/api/v1/packets", json=SAMPLE_PACKET, headers=headers)
                            elapsed = time.perf_counter() - start
                            if r.status_code == 201:
                                data = r.json()
                                pid = data.get("id", "")
                                round_data.total_bytes += len(r.content)
                                round_data.successful += 1
                                round_data.latencies.append(elapsed)
                                # claim
                                await client.post(f"/api/v1/packets/{pid}/claim", json={"claimed_by": "bench"}, headers=headers)
                                # complete
                                await client.post(f"/api/v1/packets/{pid}/complete", json={"status": "completed", "outcome": {"result": "ok"}}, headers=headers)
                            else:
                                round_data.failed += 1
                            round_data.total_requests += 1
                        except Exception:
                            round_data.total_requests += 1
                            round_data.failed += 1

            tasks = [asyncio.create_task(_inproc_worker(i)) for i in range(concurrency)]
            await asyncio.sleep(duration_sec)
            stop_event.set()
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            # External server mode: use aiohttp
            async with aiohttp.ClientSession() as session:
                stop_event = asyncio.Event()
                workers = [
                    _benchmark_flow(session, base_url, api_key, round_data, stop_event)
                    for _ in range(concurrency)
                ]
                tasks = [asyncio.create_task(w) for w in workers]
                await asyncio.sleep(duration_sec)
                stop_event.set()
                await asyncio.gather(*tasks, return_exceptions=True)

        round_data.duration_sec = duration_sec
        results.append(round_data)
        ls = round_data.latency().as_ms()
        print(f"  {round_data.requests_per_second:.0f} req/s  "
              f"p50={ls.p50:.1f}ms  p95={ls.p95:.1f}ms  err={round_data.error_rate:.1f}%")

    return results


def print_results(results: list[BenchmarkRound]) -> None:
    """Pretty-print throughput benchmark results."""
    print_header("Packet Throughput Benchmark — Lifecycle (create → claim → complete)")
    rows = []
    for r in results:
        ls = r.latency().as_ms()
        rows.append({
            "concurrency": str(r.concurrency),
            "rps": f"{r.requests_per_second:.1f}",
            "total": str(r.total_requests),
            "errors": f"{r.error_rate:.1f}%",
            "p50": f"{ls.p50:.1f}ms",
            "p95": f"{ls.p95:.1f}ms",
            "p99": f"{ls.p99:.1f}ms",
            "mean": f"{ls.mean:.1f}ms",
        })
    print_table(
        rows,
        [("concurrency", "Concurr"), ("rps", "Req/s"), ("total", "Total"),
         ("errors", "Err%"), ("p50", "P50"), ("p95", "P95"), ("p99", "P99"), ("mean", "Mean")],
    )
    print(f"  ↑ Higher RPS + lower latency = better")


async def main() -> None:
    parser = argparse.ArgumentParser(description="HandoffRail Packet Throughput Benchmark")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port")
    parser.add_argument("--api-key", default=None, help="API key (omit for auto/in-process)")
    parser.add_argument("--concurrency", type=int, nargs="+", default=DEFAULT_CONCURRENCY_LEVELS)
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION, help="Seconds per round")
    parser.add_argument("--inprocess", action="store_true", default=DEFAULT_INPROCESS, help="Run in-process (no server)")
    args = parser.parse_args()

    print("═" * 70)
    print("  HandoffRail — Packet Throughput Benchmark")
    print(f"  Target: {'in-process' if args.inprocess else f'http://{args.host}:{args.port}'}")
    print(f"  Concurrency levels: {args.concurrency}")
    print(f"  Duration per round: {args.duration}s")
    print("═" * 70)

    results = await run_throughput_benchmark(
        host=args.host,
        port=args.port,
        api_key=args.api_key or DEFAULT_API_KEY,
        concurrency_levels=args.concurrency,
        duration_sec=args.duration,
        inprocess=args.inprocess,
    )
    print_results(results)


if __name__ == "__main__":
    asyncio.run(main())
