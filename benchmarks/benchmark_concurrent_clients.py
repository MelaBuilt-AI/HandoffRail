"""HandoffRail Concurrent Clients Benchmark.

Measures performance under multiple simultaneous API and WebSocket clients.
Tests the server's ability to handle concurrent connections across both
protocols simultaneously.

Scenarios:
  - N concurrent REST API clients creating/querying packets
  - M concurrent WebSocket connections receiving events
  - Mixed: both protocols simultaneously

Reports connection success rate, message throughput, error rates,
and per-client latency distributions.

Usage:
    # Against running server (default)
    python -m benchmarks.benchmark_concurrent_clients --host localhost --port 8080

    # In-process mode
    HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_concurrent_clients
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from benchmarks.common import (
    DEFAULT_API_KEY,
    DEFAULT_DURATION,
    DEFAULT_HOST,
    DEFAULT_INPROCESS,
    DEFAULT_PORT,
    SAMPLE_PACKET,
    BenchmarkRound,
    LatencyStats,
    print_header,
    print_table,
)

# Default concurrency matrix
DEFAULT_API_CLIENTS = [10, 25, 50]
DEFAULT_WS_CLIENTS = [10, 25, 50]


@dataclass
class ClientMetrics:
    """Per-client metrics."""

    client_id: int = 0
    protocol: str = "rest"
    requests_made: int = 0
    errors: int = 0
    connected: bool = False
    connect_time: float = 0.0
    total_bytes: int = 0

    # WS-specific
    events_received: int = 0
    disconnected: bool = False


_inprocess_cache: tuple | None = None

async def _setup_inprocess():
    """Set up the in-process app environment. Cached after first call."""
    global _inprocess_cache
    if _inprocess_cache is not None:
        return _inprocess_cache
    import os
    os.environ.setdefault("HR_DISABLE_DAILY_LIMIT", "1")
    import httpx
    from app.database import _init_fts, async_session, engine
    from app.main import create_app
    from app.middleware.auth import generate_api_key as gen_key
    from app.middleware.rate_limit import daily_handoff_counter, rate_limiter_registry, sliding_window_counter
    from app.models.db import ApiKey, Base, Tenant
    from datetime import UTC, datetime
    from sqlalchemy import select

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
        session.add(ApiKey(id="bench-cc-key", name="bench-cc", key_hash=hashed_key, key_prefix=plain_key[:8], tenant_id="default", tier="business"))
        await session.commit()
    await asyncio.sleep(0.1)
    _inprocess_cache = (httpx.ASGITransport(app=app), plain_key)
    return _inprocess_cache


async def _rest_client_worker(
    base_url: str,
    api_key: str,
    metrics: ClientMetrics,
    stop_event: asyncio.Event,
    session: aiohttp.ClientSession,
) -> None:
    """REST client: mix of reads and writes."""
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    ops = ["create", "list", "stats", "create", "list"]

    while not stop_event.is_set():
        try:
            op = ops[metrics.requests_made % len(ops)]
            if op == "create":
                async with session.post(f"{base_url}/api/v1/packets", json=SAMPLE_PACKET, headers=headers) as resp:
                    await resp.read()
            elif op == "list":
                async with session.get(f"{base_url}/api/v1/packets?limit=10", headers=headers) as resp:
                    await resp.read()
            elif op == "stats":
                async with session.get(f"{base_url}/api/v1/stats", headers=headers) as resp:
                    await resp.read()
            metrics.requests_made += 1
            metrics.connected = True
        except Exception:
            metrics.errors += 1


async def _ws_client_worker(
    ws_url: str,
    api_key: str,
    metrics: ClientMetrics,
    stop_event: asyncio.Event,
) -> None:
    """WebSocket client: connect, subscribe, receive events."""
    try:
        import websockets
        uri = f"{ws_url}?api_key={api_key}"
        connect_start = time.monotonic()

        async with websockets.connect(uri, timeout=10, max_size=2 ** 20) as ws:
            metrics.connect_time = time.monotonic() - connect_start
            metrics.connected = True

            # Subscribe to channels
            await ws.send(json.dumps({"action": "subscribe", "channel": "status:created"}))
            await ws.send(json.dumps({"action": "subscribe", "channel": "status:completed"}))

            while not stop_event.is_set():
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=35)
                    metrics.events_received += 1
                    if isinstance(msg, bytes):
                        metrics.total_bytes += len(msg)
                    else:
                        metrics.total_bytes += len(msg.encode())
                except TimeoutError:
                    metrics.errors += 1
                    break
                except Exception:
                    metrics.disconnected = True
                    break
    except Exception:
        metrics.errors += 1


async def run_scenario(
    api_clients: int,
    ws_clients: int,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    api_key: str = DEFAULT_API_KEY,
    duration_sec: int = DEFAULT_DURATION,
    inprocess: bool = DEFAULT_INPROCESS,
) -> dict[str, Any]:
    """Run a mixed-concurrency scenario."""
    base_url = f"http://{host}:{port}"
    ws_url = f"ws://{host}:{port}/ws"

    transport = None
    if inprocess:
        transport, api_key = await _setup_inprocess()

    # Pre-create some packets so WS clients have events to receive
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        for i in range(max(api_clients, 5)):
            try:
                async with session.post(f"{base_url}/api/v1/packets", json=SAMPLE_PACKET, headers=headers):
                    pass
            except Exception:
                pass

    api_metrics_list: list[ClientMetrics] = []
    ws_metrics_list: list[ClientMetrics] = []
    tasks: list[asyncio.Task] = []
    stop_event = asyncio.Event()

    async with aiohttp.ClientSession() as session:
        # Start REST clients
        for i in range(api_clients):
            m = ClientMetrics(client_id=i, protocol="rest")
            api_metrics_list.append(m)
            tasks.append(asyncio.create_task(
                _rest_client_worker(base_url, api_key, m, stop_event, session)
            ))

        # Start WS clients
        for i in range(ws_clients):
            m = ClientMetrics(client_id=api_clients + i, protocol="ws")
            ws_metrics_list.append(m)
            tasks.append(asyncio.create_task(
                _ws_client_worker(ws_url, api_key, m, stop_event)
            ))

        # Let them run
        await asyncio.sleep(duration_sec)
        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate
    total_reqs = sum(m.requests_made for m in api_metrics_list)
    total_errors = sum(m.errors for m in api_metrics_list) + sum(m.errors for m in ws_metrics_list)
    total_ws_events = sum(m.events_received for m in ws_metrics_list)
    connected_ws = sum(1 for m in ws_metrics_list if m.connected)
    dropped_ws = sum(1 for m in ws_metrics_list if m.disconnected)

    return {
        "scenario": f"{api_clients}REST+{ws_clients}WS",
        "api_clients": api_clients,
        "ws_clients": ws_clients,
        "total_clients": api_clients + ws_clients,
        "api_requests": total_reqs,
        "api_errors": sum(m.errors for m in api_metrics_list),
        "api_error_rate": sum(m.errors for m in api_metrics_list) / max(total_reqs, 1) * 100,
        "ws_connected": connected_ws,
        "ws_dropped": dropped_ws,
        "ws_events": total_ws_events,
        "ws_connect_times": [m.connect_time for m in ws_metrics_list if m.connect_time > 0],
    }


async def run_concurrent_benchmark(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    api_key: str = DEFAULT_API_KEY,
    api_levels: list[int] | None = None,
    ws_levels: list[int] | None = None,
    duration_sec: int = DEFAULT_DURATION,
    inprocess: bool = DEFAULT_INPROCESS,
) -> list[dict[str, Any]]:
    """Run concurrent client scenarios."""
    if api_levels is None:
        api_levels = DEFAULT_API_CLIENTS
    if ws_levels is None:
        ws_levels = DEFAULT_WS_CLIENTS

    results: list[dict[str, Any]] = []

    # REST-only scenarios
    for api_c in api_levels:
        print(f"  REST-only: {api_c} clients ...", end="", flush=True)
        r = await run_scenario(api_clients=api_c, ws_clients=0, host=host, port=port,
                                api_key=api_key, duration_sec=duration_sec, inprocess=inprocess)
        results.append(r)
        print(f"  {r['api_requests']} req, {r['api_errors']} err")

    # Mixed scenarios
    for api_c, ws_c in [(10, 10), (25, 25), (50, 50)]:
        print(f"  Mixed: {api_c}REST+{ws_c}WS ...", end="", flush=True)
        r = await run_scenario(api_clients=api_c, ws_clients=ws_c, host=host, port=port,
                                api_key=api_key, duration_sec=duration_sec, inprocess=inprocess)
        results.append(r)
        print(f"  API: {r['api_requests']} req, WS: {r['ws_events']} evt, "
              f"conn: {r['ws_connected']}/{ws_c}")

    # WS-only scenarios
    for ws_c in ws_levels:
        print(f"  WS-only: {ws_c} clients ...", end="", flush=True)
        r = await run_scenario(api_clients=0, ws_clients=ws_c, host=host, port=port,
                                api_key=api_key, duration_sec=duration_sec, inprocess=inprocess)
        results.append(r)
        print(f"  {r['ws_events']} events, {r['ws_connected']}/{ws_c} connected")

    return results


def print_results(results: list[dict[str, Any]]) -> None:
    """Pretty-print concurrent clients benchmark results."""
    print_header("Concurrent Clients Benchmark")
    rows = []
    for r in results:
        ws_ct = ""
        if r["ws_connect_times"]:
            sorted_ct = sorted(r["ws_connect_times"])
            ws_ct = f"{statistics.median(sorted_ct)*1000:.0f}ms"
        ws_status = f"{r['ws_connected']}/{r['ws_clients']}"
        if r["ws_dropped"]:
            ws_status += f" ({r['ws_dropped']} dropped)"

        rows.append({
            "scenario": r["scenario"],
            "total": str(r["total_clients"]),
            "api_req": str(r["api_requests"]),
            "api_err": f"{r['api_error_rate']:.1f}%",
            "ws_evt": str(r["ws_events"]),
            "ws_conn": ws_status,
            "ws_conn_time": ws_ct,
        })
    print_table(
        rows,
        [("scenario", "Scenario"), ("total", "Total"), ("api_req", "API Req"),
         ("api_err", "API Err%"), ("ws_evt", "WS Evt"),
         ("ws_conn", "WS Connected"), ("ws_conn_time", "WS Conn Time")],
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="HandoffRail Concurrent Clients Benchmark")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION)
    parser.add_argument("--api-clients", type=int, nargs="+", default=DEFAULT_API_CLIENTS)
    parser.add_argument("--ws-clients", type=int, nargs="+", default=DEFAULT_WS_CLIENTS)
    parser.add_argument("--inprocess", action="store_true", default=DEFAULT_INPROCESS)
    parser.add_argument("--all", action="store_true", help="Run all scenario combinations")
    args = parser.parse_args()

    print("═" * 70)
    print("  HandoffRail — Concurrent Clients Benchmark")
    print(f"  Target: {'in-process' if args.inprocess else f'http://{args.host}:{args.port}'}")
    print(f"  Duration: {args.duration}s")
    print("═" * 70)

    results = await run_concurrent_benchmark(
        host=args.host,
        port=args.port,
        api_key=args.api_key or DEFAULT_API_KEY,
        api_levels=args.api_clients if not args.all else [10, 25, 50],
        ws_levels=args.ws_clients if not args.all else [10, 25, 50],
        duration_sec=args.duration,
        inprocess=args.inprocess,
    )
    print_results(results)


if __name__ == "__main__":
    asyncio.run(main())
