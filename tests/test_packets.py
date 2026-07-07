"""HandoffRail API Server — Integration tests for packet endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from httpx import AsyncClient

# Add server dir to Python path so `app` module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))


def _minimal_payload() -> dict:
    """Return a minimal valid packet creation payload."""
    return {
        "metadata": {
            "source_agent": {"id": "test-source", "name": "TestSource", "framework": "test"},
            "target_agent": {"id": "test-target", "name": "TestTarget"},
            "priority": "normal",
            "tags": ["test"],
        },
        "context": {
            "summary": "Test handoff packet",
            "conversation_state": [
                {"role": "user", "content": "Hello"},
            ],
        },
        "decisions": [],
        "actions": {
            "pending": [],
            "completed": [],
            "failed": [],
        },
        "dependencies": [],
        "hitl": None,
    }


def _hitl_payload() -> dict:
    """Return a payload with a HITL checkpoint."""
    payload = _minimal_payload()
    payload["hitl"] = {
        "required": True,
        "reason": "Needs manager approval",
        "question": "Should we proceed?",
        "options": ["Yes", "No"],
    }
    return payload


# ── Create Packet Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_packet_minimal(client: AsyncClient):
    """POST /packets with minimal valid payload returns 201."""
    response = await client.post("/api/v1/packets", json=_minimal_payload())
    assert response.status_code == 201

    data = response.json()
    assert data["version"] == "1.0.0"
    assert data["status"] == "created"
    assert data["id"] is not None
    assert data["metadata"]["source_agent"]["id"] == "test-source"
    assert data["metadata"]["target_agent"]["id"] == "test-target"
    assert data["context"]["summary"] == "Test handoff packet"


@pytest.mark.asyncio
async def test_create_packet_with_decisions(client: AsyncClient):
    """POST /packets with decisions preserves them."""
    payload = _minimal_payload()
    payload["decisions"] = [
        {
            "id": "d1",
            "decision": "Proceed with upgrade",
            "rationale": "Customer is eligible",
            "alternatives": ["defer"],
            "decided_by": "test-source",
        }
    ]
    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert len(data["decisions"]) == 1
    assert data["decisions"][0]["id"] == "d1"
    assert data["decisions"][0]["rationale"] == "Customer is eligible"


@pytest.mark.asyncio
async def test_create_packet_with_actions(client: AsyncClient):
    """POST /packets with pending actions preserves them."""
    payload = _minimal_payload()
    payload["actions"]["pending"] = [
        {
            "id": "a1",
            "description": "Process payment",
            "assignee": "billing-01",
            "priority": "high",
            "depends_on": [],
        }
    ]
    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert len(data["actions"]["pending"]) == 1
    assert data["actions"]["pending"][0]["description"] == "Process payment"


@pytest.mark.asyncio
async def test_create_packet_with_dependencies(client: AsyncClient):
    """POST /packets with dependencies preserves them."""
    payload = _minimal_payload()
    payload["dependencies"] = [
        {
            "id": "dep1",
            "type": "api",
            "description": "Payment gateway must be up",
            "status": "available",
            "source": "stripe-api",
        }
    ]
    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert len(data["dependencies"]) == 1
    assert data["dependencies"][0]["type"] == "api"


@pytest.mark.asyncio
async def test_create_packet_with_hitl(client: AsyncClient):
    """POST /packets with HITL checkpoint sets status to awaiting_human."""
    response = await client.post("/api/v1/packets", json=_hitl_payload())
    assert response.status_code == 201

    data = response.json()
    assert data["status"] == "awaiting_human"
    assert data["hitl"]["required"] is True
    assert data["hitl"]["reason"] == "Needs manager approval"


@pytest.mark.asyncio
async def test_create_packet_with_parent(client: AsyncClient):
    """POST /packets with parent_packet_id preserves it."""
    payload = _minimal_payload()
    payload["parent_packet_id"] = "550e8400-e29b-41d4-a716-446655440000"
    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["parent_packet_id"] == "550e8400-e29b-41d4-a716-446655440000"


@pytest.mark.asyncio
async def test_create_packet_validation_error(client: AsyncClient):
    """POST /packets with missing required fields returns 422."""
    bad_payload = {
        "metadata": {
            "source_agent": {"id": "test", "name": "Test"},
            # Missing target_agent
        },
        "context": {"summary": "bad"},
    }
    response = await client.post("/api/v1/packets", json=bad_payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_packet_invalid_priority(client: AsyncClient):
    """POST /packets with invalid priority returns 422."""
    payload = _minimal_payload()
    payload["metadata"]["priority"] = "urgent"
    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_packet_invalid_status(client: AsyncClient):
    """POST /packets with invalid conversation role returns 422."""
    payload = _minimal_payload()
    payload["context"]["conversation_state"] = [
        {"role": "narrator", "content": "invalid role"}
    ]
    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_packet_with_artifacts(client: AsyncClient):
    """POST /packets with artifacts preserves them."""
    payload = _minimal_payload()
    payload["context"]["artifacts"] = [
        {
            "key": "customer_profile",
            "value": {"id": "cust-789", "tier": "pro"},
            "content_type": "application/json",
        }
    ]
    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert len(data["context"]["artifacts"]) == 1
    assert data["context"]["artifacts"][0]["key"] == "customer_profile"


@pytest.mark.asyncio
async def test_create_packet_with_custom_context(client: AsyncClient):
    """POST /packets with custom context fields preserves them."""
    payload = _minimal_payload()
    payload["context"]["custom"] = {"framework_version": "0.3.0", "session_id": "sess-123"}
    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["context"]["custom"]["framework_version"] == "0.3.0"


# ── Get Packet Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_packet_exists(client: AsyncClient):
    """GET /packets/{id} returns the created packet."""
    create_resp = await client.post("/api/v1/packets", json=_minimal_payload())
    assert create_resp.status_code == 201
    packet_id = create_resp.json()["id"]

    get_resp = await client.get(f"/api/v1/packets/{packet_id}")
    assert get_resp.status_code == 200

    data = get_resp.json()
    assert data["id"] == packet_id
    assert data["status"] == "created"
    assert data["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_get_packet_not_found(client: AsyncClient):
    """GET /packets/{id} with non-existent ID returns 404."""
    response = await client.get("/api/v1/packets/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_packet_preserves_all_fields(client: AsyncClient):
    """GET /packets/{id} preserves all nested fields from creation."""
    payload = _hitl_payload()
    payload["decisions"] = [
        {
            "id": "d1",
            "decision": "Escalate",
            "rationale": "Policy requires human review",
            "alternatives": ["deny"],
            "decided_by": "support-agent-01",
        }
    ]
    payload["actions"]["pending"] = [
        {
            "id": "a1",
            "description": "Review refund",
            "assignee": "human",
            "priority": "high",
            "depends_on": [],
        }
    ]
    payload["dependencies"] = [
        {
            "id": "dep1",
            "type": "human_approval",
            "description": "Manager must approve",
            "status": "blocked",
        }
    ]

    create_resp = await client.post("/api/v1/packets", json=payload)
    assert create_resp.status_code == 201
    packet_id = create_resp.json()["id"]

    get_resp = await client.get(f"/api/v1/packets/{packet_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()

    assert data["status"] == "awaiting_human"
    assert len(data["decisions"]) == 1
    assert len(data["actions"]["pending"]) == 1
    assert len(data["dependencies"]) == 1
    assert data["hitl"]["required"] is True
    assert data["context"]["summary"] == "Test handoff packet"


@pytest.mark.asyncio
async def test_list_packets_cursor_pagination(client: AsyncClient):
    """GET /packets supports cursor pagination while keeping offset compatibility."""
    for i in range(3):
        payload = _minimal_payload()
        payload["context"]["summary"] = f"Cursor packet {i}"
        response = await client.post("/api/v1/packets", json=payload)
        assert response.status_code == 201

    first_page = await client.get("/api/v1/packets", params={"limit": 2})
    assert first_page.status_code == 200
    first_data = first_page.json()
    assert len(first_data["packets"]) == 2
    assert first_data["next_cursor"]

    second_page = await client.get(
        "/api/v1/packets",
        params={"limit": 2, "cursor": first_data["next_cursor"]},
    )
    assert second_page.status_code == 200
    second_data = second_page.json()
    assert len(second_data["packets"]) == 1

    first_ids = {packet["id"] for packet in first_data["packets"]}
    second_ids = {packet["id"] for packet in second_data["packets"]}
    assert first_ids.isdisjoint(second_ids)


@pytest.mark.asyncio
async def test_list_packets_invalid_cursor(client: AsyncClient):
    """Malformed cursors return a 400 instead of silently falling back."""
    response = await client.get("/api/v1/packets", params={"cursor": "not-a-cursor"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid cursor"


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """GET /health returns ok status."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ── Batch Create Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_create_success(client: AsyncClient):
    """POST /packets/batch creates multiple packets successfully."""
    payload = {
        "packets": [
            _minimal_payload(),
            _minimal_payload(),
            _minimal_payload(),
        ]
    }
    response = await client.post("/api/v1/packets/batch", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert len(data["created"]) == 3
    assert len(data["errors"]) == 0
    for pkt in data["created"]:
        assert pkt["status"] == "created"
        assert pkt["id"] is not None


@pytest.mark.asyncio
async def test_batch_create_partial_failure(client: AsyncClient):
    """POST /packets/batch with one invalid packet returns partial success."""
    good = _minimal_payload()
    bad = {
        "metadata": {
            "source_agent": {"id": "bad", "name": "Bad"},
        },
        "context": {"summary": "bad"},
    }
    payload = {"packets": [good, bad, good]}
    response = await client.post("/api/v1/packets/batch", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert len(data["created"]) == 2
    assert len(data["errors"]) == 1
    assert data["errors"][0]["index"] == 1


@pytest.mark.asyncio
async def test_batch_create_exceeds_limit(client: AsyncClient):
    """POST /packets/batch with >50 packets returns 400."""
    payload = {"packets": [_minimal_payload() for _ in range(51)]}
    response = await client.post("/api/v1/packets/batch", json=payload)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_batch_create_with_hitl(client: AsyncClient):
    """POST /packets/batch with HITL packets sets awaiting_human status."""
    payload = {
        "packets": [
            _minimal_payload(),
            _hitl_payload(),
        ]
    }
    response = await client.post("/api/v1/packets/batch", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert len(data["created"]) == 2
    assert data["created"][0]["status"] == "created"
    assert data["created"][1]["status"] == "awaiting_human"


# ── Batch Claim Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_claim_success(client: AsyncClient):
    """POST /packets/batch/claim claims multiple packets."""
    # Create 3 packets first
    ids = []
    for _ in range(3):
        resp = await client.post("/api/v1/packets", json=_minimal_payload())
        assert resp.status_code == 201
        ids.append(resp.json()["id"])

    # Batch claim them
    response = await client.post("/api/v1/packets/batch/claim", json={
        "packet_ids": ids,
        "agent_id": "batch-agent",
        "agent_name": "BatchAgent",
        "framework": "test",
    })
    assert response.status_code == 200

    data = response.json()
    assert len(data["claimed"]) == 3
    assert len(data["errors"]) == 0
    for pkt in data["claimed"]:
        assert pkt["status"] == "claimed"


@pytest.mark.asyncio
async def test_batch_claim_already_claimed(client: AsyncClient):
    """POST /packets/batch/claim returns error for already-claimed packets."""
    # Create 2 packets
    ids = []
    for _ in range(2):
        resp = await client.post("/api/v1/packets", json=_minimal_payload())
        assert resp.status_code == 201
        ids.append(resp.json()["id"])

    # Claim first one
    await client.post(f"/api/v1/packets/{ids[0]}/claim", json={
        "agent_id": "other-agent",
        "agent_name": "OtherAgent",
    })

    # Batch claim both
    response = await client.post("/api/v1/packets/batch/claim", json={
        "packet_ids": ids,
        "agent_id": "batch-agent",
        "agent_name": "BatchAgent",
        "framework": "test",
    })
    assert response.status_code == 200

    data = response.json()
    assert len(data["claimed"]) == 1
    assert len(data["errors"]) == 1
    assert "Already claimed" in data["errors"][0]["error"]


@pytest.mark.asyncio
async def test_batch_claim_not_found(client: AsyncClient):
    """POST /packets/batch/claim returns error for non-existent packets."""
    response = await client.post("/api/v1/packets/batch/claim", json={
        "packet_ids": ["00000000-0000-0000-0000-000000000000"],
        "agent_id": "batch-agent",
        "agent_name": "BatchAgent",
    })
    assert response.status_code == 200

    data = response.json()
    assert len(data["claimed"]) == 0
    assert len(data["errors"]) == 1


# ── Batch Complete Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_complete_success(client: AsyncClient):
    """POST /packets/batch/complete completes multiple packets."""
    # Create and claim 3 packets
    ids = []
    for _ in range(3):
        resp = await client.post("/api/v1/packets", json=_minimal_payload())
        assert resp.status_code == 201
        pkt_id = resp.json()["id"]
        # Claim it
        await client.post(f"/api/v1/packets/{pkt_id}/claim", json={
            "agent_id": "batch-agent",
            "agent_name": "BatchAgent",
        })
        # Move to in_progress (required by state machine)
        await client.patch(f"/api/v1/packets/{pkt_id}", json={"status": "in_progress"})
        ids.append(pkt_id)

    # Batch complete them
    response = await client.post("/api/v1/packets/batch/complete", json={
        "packet_ids": ids,
    })
    assert response.status_code == 200

    data = response.json()
    assert len(data["completed"]) == 3
    assert len(data["errors"]) == 0
    for pkt in data["completed"]:
        assert pkt["status"] == "completed"


@pytest.mark.asyncio
async def test_batch_complete_not_found(client: AsyncClient):
    """POST /packets/batch/complete returns error for non-existent packets."""
    response = await client.post("/api/v1/packets/batch/complete", json={
        "packet_ids": ["00000000-0000-0000-0000-000000000000"],
    })
    assert response.status_code == 200

    data = response.json()
    assert len(data["completed"]) == 0
    assert len(data["errors"]) == 1


@pytest.mark.asyncio
async def test_batch_complete_wrong_status(client: AsyncClient):
    """POST /packets/batch/complete returns error for packets in wrong status."""
    # Create a packet but don't claim it (status=created, can't go directly to completed)
    resp = await client.post("/api/v1/packets", json=_minimal_payload())
    assert resp.status_code == 201
    pkt_id = resp.json()["id"]

    response = await client.post("/api/v1/packets/batch/complete", json={
        "packet_ids": [pkt_id],
    })
    assert response.status_code == 200

    data = response.json()
    assert len(data["completed"]) == 0
    assert len(data["errors"]) == 1
    assert "Cannot complete" in data["errors"][0]["error"]
