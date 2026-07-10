"""HandoffRail Webhook Delivery Latency Benchmark.

Measures end-to-end webhook delivery latency:
  1. Register a webhook pointing at a local listener
  2. Create packets and measure the time from creation to webhook receipt
  3. Reports p50/p95/p99 delivery latency, throughput, and reliability

Usage:
    # Against a running server (default)
    python -m benchmarks.benchmark_webhook_latency --host localhost --port 8080

    # In-process (no server needed)
    HR_BENCH_INPROCESS=1 python -m benchmarks.benchmark_webhook_latency

    # Custom webhook URL (for external testing)
    python -m benchmarks.benchmark_webhook_latency --webhook-url http://host:9999/hook
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
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


async def _get_base_url_and_key(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    api_key: str = DEFAULT_API_KEY,
    inprocess: bool = DEFAULT_INPROCESS,
) -> tuple[str, str, Any]:
    """Resolve the base URL and API key. Returns (base_url, api_key, transport_or_none)."""
    transport = None
    if inprocess:
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
            session.add(ApiKey(id="bench-webhook-key", name="bench-webhook", key_hash=hashed_key, key_prefix=plain_key[:8], tenant_id="default", tier="business"))
            await session.commit()
        await asyncio.sleep(0.1)
        transport = httpx.ASGITransport(app=app)
        return "", plain_key, transport
    else:
        if not api_key:
            api_key = DEFAULT_API_KEY
        return f"http://{host}:{port}", api_key, None


async def _run_webhook_listener(host: str, port: int, received_events: asyncio.Queue) -> None:
    """Run a lightweight HTTP server that captures webhook deliveries."""
    from aiohttp import web

    async def handle_webhook(request):
        body = await request.text()
        try:
            data = json.loads(body)
            event_type = data.get("event", "unknown")
            packet_id = data.get("packet_id", "")
            timestamp = data.get("timestamp", "")
            received_events.put_nowait({
                "event": event_type,
                "packet_id": packet_id,
                "timestamp": timestamp,
                "received_at": time.time(),
                "headers": dict(request.headers),
            })
        except Exception:
            pass
        return web.Response(status=200)

    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    try:
        # Keep running until cancelled
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()


async def _register_webhook(
    base_url: str,
    api_key: str,
    webhook_url: str,
    transport: Any,
    session: aiohttp.ClientSession | None = None,
) -> str:
    """Register a webhook via the API and return the webhook ID."""
    # Use in-process httpx if we have a transport
    if transport:
        import httpx
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/hooks",
                json={"url": webhook_url, "events": ["packet.created", "packet.claimed", "packet.completed", "packet.failed"]},
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            )
            if resp.status_code in (200, 201):
                return resp.json().get("id", str(uuid.uuid4()))
            return str(uuid.uuid4())
    else:
        async with session.post(
            f"{base_url}/api/v1/hooks",
            json={"url": webhook_url, "events": ["packet.created", "packet.claimed", "packet.completed", "packet.failed"]},
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        ) as resp:
            if resp.ok:
                data = await resp.json()
                return data.get("id", str(uuid.uuid4()))
            return str(uuid.uuid4())


async def _benchmark_webhook_worker(
    base_url: str,
    api_key: str,
    round_data: BenchmarkRound,
    stop_event: asyncio.Event,
    session: aiohttp.ClientSession,
    packet_id_queue: asyncio.Queue,
) -> None:
    """Worker: create packets and track sent timestamps for latency calculation."""
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    while not stop_event.is_set():
        try:
            start = time.perf_counter()
            async with session.post(f"{base_url}/api/v1/packets", json=SAMPLE_PACKET, headers=headers) as resp:
                elapsed = time.perf_counter() - start
                body = await resp.read()
                if resp.ok:
                    data = await resp.json()
                    pid = data.get("id", "")
                    if pid:
                        packet_id_queue.put_nowait((pid, time.time()))
                        round_data.total_requests += 1
                        round_data.successful += 1
                        round_data.total_bytes += len(body)
                        round_data.latencies.append(elapsed)
                    else:
                        round_data.total_requests += 1
                        round_data.failed += 1
                else:
                    round_data.total_requests += 1
                    round_data.failed += 1
        except Exception:
            round_data.total_requests += 1
            round_data.failed += 1


async def run_webhook_benchmark(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    api_key: str = DEFAULT_API_KEY,
    concurrency_levels: list[int] | None = None,
    duration_sec: int = DEFAULT_DURATION,
    inprocess: bool = DEFAULT_INPROCESS,
    webhook_host: str = "127.0.0.1",
    webhook_port: int = 19999,
) -> list[BenchmarkRound]:
    """Run the webhook delivery latency benchmark."""
    if concurrency_levels is None:
        concurrency_levels = DEFAULT_CONCURRENCY_LEVELS

    base_url, resolved_key, transport = await _get_base_url_and_key(host, port, api_key, inprocess)
    webhook_url = f"http://{webhook_host}:{webhook_port}/webhook"

    # Start local webhook listener
    received_events: asyncio.Queue = asyncio.Queue()
    listener_task = asyncio.create_task(
        _run_webhook_listener(webhook_host, webhook_port, received_events)
    )
    await asyncio.sleep(0.5)  # Let listener start

    # Register webhook
    wh_id = ""
    async with aiohttp.ClientSession() as session:
        wh_id = await _register_webhook(base_url, resolved_key, webhook_url, transport, session)
    print(f"  Registered webhook: {wh_id} -> {webhook_url}")

    results: list[BenchmarkRound] = []

    for concurrency in concurrency_levels:
        print(f"  Concurrency={concurrency} ...", end="", flush=True)

        round_data = BenchmarkRound(
            name="webhook delivery latency",
            concurrency=concurrency,
        )
        packet_id_queue: asyncio.Queue = asyncio.Queue()

        async with aiohttp.ClientSession() as session:
            stop_event = asyncio.Event()
            workers = [
                _benchmark_webhook_worker(base_url, resolved_key, round_data, stop_event, session, packet_id_queue)
                for _ in range(concurrency)
            ]
            tasks = [asyncio.create_task(w) for w in workers]

            # Collector: measure delivery latency from sent to received webhook
            delivery_latencies: list[float] = []
            collector_stop = asyncio.Event()

            async def _collector():
                sent_packets: dict[str, float] = {}
                while not collector_stop.is_set():
                    # Gather sent packet IDs
                    while not packet_id_queue.empty():
                        try:
                            pid, sent_at = packet_id_queue.get_nowait()
                            sent_packets[pid] = sent_at
                        except asyncio.QueueEmpty:
                            break

                    # Check for received webhook events
                    while not received_events.empty():
                        try:
                            event = received_events.get_nowait()
                            pid = event.get("packet_id", "")
                            if pid in sent_packets:
                                delivery_lat = time.time() - sent_packets[pid]
                                delivery_latencies.append(delivery_lat)
                                del sent_packets[pid]
                        except asyncio.QueueEmpty:
                            break

                    await asyncio.sleep(0.05)

            collector = asyncio.create_task(_collector())

            await asyncio.sleep(duration_sec)
            stop_event.set()
            await asyncio.gather(*tasks, return_exceptions=True)

            # Drain remaining events
            await asyncio.sleep(2)
            await _drain_events(received_events, packet_id_queue, collector_stop, collector, delivery_latencies)

        round_data.duration_sec = duration_sec

        # Override latencies with webhook delivery latencies
        if delivery_latencies:
            round_data.latencies = delivery_latencies
            ls = BenchmarkRound(
                name="", concurrency=concurrency, latencies=delivery_latencies, duration_sec=duration_sec
            ).latency().as_ms()
            print(f"  {len(delivery_latencies)} deliveries  "
                  f"p50={ls.p50:.1f}ms  p95={ls.p95:.1f}ms  "
                  f"p99={ls.p99:.1f}ms  err={round_data.error_rate:.1f}%")
        else:
            print(f"  No webhook deliveries received!")

        results.append(round_data)

    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    return results


async def _drain_events(
    received_events: asyncio.Queue,
    packet_id_queue: asyncio.Queue,
    collector_stop: asyncio.Event,
    collector: asyncio.Task,
    delivery_latencies: list[float],
) -> None:
    """Drain remaining events after benchmark stop."""
    sent_packets: dict[str, float] = {}
    while not packet_id_queue.empty():
        try:
            pid, t = packet_id_queue.get_nowait()
            sent_packets[pid] = t
        except asyncio.QueueEmpty:
            break

    for _ in range(50):
        while not received_events.empty():
            try:
                event = received_events.get_nowait()
                pid = event.get("packet_id", "")
                if pid in sent_packets:
                    delivery_latencies.append(time.time() - sent_packets[pid])
                    del sent_packets[pid]
            except asyncio.QueueEmpty:
                break
        await asyncio.sleep(0.1)

    collector_stop.set()
    await asyncio.gather(collector, return_exceptions=True)


def print_results(results: list[BenchmarkRound]) -> None:
    """Pretty-print webhook benchmark results."""
    print_header("Webhook Delivery Latency Benchmark")
    rows = []
    for r in results:
        ls = r.latency().as_ms()
        rows.append({
            "concurrency": str(r.concurrency),
            "deliveries": str(ls.samples),
            "p50": f"{ls.p50:.1f}ms",
            "p95": f"{ls.p95:.1f}ms",
            "p99": f"{ls.p99:.1f}ms",
            "mean": f"{ls.mean:.1f}ms",
            "max": f"{ls.max:.1f}ms",
        })
    print_table(
        rows,
        [("concurrency", "Concurr"), ("deliveries", "Deliveries"), ("p50", "P50"),
         ("p95", "P95"), ("p99", "P99"), ("mean", "Mean"), ("max", "Max")],
    )
    print(f"  ↑ Lower latencies = faster webhook delivery")


async def main() -> None:
    parser = argparse.ArgumentParser(description="HandoffRail Webhook Delivery Latency Benchmark")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--concurrency", type=int, nargs="+", default=DEFAULT_CONCURRENCY_LEVELS)
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION)
    parser.add_argument("--inprocess", action="store_true", default=DEFAULT_INPROCESS)
    parser.add_argument("--webhook-host", default="127.0.0.1", help="Local listener host")
    parser.add_argument("--webhook-port", type=int, default=19999, help="Local listener port")
    args = parser.parse_args()

    print("═" * 70)
    print("  HandoffRail — Webhook Delivery Latency Benchmark")
    print(f"  Target: {'in-process' if args.inprocess else f'http://{args.host}:{args.port}'}")
    print(f"  Webhook listener: http://{args.webhook_host}:{args.webhook_port}/webhook")
    print(f"  Concurrency levels: {args.concurrency}")
    print(f"  Duration per round: {args.duration}s")
    print("═" * 70)

    results = await run_webhook_benchmark(
        host=args.host,
        port=args.port,
        api_key=args.api_key or DEFAULT_API_KEY,
        concurrency_levels=args.concurrency,
        duration_sec=args.duration,
        inprocess=args.inprocess,
        webhook_host=args.webhook_host,
        webhook_port=args.webhook_port,
    )
    print_results(results)


if __name__ == "__main__":
    asyncio.run(main())
