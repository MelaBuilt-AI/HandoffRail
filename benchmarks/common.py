"""Shared utilities and data for benchmark scripts."""

from __future__ import annotations

import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── path setup for in-process mode ──────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "server"))
sys.path.insert(0, str(_PROJECT_ROOT / "sdk" / "src"))

# ── environment defaults ────────────────────────────────────────────────────
DEFAULT_HOST = os.environ.get("HR_BENCH_HOST", "localhost")
DEFAULT_PORT = int(os.environ.get("HR_BENCH_PORT", "8080"))
DEFAULT_API_KEY = os.environ.get("HR_BENCH_API_KEY", "")
DEFAULT_DURATION = int(os.environ.get("HR_BENCH_DURATION", "10"))
DEFAULT_CONCURRENCY_LEVELS = [int(x) for x in os.environ.get("HR_BENCH_CONCURRENCY", "5,10,25,50").split(",")]
DEFAULT_INPROCESS = os.environ.get("HR_BENCH_INPROCESS", "").lower() in ("1", "true", "yes")

# ── benchmark payload templates ─────────────────────────────────────────────

SAMPLE_PACKET: dict[str, Any] = {
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


@dataclass
class LatencyStats:
    """Per-endpoint or per-flow latency statistics."""

    samples: int = 0
    min: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    max: float = 0.0
    mean: float = 0.0
    stdev: float = 0.0

    @classmethod
    def from_latencies(cls, latencies: list[float]) -> LatencyStats:
        if not latencies:
            return cls()
        sorted_lat = sorted(latencies)
        n = len(sorted_lat)
        return cls(
            samples=n,
            min=sorted_lat[0],
            p50=statistics.median(sorted_lat),
            p95=sorted_lat[int(n * 0.95)],
            p99=sorted_lat[int(n * 0.99)],
            max=sorted_lat[-1],
            mean=statistics.mean(sorted_lat),
            stdev=statistics.stdev(sorted_lat) if n > 1 else 0.0,
        )

    def as_ms(self) -> LatencyStats:
        """Return a copy with values converted to milliseconds."""
        return LatencyStats(
            samples=self.samples,
            min=self.min * 1000,
            p50=self.p50 * 1000,
            p95=self.p95 * 1000,
            p99=self.p99 * 1000,
            max=self.max * 1000,
            mean=self.mean * 1000,
            stdev=self.stdev * 1000,
        )


@dataclass
class BenchmarkRound:
    """Metrics for one benchmark round."""

    name: str
    concurrency: int
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    latencies: list[float] = field(default_factory=list)
    total_bytes: int = 0
    duration_sec: float = 0.0

    @property
    def requests_per_second(self) -> float:
        return self.total_requests / self.duration_sec if self.duration_sec > 0 else 0.0

    @property
    def error_rate(self) -> float:
        return self.failed / self.total_requests * 100 if self.total_requests > 0 else 0.0

    def latency(self) -> LatencyStats:
        return LatencyStats.from_latencies(self.latencies)


def print_header(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def print_table(
    rows: list[dict[str, str]],
    columns: list[tuple[str, str]],  # (key, header)
) -> None:
    """Print a simple aligned table."""
    if not rows:
        return
    widths = {key: len(header) for key, header in columns}
    for row in rows:
        for key, _ in columns:
            widths[key] = max(widths.get(key, 0), len(row.get(key, "")))
    fmt = "  " + " | ".join(f"{{{k}:<{widths[k]}}}" for k, _ in columns)
    print(fmt.format(**{k: h for k, h in columns}))
    print("  " + "-" * (sum(widths.values()) + 3 * (len(columns) - 1)))
    for row in rows:
        print(fmt.format(**row))
