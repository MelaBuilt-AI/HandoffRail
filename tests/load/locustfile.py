"""HandoffRail Locust load test — REST API endpoint benchmarking.

Tests POST /api/v1/packets, GET /api/v1/packets, and GET /api/v1/stats
with realistic user behaviour.

Usage:
    locust -f tests/load/locustfile.py --host=http://localhost:8080
    # Then open http://localhost:8089 in browser, or run headless:
    locust -f tests/load/locustfile.py --host=http://localhost:8080
           --headless -u 50 -r 10 --run-time 60s
"""

from __future__ import annotations

import json
import time
from typing import Any

from locust import FastHttpUser, between, task

# ── Test data templates ────────────────────────────────────────────────────────

SAMPLE_PACKET: dict[str, Any] = {
    "metadata": {
        "source_agent": {"id": "locust-source", "name": "Locust Source", "framework": "locust"},
        "target_agent": {"id": "locust-target", "name": "Locust Target", "framework": "locust"},
        "priority": "normal",
        "tags": ["load-test"],
    },
    "context": {
        "conversation_state": [{"role": "user", "content": "Load test message"}],
        "summary": "Load test packet from locust",
    },
    "decisions": [],
    "actions": {"pending": [], "completed": [], "failed": []},
    "dependencies": [],
}

SAMPLE_PACKET_UPDATE: dict[str, Any] = {
    "status": "in_progress",
    "decisions": [
        {"id": "locust-dec-1", "decision": "proceed", "rationale": "Load test", "timestamp": time.time()},
    ],
}


class HandoffRailUser(FastHttpUser):
    """Simulates a HandoffRail API consumer.

    Mix of read and write operations with realistic pacing.
    """

    wait_time = between(0.5, 2.0)
    host = "http://localhost:8080"
    # API key header — set via environment or default
    api_key: str = "test-api-key"

    def on_start(self) -> None:
        """Set up common headers on start."""
        self.client.headers.update({
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        })

    @task(3)
    def list_packets(self) -> None:
        """GET /api/v1/packets — list recent packets."""
        with self.client.get(
            "/api/v1/packets?limit=20",
            name="GET /api/v1/packets",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")

    @task(3)
    def get_stats(self) -> None:
        """GET /api/v1/stats — dashboard statistics."""
        with self.client.get(
            "/api/v1/stats",
            name="GET /api/v1/stats",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")

    @task(2)
    def create_packet(self) -> None:
        """POST /api/v1/packets — create a new handoff packet."""
        with self.client.post(
            "/api/v1/packets",
            json=SAMPLE_PACKET,
            name="POST /api/v1/packets",
            catch_response=True,
        ) as resp:
            if resp.status_code == 201:
                resp.success()
                # Store the created packet ID for potential follow-up
                try:
                    data = resp.json()
                    packet_id = data.get("id", "")
                    if packet_id and packet_id != "00000000-0000-0000-0000-000000000000":
                        self.environment.runner.environment.stats.log_request(
                            request_type="POST",
                            name="POST /api/v1/packets (created)",
                            response_time=resp.elapsed.total_seconds() * 1000,
                            response_length=len(resp.content),
                        )
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")

    @task(1)
    def get_awaiting_human(self) -> None:
        """GET /api/v1/packets/awaiting — HITL queue depth."""
        with self.client.get(
            "/api/v1/packets/awaiting",
            name="GET /api/v1/packets/awaiting",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")

    @task(1)
    def check_health(self) -> None:
        """GET /health — health check endpoint."""
        with self.client.get(
            "/health",
            name="GET /health",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")
