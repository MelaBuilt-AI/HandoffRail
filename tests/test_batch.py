"""Tests for batch operations API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from httpx import AsyncClient

# Add server dir to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))


def _make_packet_payload(source_id="agent-a", target_id="agent-b", summary="Test handoff"):
    """Build a minimal valid packet payload."""
    return {
        "metadata": {
            "source_agent": {"id": source_id, "name": "Agent A"},
            "target_agent": {"id": target_id, "name": "Agent B"},
            "priority": "normal",
        },
        "context": {"summary": summary},
        "decisions": [],
        "actions": {"pending": [], "completed": [], "failed": []},
        "dependencies": [],
        "hitl": None,
    }


pytestmark = pytest.mark.asyncio


class TestBatchCreate:
    """Tests for POST /api/v1/packets/batch."""

    async def test_batch_create_success(self, client: AsyncClient):
        """Batch create multiple packets successfully."""
        resp = await client.post("/api/v1/packets/batch", json={
            "packets": [
                _make_packet_payload(summary="Batch packet 1"),
                _make_packet_payload(summary="Batch packet 2"),
                _make_packet_payload(summary="Batch packet 3"),
            ],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["created"]) == 3
        assert len(data["errors"]) == 0
        summaries = [p["context"]["summary"] for p in data["created"]]
        assert "Batch packet 1" in summaries
        assert "Batch packet 3" in summaries

    async def test_batch_create_empty_list(self, client: AsyncClient):
        """Empty packet list should return 422 (validation error)."""
        resp = await client.post("/api/v1/packets/batch", json={"packets": []})
        assert resp.status_code == 422

    async def test_batch_create_exceeds_limit(self, client: AsyncClient):
        """Exceeding max batch size should return 400."""
        packets = [_make_packet_payload(summary=f"Packet {i}") for i in range(51)]
        resp = await client.post("/api/v1/packets/batch", json={"packets": packets})
        assert resp.status_code == 400

    async def test_batch_create_partial_failure(self, client: AsyncClient):
        """Batch with one invalid packet returns 201 with partial errors."""
        resp = await client.post("/api/v1/packets/batch", json={
            "packets": [
                _make_packet_payload(summary="Valid packet"),
                {"metadata": {}, "context": {}},
            ],
        })
        # Now that we accept raw dicts, invalid packets become partial errors
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["created"]) == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["index"] == 1


class TestBatchClaim:
    """Tests for POST /api/v1/packets/batch/claim."""

    async def test_batch_claim_success(self, client: AsyncClient):
        """Claim multiple packets successfully."""
        # First create some packets
        create_resp = await client.post("/api/v1/packets/batch", json={
            "packets": [
                _make_packet_payload(summary="Claim me 1"),
                _make_packet_payload(summary="Claim me 2"),
            ],
        })
        created = create_resp.json()["created"]
        packet_ids = [p["id"] for p in created]

        # Now batch claim
        resp = await client.post("/api/v1/packets/batch/claim", json={
            "packet_ids": packet_ids,
            "agent_id": "claimer-01",
            "agent_name": "ClaimerBot",
            "framework": "langchain",
        })
        assert resp.status_code == 200, f"Response: {resp.text}"
        data = resp.json()
        assert len(data["claimed"]) == 2
        assert len(data["errors"]) == 0

    async def test_batch_claim_already_claimed(self, client: AsyncClient):
        """Claiming an already-claimed packet returns error for that entry."""
        # Create and claim a packet first
        create_resp = await client.post("/api/v1/packets/batch", json={
            "packets": [_make_packet_payload(summary="Already claimed")],
        })
        pkt_id = create_resp.json()["created"][0]["id"]

        await client.post("/api/v1/packets/batch/claim", json={
            "packet_ids": [pkt_id],
            "agent_id": "first-claimer",
            "agent_name": "FirstBot",
        })

        # Second claim attempt
        resp = await client.post("/api/v1/packets/batch/claim", json={
            "packet_ids": [pkt_id],
            "agent_id": "second-claimer",
            "agent_name": "SecondBot",
        })
        assert resp.status_code == 200, f"Response: {resp.text}"
        data = resp.json()
        assert len(data["claimed"]) == 0
        assert len(data["errors"]) == 1

    async def test_batch_claim_not_found(self, client: AsyncClient):
        """Claiming non-existent packet returns error."""
        resp = await client.post("/api/v1/packets/batch/claim", json={
            "packet_ids": ["00000000-0000-0000-0000-000000000000"],
            "agent_id": "agent-01",
            "agent_name": "AgentBot",
        })
        assert resp.status_code == 200, f"Response: {resp.text}"
        data = resp.json()
        assert len(data["claimed"]) == 0
        assert len(data["errors"]) == 1


class TestBatchComplete:
    """Tests for POST /api/v1/packets/batch/complete."""

    async def test_batch_complete_success(self, client: AsyncClient):
        """Complete multiple packets successfully."""
        # Create and claim packets first
        create_resp = await client.post("/api/v1/packets/batch", json={
            "packets": [
                _make_packet_payload(summary="Complete me 1"),
                _make_packet_payload(summary="Complete me 2"),
            ],
        })
        ids = [p["id"] for p in create_resp.json()["created"]]

        await client.post("/api/v1/packets/batch/claim", json={
            "packet_ids": ids,
            "agent_id": "worker-01",
            "agent_name": "WorkerBot",
        })

        # Move to in_progress first (required by state machine)
        for pid in ids:
            await client.patch(f"/api/v1/packets/{pid}", json={"status": "in_progress"})

        # Now batch complete
        resp = await client.post("/api/v1/packets/batch/complete", json={
            "packet_ids": ids,
        })
        assert resp.status_code == 200, f"Response: {resp.text}"
        data = resp.json()
        assert len(data["completed"]) == 2
        assert len(data["errors"]) == 0
        for p in data["completed"]:
            assert p["status"] == "completed"

    async def test_batch_complete_not_found(self, client: AsyncClient):
        """Completing non-existent packet returns error."""
        resp = await client.post("/api/v1/packets/batch/complete", json={
            "packet_ids": ["00000000-0000-0000-0000-000000000000"],
        })
        assert resp.status_code == 200, f"Response: {resp.text}"
        data = resp.json()
        assert len(data["completed"]) == 0
        assert len(data["errors"]) == 1

    async def test_batch_complete_empty_list(self, client: AsyncClient):
        """Empty list should return 422."""
        resp = await client.post("/api/v1/packets/batch/complete", json={"packet_ids": []})
        assert resp.status_code == 422
