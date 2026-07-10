"""HandoffRail Memory Profile Benchmark.

Measures memory usage under sustained load by:
  1. Recording baseline memory (process RSS)
  2. Ramping up concurrent clients
  3. Sampling memory at regular intervals
  4. Recording peak, final, and delta memory

Reports:
  - Baseline memory (idle)
  - Memory during load at each concurrency level
  - Peak memory usage
  - Memory growth per client
  - GC pressure indicators

Usage:
    # Against running server (default)
    python -m benchmarks.benchmark_memory_profile --host localhost --port 8080

    # In-process (more accurate memory tracking)
    HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_memory_profile
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any

from benchmarks.common import (
    DEFAULT_API_KEY,
    DEFAULT_CONCURRENCY_LEVELS,
    DEFAULT_DURATION,
    DEFAULT_HOST,
    DEFAULT_INPROCESS,
    DEFAULT_PORT,
    SAMPLE_PACKET,
    print_header,
    print_table,
)


@dataclass
class MemorySample:
    """A single memory measurement."""

    timestamp: float = 0.0
    rss_mb: float = 0.0
    client_count: int = 0


@dataclass
class MemoryProfileResult:
    """Memory profile for a concurrency level."""

    concurrency: int
    baseline_rss_mb: float = 0.0
    peak_rss_mb: float = 0.0
    final_rss_mb: float = 0.0
    delta_mb: float = 0.0
    samples: list[MemorySample] = field(default_factory=list)
    gc_collections: int = 0
    gc_collected: int = 0


def _get_process_rss_mb() -> float:
    """Get current RSS memory in MB for this process."""
    try:
        # Linux /proc/self/status
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except (FileNotFoundError, IOError, IndexError, ValueError):
        pass
    try:
        # Fallback: /proc/self/statm (pages)
        with open("/proc/self/statm") as f:
            pages = int(f.read().split()[1])
            page_size = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
            return pages * page_size / (1024 * 1024)
    except (FileNotFoundError, IOError, IndexError, ValueError):
        pass
    return 0.0


def _collect_garbage() -> dict[str, int]:
    """Run garbage collection and return stats."""
    import gc
    old_flags = gc.get_debug()
    gc.set_debug(0)
    collected = gc.collect()
    gc.set_debug(old_flags)
    counts = gc.get_count()
    return {"collected": collected, "counts": list(counts)}


async def _load_worker(
    base_url: str,
    api_key: str,
    stop_event: asyncio.Event,
    worker_id: int,
    in_transport: Any = None,
) -> int:
    """Worker that creates packets to generate memory pressure."""
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    if in_transport:
        import httpx
        async with httpx.AsyncClient(transport=in_transport, base_url="http://test") as client:
            ops = 0
            while not stop_event.is_set():
                try:
                    r = await client.post("/api/v1/packets", json=SAMPLE_PACKET, headers=headers)
                    if r.status_code == 201:
                        data = r.json()
                        pid = data.get("id", "")
                        # Read some
                        await client.get(f"/api/v1/packets?limit=10", headers=headers)
                        if pid:
                            try:
                                await client.get(f"/api/v1/packets/{pid}", headers=headers)
                            except Exception:
                                pass
                    ops += 1
                except Exception:
                    pass
            return ops
    else:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            ops = 0
            while not stop_event.is_set():
                try:
                    async with session.post(f"{base_url}/api/v1/packets", json=SAMPLE_PACKET, headers=headers) as resp:
                        if resp.ok:
                            data = await resp.json()
                            pid = data.get("id", "")
                    ops += 1
                except Exception:
                    pass
            return ops


async def run_memory_profile(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    api_key: str = DEFAULT_API_KEY,
    concurrency_levels: list[int] | None = None,
    duration_sec: int = DEFAULT_DURATION,
    inprocess: bool = DEFAULT_INPROCESS,
) -> list[MemoryProfileResult]:
    """Run memory profiling at increasing concurrency levels."""
    if concurrency_levels is None:
        concurrency_levels = DEFAULT_CONCURRENCY_LEVELS

    transport = None
    if inprocess:
        from app.database import _init_fts, async_session, engine
        from app.main import create_app
        from app.middleware.auth import generate_api_key as gen_key
        from app.middleware.rate_limit import daily_handoff_counter, rate_limiter_registry, sliding_window_counter
        from app.models.db import ApiKey, Base, Tenant
        from datetime import UTC, datetime
        from sqlalchemy import select
        import httpx

        import os
        os.environ.setdefault("HR_DISABLE_DAILY_LIMIT", "1")
        app = create_app(tier_limits={"free": 100000, "pro": 100000, "business": 100000}, rate_limit_per_minute=100000, disable_rbac=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _init_fts(conn)
        async with async_session() as session:
            result = await session.execute(select(Tenant).where(Tenant.id == "default"))
            if result.scalar_one_or_none() is None:
                session.add(Tenant(id="default", name="Default Tenant", tier="free", handoffs_per_day=100000, max_api_keys=100, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)))
                await session.commit()
        plain_key, hashed_key = gen_key()
        async with async_session() as session:
            session.add(ApiKey(id="bench-mem-key", name="bench-mem", key_hash=hashed_key, key_prefix=plain_key[:8], tenant_id="default", tier="business"))
            await session.commit()
        await asyncio.sleep(0.1)
        transport = httpx.ASGITransport(app=app)
        api_key = plain_key
        base_url_effective = ""
    else:
        base_url_effective = f"http://{host}:{port}"
        if not api_key:
            api_key = DEFAULT_API_KEY

    results: list[MemoryProfileResult] = []

    # Baseline memory
    _collect_garbage()
    await asyncio.sleep(0.5)
    baseline_rss = _get_process_rss_mb()
    print(f"  Baseline RSS: {baseline_rss:.1f} MB")

    for concurrency in concurrency_levels:
        print(f"  Concurrency={concurrency} ...", end="", flush=True)

        profile = MemoryProfileResult(
            concurrency=concurrency,
            baseline_rss_mb=baseline_rss,
        )

        stop_event = asyncio.Event()
        workers = [
            _load_worker(base_url_effective, api_key, stop_event, i, in_transport=transport)
            for i in range(concurrency)
        ]
        tasks = [asyncio.create_task(w) for w in workers]

        # Memory sampling loop
        sample_task = asyncio.create_task(_memory_sampler(profile, concurrency, stop_event))

        await asyncio.sleep(duration_sec)
        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)

        # Wait for sample loop and get final measurements
        try:
            await sample_task
        except asyncio.CancelledError:
            pass

        # Final GC and measurement
        gc_stats = _collect_garbage()
        profile.gc_collections += gc_stats["collected"]
        await asyncio.sleep(0.2)
        final_rss = _get_process_rss_mb()

        profile.final_rss_mb = final_rss
        profile.peak_rss_mb = max((s.rss_mb for s in profile.samples), default=0)
        profile.delta_mb = final_rss - baseline_rss

        results.append(profile)

        print(f"  base={baseline_rss:.1f} peak={profile.peak_rss_mb:.1f} "
              f"final={final_rss:.1f} delta={profile.delta_mb:+.1f} MB "
              f"gc_collected={gc_stats['collected']}")

        # Brief cooldown
        await asyncio.sleep(1)

    return results


async def _memory_sampler(
    profile: MemoryProfileResult,
    client_count: int,
    stop_event: asyncio.Event,
) -> None:
    """Sample memory at regular intervals during the load test."""
    while not stop_event.is_set():
        sample = MemorySample(
            timestamp=time.time(),
            rss_mb=_get_process_rss_mb(),
            client_count=client_count,
        )
        profile.samples.append(sample)
        await asyncio.sleep(0.5)


def print_results(results: list[MemoryProfileResult]) -> None:
    """Pretty-print memory profile results."""
    print_header("Memory Profile Benchmark")
    rows = []
    for r in results:
        rows.append({
            "concurrency": str(r.concurrency),
            "baseline": f"{r.baseline_rss_mb:.1f} MB",
            "peak": f"{r.peak_rss_mb:.1f} MB",
            "final": f"{r.final_rss_mb:.1f} MB",
            "delta": f"{r.delta_mb:+.1f} MB",
            "samples": str(len(r.samples)),
            "gc": str(r.gc_collections),
        })
    print_table(
        rows,
        [("concurrency", "Clients"), ("baseline", "Baseline"), ("peak", "Peak"),
         ("final", "Final"), ("delta", "Δ"), ("samples", "Samples"), ("gc", "GC Collected")],
    )
    print(f"  ↑ Lower delta = better memory efficiency")


async def main() -> None:
    parser = argparse.ArgumentParser(description="HandoffRail Memory Profile Benchmark")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--concurrency", type=int, nargs="+", default=DEFAULT_CONCURRENCY_LEVELS)
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION)
    parser.add_argument("--inprocess", action="store_true", default=DEFAULT_INPROCESS)
    args = parser.parse_args()

    print("═" * 70)
    print("  HandoffRail — Memory Profile Benchmark")
    print(f"  Target: {'in-process' if args.inprocess else f'http://{args.host}:{args.port}'}")
    print(f"  Concurrency levels: {args.concurrency}")
    print(f"  Duration per level: {args.duration}s")
    print("═" * 70)

    results = await run_memory_profile(
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
