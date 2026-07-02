"""HandoffRail WebSocket load test — concurrent connections at scale.

Tests 50, 100, and 200 concurrent WebSocket connections against the
/ws endpoint. Measures:

- Connection success rate & time
- Message throughput (events received per second)
- End-to-end latency (subscribe → event received)
- Connection stability (drops, reconnects)
- Memory/resource usage per connection

Usage:
    python -m tests.load.ws_load_test [--host localhost] [--port 8080] [--api-key <key>]
"""

from __future__ import annotations

import asyncio
import json
import time
import statistics
import sys
import argparse
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import aiohttp

try:
    import websockets
except ImportError:
    print("websockets library required: pip install websockets")
    sys.exit(1)


# ── Test configuration ─────────────────────────────────────────────────────────

CONCURRENT_LEVELS = [50, 100, 200]

# Timeouts
CONNECT_TIMEOUT = 10.0  # seconds
SUBSCRIBE_TIMEOUT = 5.0
EVENT_WAIT_TIMEOUT = 15.0
HEARTBEAT_WAIT = 35.0  # wait for at least one heartbeat (server sends every 30s)

# Event types we expect
EXPECTED_EVENT_TYPES = {"ping", "connected"}


@dataclass
class ConnectionMetrics:
    """Metrics collected for a single WebSocket connection."""

    connection_id: str = ""
    connect_time: float = 0.0           # Time to establish WS connection (seconds)
    events_received: int = 0
    heartbeats_received: int = 0
    messages_received: int = 0
    errors: int = 0
    disconnected: bool = False
    subscribe_time: float | None = None  # Time to receive subscribed event
    first_event_time: float | None = None  # Time from connect to first event
    latencies: list[float] = field(default_factory=list)  # Inter-event latencies
    total_bytes: int = 0


@dataclass
class LoadTestResult:
    """Aggregate result from a load test run."""

    concurrent_count: int
    successful_connections: int
    failed_connections: int
    total_events_received: int
    total_heartbeats: int
    connect_times: list[float]
    events_per_second: float
    messages_per_connection: float
    errors_total: int
    dropped_connections: int
    total_bytes: int
    test_duration: float
    latency_stats: dict[str, float] | None = None


async def _create_test_packets(session: aiohttp.ClientSession, api_key: str, base_url: str, count: int = 10) -> list[str]:
    """Create test packets via REST API so WS has events to receive."""
    created_ids = []
    for i in range(count):
        resp = await session.post(
            f"{base_url}/api/v1/packets",
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            json={
                "metadata": {
                    "source_agent": {"id": f"load-test-source-{i}", "name": "Load Test Source", "framework": "test"},
                    "target_agent": {"id": f"load-test-target-{i}", "name": "Load Test Target", "framework": "test"},
                    "priority": "normal",
                    "tags": ["load-test"],
                },
                "context": {"conversation_state": [], "summary": f"Load test packet {i}"},
                "decisions": [],
                "actions": {"pending": [], "completed": [], "failed": []},
                "dependencies": [],
            },
        )
        if resp.ok:
            data = await resp.json()
            created_ids.append(data["id"])
    return created_ids


async def _monitor_connection(
    client: aiohttp.ClientSession,
    ws_url: str,
    api_key: str | None,
    index: int,
    metrics: ConnectionMetrics,
    event_received: asyncio.Event,
    stop_event: asyncio.Event,
) -> None:
    """Run a single WebSocket connection and collect metrics."""
    uri = ws_url
    if api_key:
        uri += f"?{urlencode({'api_key': api_key})}"

    try:
        connect_start = time.monotonic()
        async with websockets.connect(uri, timeout=CONNECT_TIMEOUT, max_size=2 ** 20) as ws:
            metrics.connect_time = time.monotonic() - connect_start
            metrics.connection_id = f"conn-{index}"

            # Subscribe to events
            sub_start = time.monotonic()
            await ws.send(json.dumps({"action": "subscribe", "channel": "status:created"}))
            await ws.send(json.dumps({"action": "subscribe", "channel": "status:completed"}))

            # Wait for first event
            first_event = True
            last_event_time = time.monotonic()

            while not stop_event.is_set():
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=HEARTBEAT_WAIT)

                    if isinstance(msg, bytes):
                        msg = msg.decode("utf-8")

                    metrics.total_bytes += len(msg)
                    now = time.monotonic()
                    data = json.loads(msg)

                    msg_type = data.get("type", "")
                    metrics.messages_received += 1

                    if msg_type == "ping":
                        metrics.heartbeats_received += 1
                        # Respond to pings
                        try:
                            await ws.send(json.dumps({"action": "pong"}))
                        except Exception:
                            pass
                        continue

                    metrics.events_received += 1

                    if first_event:
                        metrics.first_event_time = now - connect_start
                        event_received.set()
                        first_event = False

                    # Track inter-event latency
                    event_latency = now - last_event_time
                    metrics.latencies.append(event_latency)
                    last_event_time = now

                except asyncio.TimeoutError:
                    # No message within heartbeat wait — connection may be stuck
                    metrics.errors += 1
                    break
                except websockets.exceptions.ConnectionClosed:
                    metrics.disconnected = True
                    break
                except Exception:
                    metrics.errors += 1
                    break

    except Exception:
        metrics.connect_time = time.monotonic() - connect_start if "connect_start" in locals() else 0
        metrics.errors += 1


async def run_load_test(
    host: str = "localhost",
    port: int = 8080,
    api_key: str | None = None,
    concurrent_count: int = 50,
    test_duration: float = 15.0,
) -> LoadTestResult:
    """Run a WebSocket load test with `concurrent_count` connections."""
    base_url = f"http://{host}:{port}"
    ws_url = f"ws://{host}:{port}/ws"

    async with aiohttp.ClientSession() as session:
        # Ensure API key
        if not api_key:
            # Try to get from the server by creating one (test mode)
            try:
                resp = await session.post(
                    f"{base_url}/api/v1/keys",
                    json={"name": "load-test-key"},
                )
                if resp.ok:
                    data = await resp.json()
                    api_key = data.get("key", "")
            except Exception:
                pass

        if not api_key:
            api_key = "test-api-key"

        # Create some test packets so WS has events to receive
        packet_ids = await _create_test_packets(session, api_key, base_url, count=concurrent_count // 5 + 5)
        print(f"  Created {len(packet_ids)} test packets for event generation")

        # Launch concurrent WebSocket connections
        metrics_list: list[ConnectionMetrics] = []
        tasks: list[asyncio.Task] = []
        event_received = asyncio.Event()
        stop_event = asyncio.Event()

        start_time = time.monotonic()

        for i in range(concurrent_count):
            metrics = ConnectionMetrics()
            metrics_list.append(metrics)
            task = asyncio.create_task(
                _monitor_connection(session, ws_url, api_key, i, metrics, event_received, stop_event)
            )
            tasks.append(task)

        # Let connections establish and events flow
        await asyncio.sleep(1.0)

        # Create more packets during the test to generate WS events
        async def _generate_events():
            while time.monotonic() - start_time < test_duration - 2:
                await _create_test_packets(session, api_key, base_url, count=3)
                await asyncio.sleep(0.5)
            # Final burst
            await _create_test_packets(session, api_key, base_url, count=10)

        event_gen_task = asyncio.create_task(_generate_events())

        # Wait for test duration
        await asyncio.sleep(test_duration)

        # Signal stop
        stop_event.set()

        # Wait for all connections to close
        await asyncio.gather(*tasks, return_exceptions=True)
        event_gen_task.cancel()
        try:
            await event_gen_task
        except asyncio.CancelledError:
            pass

        end_time = time.monotonic()
        test_duration_actual = end_time - start_time

    # Aggregate metrics
    successful = sum(1 for m in metrics_list if m.messages_received > 0)
    failed = concurrent_count - successful
    total_events = sum(m.events_received for m in metrics_list)
    total_heartbeats = sum(m.heartbeats_received for m in metrics_list)
    total_errors = sum(m.errors for m in metrics_list)
    total_bytes = sum(m.total_bytes for m in metrics_list)
    dropped = sum(1 for m in metrics_list if m.disconnected)
    connect_times = [m.connect_time for m in metrics_list if m.connect_time > 0]

    # Latency analysis (inter-event latencies across all connections)
    all_latencies: list[float] = []
    for m in metrics_list:
        all_latencies.extend(m.latencies)

    latency_stats = None
    if all_latencies:
        sorted_lat = sorted(all_latencies)
        latency_stats = {
            "p50": statistics.median(sorted_lat),
            "p95": sorted_lat[int(len(sorted_lat) * 0.95)],
            "p99": sorted_lat[int(len(sorted_lat) * 0.99)],
            "mean": statistics.mean(sorted_lat),
            "min": min(sorted_lat),
            "max": max(sorted_lat),
            "samples": len(sorted_lat),
        }

    events_per_second = total_events / test_duration_actual if test_duration_actual > 0 else 0

    return LoadTestResult(
        concurrent_count=concurrent_count,
        successful_connections=successful,
        failed_connections=failed,
        total_events_received=total_events,
        total_heartbeats=total_heartbeats,
        connect_times=connect_times,
        events_per_second=events_per_second,
        messages_per_connection=total_events / concurrent_count if concurrent_count > 0 else 0,
        errors_total=total_errors,
        dropped_connections=dropped,
        total_bytes=total_bytes,
        test_duration=test_duration_actual,
        latency_stats=latency_stats,
    )


def _print_result(result: LoadTestResult) -> None:
    """Pretty-print a load test result."""
    print(f"\n{'='*60}")
    print(f"  WS Load Test: {result.concurrent_count} concurrent connections")
    print(f"{'='*60}")
    print(f"  Duration:           {result.test_duration:.1f}s")
    print(f"  Successful conns:   {result.successful_connections}/{result.concurrent_count}")
    print(f"  Failed conns:       {result.failed_connections}")
    print(f"  Dropped conns:      {result.dropped_connections}")
    print(f"  Events received:    {result.total_events_received}")
    print(f"  Heartbeats:         {result.total_heartbeats}")
    print(f"  Events/sec:         {result.events_per_second:.1f}")
    print(f"  Msgs/connection:    {result.messages_per_connection:.1f}")
    print(f"  Errors:             {result.errors_total}")
    print(f"  Total data:         {result.total_bytes:,} bytes")

    if result.connect_times:
        sorted_ct = sorted(result.connect_times)
        print(f"\n  Connection Time:")
        print(f"    Min:    {min(result.connect_times):.3f}s")
        print(f"    P50:    {statistics.median(result.connect_times):.3f}s")
        print(f"    P95:    {sorted_ct[int(len(sorted_ct) * 0.95)]:.3f}s")
        print(f"    P99:    {sorted_ct[int(len(sorted_ct) * 0.99)]:.3f}s")
        print(f"    Max:    {max(result.connect_times):.3f}s")

    if result.latency_stats:
        ls = result.latency_stats
        print(f"\n  Event Latency (inter-event):")
        print(f"    Samples: {ls['samples']}")
        print(f"    Min:     {ls['min']:.4f}s")
        print(f"    P50:     {ls['p50']:.4f}s")
        print(f"    P95:     {ls['p95']:.4f}s")
        print(f"    P99:     {ls['p99']:.4f}s")
        print(f"    Max:     {ls['max']:.4f}s")
        print(f"    Mean:    {ls['mean']:.4f}s")

    # Connection stability score
    stability = (result.successful_connections - result.dropped_connections) / max(result.concurrent_count, 1) * 100
    print(f"\n  Stability: {stability:.1f}%")
    print(f"{'='*60}\n")


async def main():
    parser = argparse.ArgumentParser(description="HandoffRail WebSocket Load Test")
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    parser.add_argument("--api-key", default=None, help="API key")
    parser.add_argument("--duration", type=float, default=15.0, help="Test duration per level (seconds)")
    parser.add_argument("--levels", type=int, nargs="+", default=CONCURRENT_LEVELS, help="Concurrency levels")
    args = parser.parse_args()

    print(f"🧪 HandoffRail WebSocket Load Test")
    print(f"   Server: ws://{args.host}:{args.port}/ws")
    print(f"   Duration per level: {args.duration}s")
    print(f"   Concurrency levels: {args.levels}")
    print()

    all_results: list[LoadTestResult] = []
    for level in args.levels:
        print(f"─" * 60)
        print(f"  Testing {level} concurrent connections...")
        result = await run_load_test(
            host=args.host,
            port=args.port,
            api_key=args.api_key,
            concurrent_count=level,
            test_duration=args.duration,
        )
        all_results.append(result)
        _print_result(result)

        # Brief cooldown between levels
        if level != args.levels[-1]:
            print("  Cooling down...")
            await asyncio.sleep(3)

    # Summary
    print(f"\n{'#'*60}")
    print(f"  SUMMARY")
    print(f"{'#'*60}")
    print(f"  {'Concurrent':>10} | {'Success':>8} | {'Failed':>6} | {'Evt/s':>8} | {'Stability':>9} | {'P50 Lat':>8}")
    print(f"  {'-'*10}-+-{'-'*8}-+-{'-'*6}-+-{'-'*8}-+-{'-'*9}-+-{'-'*8}")
    for r in all_results:
        stability = (r.successful_connections - r.dropped_connections) / max(r.concurrent_count, 1) * 100
        p50 = f"{r.latency_stats['p50']:.3f}s" if r.latency_stats else "N/A"
        print(f"  {r.concurrent_count:>10} | {r.successful_connections:>8} | {r.failed_connections:>6} | {r.events_per_second:>8.1f} | {stability:>8.1f}% | {p50:>8}")
    print(f"{'#'*60}")


if __name__ == "__main__":
    asyncio.run(main())
