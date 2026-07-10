"""HandoffRail Locust Load Test — realistic user scenarios.

Simulates agents creating, claiming, completing handoff packets
and querying history under load. Configurable via environment
variables:

    HOST          — target server (default: http://localhost:8080)
    USERS         — peak concurrent users (default: 50)
    SPAWN_RATE    — users spawned per second (default: 10)
    DURATION      — test duration in seconds (default: 60)

Usage:
    # Interactive (open http://localhost:8089 in browser):
    locust -f loadtests/locustfile.py --host=http://localhost:8080

    # Headless automated run:
    locust -f loadtests/locustfile.py --host=http://localhost:8080 \
        --headless -u 50 -r 10 --run-time 60s

    # With environment variables:
    HOST=http://localhost:8080 USERS=100 SPAWN_RATE=20 \
        locust -f loadtests/locustfile.py --headless -u 100 -r 20
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from locust import FastHttpUser, between, task

# ── test data ────────────────────────────────────────────────────────────────

SAMPLE_PACKET: dict[str, Any] = {
    "metadata": {
        "source_agent": {"id": "loadtest-source", "name": "Load Source", "framework": "loadtest"},
        "target_agent": {"id": "loadtest-target", "name": "Load Target", "framework": "loadtest"},
        "priority": "normal",
        "tags": ["load-test"],
    },
    "context": {
        "conversation_state": [{"role": "user", "content": "Load test message from locust"}],
        "summary": "Load test packet",
    },
    "decisions": [
        {"id": "ld-dec-1", "decision": "proceed", "rationale": "Load test", "timestamp": time.time()},
    ],
    "actions": {"pending": [], "completed": [], "failed": []},
    "dependencies": [],
}

SAMPLE_CLAIM: dict[str, Any] = {
    "claimed_by": "loadtest-worker",
}

SAMPLE_COMPLETE: dict[str, Any] = {
    "status": "completed",
    "outcome": {"result": "success"},
}

SAMPLE_WEBHOOK: dict[str, Any] = {
    "url": "http://localhost:19999/webhook",
    "events": ["packet.created", "packet.completed", "packet.failed"],
}


class HandoffRailUser(FastHttpUser):
    """Simulates a realistic API consumer mixing reads and writes.

    Task weights approximate a typical workload:
      - Read operations (list, stats, health): ~50%
      - Write operations (create, claim, complete): ~40%
      - Admin operations (hook registration): ~10%
    """

    wait_time = between(0.3, 1.5)
    host = os.environ.get("HOST", "http://localhost:8080")
    api_key = os.environ.get("HR_API_KEY", "test-api-key")

    _created_packets: list[str] = []
    _webhook_id: str = ""

    def on_start(self) -> None:
        """Set up headers and optionally register a test webhook."""
        self.client.headers.update({
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        })

    @task(4)
    def list_packets(self) -> None:
        """GET /api/v1/packets — list recent packets."""
        with self.client.get(
            "/api/v1/packets?limit=20",
            name="GET /api/v1/packets",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 304):
                resp.success()
            elif resp.status_code == 401:
                resp.failure("Unauthorized — check API key")
            else:
                resp.failure(f"Unexpected: {resp.status_code}")

    @task(2)
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
                resp.failure(f"Unexpected: {resp.status_code}")

    @task(1)
    def check_health(self) -> None:
        """GET /health — health check."""
        with self.client.get(
            "/health",
            name="GET /health",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                if resp.elapsed.total_seconds() > 2.0:
                    resp.failure(f"Slow health check: {resp.elapsed.total_seconds() * 1000:.0f}ms")
                else:
                    resp.success()
            else:
                resp.failure(f"Unexpected: {resp.status_code}")

    @task(3)
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
                try:
                    data = resp.json()
                    pid = data.get("id", "")
                    if pid:
                        self._created_packets.append(pid)
                        # Keep max 10 tracked
                        self._created_packets = self._created_packets[-10:]
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            else:
                resp.failure(f"Unexpected: {resp.status_code}")

    @task(2)
    def create_and_claim_packet(self) -> None:
        """POST + claim — simulates a worker claiming a new packet.

        Pairs packet creation with immediate claim to exercise
        the state-machine transition.
        """
        with self.client.post(
            "/api/v1/packets",
            json=SAMPLE_PACKET,
            name="POST /api/v1/packets (claim flow)",
            catch_response=True,
        ) as resp:
            if resp.status_code != 201:
                resp.failure(f"Create failed: {resp.status_code}")
                return
            try:
                data = resp.json()
                pid = data.get("id", "")
            except (json.JSONDecodeError, KeyError):
                resp.failure("Bad create response")
                return

        if not pid:
            resp.failure("No packet ID")
            return

        with self.client.post(
            f"/api/v1/packets/{pid}/claim",
            json=SAMPLE_CLAIM,
            name="POST /api/v1/packets/[id]/claim",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 202):
                resp.success()
            else:
                resp.failure(f"Claim failed: {resp.status_code}")

    @task(1)
    def create_claim_complete(self) -> None:
        """Full lifecycle: create → claim → complete.

        Exercises the complete packet state-machine path.
        """
        # Create
        with self.client.post(
            "/api/v1/packets",
            json=SAMPLE_PACKET,
            name="POST /api/v1/packets (full lifecycle)",
            catch_response=True,
        ) as resp:
            if resp.status_code != 201:
                resp.failure(f"Create failed: {resp.status_code}")
                return
            try:
                data = resp.json()
                pid = data.get("id", "")
            except (json.JSONDecodeError, KeyError):
                resp.failure("Bad create response")
                return

        if not pid:
            return

        # Claim
        with self.client.post(
            f"/api/v1/packets/{pid}/claim",
            json=SAMPLE_CLAIM,
            name="POST /api/v1/packets/[id]/claim (full lifecycle)",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 202):
                resp.failure(f"Claim failed: {resp.status_code}")
                return

        # Complete
        with self.client.post(
            f"/api/v1/packets/{pid}/complete",
            json=SAMPLE_COMPLETE,
            name="POST /api/v1/packets/[id]/complete",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 202):
                resp.success()
            else:
                resp.failure(f"Complete failed: {resp.status_code}")

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
                resp.failure(f"Unexpected: {resp.status_code}")

    @task(1)
    def get_packet_detail(self) -> None:
        """GET /api/v1/packets/[id] — fetch a specific packet's details."""
        if not self._created_packets:
            self.create_packet()
            return
        pid = self._created_packets[-1]
        with self.client.get(
            f"/api/v1/packets/{pid}",
            name="GET /api/v1/packets/[id]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Unexpected: {resp.status_code}")

    @task(1)
    def create_webhook(self) -> None:
        """POST /api/v1/hooks — register a webhook subscription."""
        with self.client.post(
            "/api/v1/hooks",
            json=SAMPLE_WEBHOOK,
            name="POST /api/v1/hooks",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 201):
                resp.success()
            else:
                resp.failure(f"Unexpected: {resp.status_code}")

    @task(1)
    def search_packets(self) -> None:
        """GET /api/v1/packets?q=... — full-text search."""
        with self.client.get(
            "/api/v1/packets?q=load+test&limit=10",
            name="GET /api/v1/packets (search)",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Unexpected: {resp.status_code}")
