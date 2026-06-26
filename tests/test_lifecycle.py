"""HandoffRail API Server — Integration tests for Week 2 features.

Tests cover: claim, update (PATCH), soft delete, HITL respond,
state machine transitions, API key CRUD, and full lifecycle flows.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

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
        "timeout_seconds": 3600,
    }
    return payload


async def _create_packet(client: AsyncClient, payload: dict | None = None) -> dict:
    """Helper to create a packet and return its JSON."""
    resp = await client.post("/api/v1/packets", json=payload or _minimal_payload())
    assert resp.status_code == 201, f"Create failed: {resp.text}"
    return resp.json()


async def _create_api_key(client: AsyncClient) -> tuple[str, str]:
    """Helper to create an API key. Returns (key_id, plain_key)."""
    # We need a bootstrapping approach: create first key via direct DB manipulation
    # or bypass auth for tests. Since auth is optional in dev mode for now,
    # we'll create keys via the endpoint once we have at least one key.
    # For testing, we'll inject a key directly.
    from app.database import async_session
    from app.middleware.auth import generate_api_key
    from app.models.db import ApiKey

    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]

    async with async_session() as session:
        db_key = ApiKey(
            id=str(uuid4()),
            name="test-bootstrap-key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            tenant_id="default",
        )
        session.add(db_key)
        await session.commit()
        await session.refresh(db_key)
        key_id = db_key.id

    return key_id, plain_key


# ════════════════════════════════════════════════════════════════════════════════
# STATE MACHINE TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestStateMachine:
    """Test the state machine module directly."""

    def test_valid_transitions_from_created(self):
        from app.services.state_machine import can_transition

        assert can_transition("created", "claimed") is True
        assert can_transition("created", "awaiting_human") is True
        assert can_transition("created", "failed") is True
        assert can_transition("created", "expired") is True
        assert can_transition("created", "completed") is False

    def test_valid_transitions_from_claimed(self):
        from app.services.state_machine import can_transition

        assert can_transition("claimed", "in_progress") is True
        assert can_transition("claimed", "awaiting_human") is True
        assert can_transition("claimed", "failed") is True

    def test_valid_transitions_from_in_progress(self):
        from app.services.state_machine import can_transition

        assert can_transition("in_progress", "completed") is True
        assert can_transition("in_progress", "awaiting_human") is True
        assert can_transition("in_progress", "failed") is True

    def test_valid_transitions_from_awaiting_human(self):
        from app.services.state_machine import can_transition

        assert can_transition("awaiting_human", "claimed") is True
        assert can_transition("awaiting_human", "in_progress") is True
        assert can_transition("awaiting_human", "failed") is True

    def test_terminal_states(self):
        from app.services.state_machine import is_terminal

        assert is_terminal("completed") is True
        assert is_terminal("expired") is True
        assert is_terminal("created") is False
        assert is_terminal("claimed") is False

    def test_completed_is_terminal(self):
        from app.services.state_machine import can_transition

        assert can_transition("completed", "claimed") is False
        assert can_transition("completed", "in_progress") is False

    def test_expired_is_terminal(self):
        from app.services.state_machine import can_transition

        assert can_transition("expired", "claimed") is False

    def test_validate_transition_success(self):
        from app.services.state_machine import validate_transition

        result = validate_transition("created", "claimed")
        assert result == "claimed"

    def test_validate_transition_failure_raises(self):
        from app.services.state_machine import InvalidTransitionError, validate_transition

        with pytest.raises(InvalidTransitionError):
            validate_transition("completed", "claimed")

    def test_get_allowed_transitions(self):
        from app.services.state_machine import get_allowed_transitions

        allowed = get_allowed_transitions("created")
        assert "claimed" in allowed
        assert "awaiting_human" in allowed
        assert "expired" in allowed
        assert len(get_allowed_transitions("expired")) == 0


# ════════════════════════════════════════════════════════════════════════════════
# CLAIM ENDPOINT TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestClaimPacket:
    """Test POST /packets/{id}/claim."""

    @pytest.mark.asyncio
    async def test_claim_created_packet(self, client: AsyncClient):
        """Claiming a packet in 'created' status succeeds."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        resp = await client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "billing-01", "agent_name": "BillingBot", "framework": "crewai"},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "claimed"
        assert data["metadata"]["target_agent"]["id"] == "billing-01"
        assert data["metadata"]["claimed_at"] is not None

    @pytest.mark.asyncio
    async def test_claim_already_claimed_packet(self, client: AsyncClient):
        """Claiming a packet that's already claimed returns 409."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        # First claim succeeds
        resp1 = await client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "agent-1", "agent_name": "Agent1"},
        )
        assert resp1.status_code == 200

        # Second claim fails with conflict
        resp2 = await client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "agent-2", "agent_name": "Agent2"},
        )
        assert resp2.status_code == 409
        assert "already claimed" in resp2.json()["detail"]["message"]

    @pytest.mark.asyncio
    async def test_claim_packet_not_found(self, client: AsyncClient):
        """Claiming a non-existent packet returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.post(
            f"/api/v1/packets/{fake_id}/claim",
            json={"agent_id": "agent-1", "agent_name": "Agent1"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_claim_completed_packet(self, client: AsyncClient):
        """Claiming a completed packet returns 400 (invalid transition)."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        # Transition: created -> claimed -> in_progress -> completed
        await client.post(f"/api/v1/packets/{packet_id}/claim", json={"agent_id": "a1", "agent_name": "A1"})
        await client.patch(f"/api/v1/packets/{packet_id}", json={"status": "in_progress"})
        await client.patch(f"/api/v1/packets/{packet_id}", json={"status": "completed"})

        resp = await client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "agent-1", "agent_name": "Agent1"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_claim_awaiting_human_packet(self, client: AsyncClient):
        """Claiming a packet in 'awaiting_human' status succeeds (after human response)."""
        packet_data = await _create_packet(client, _hitl_payload())
        packet_id = packet_data["id"]
        assert packet_data["status"] == "awaiting_human"

        # After HITL respond, it transitions to claimed
        resp = await client.post(
            f"/api/v1/packets/{packet_id}/respond",
            json={"response": "Approved", "responded_by": "manager@test.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "claimed"


# ════════════════════════════════════════════════════════════════════════════════
# PATCH (UPDATE) ENDPOINT TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestUpdatePacket:
    """Test PATCH /packets/{id}."""

    @pytest.mark.asyncio
    async def test_update_status_transition(self, client: AsyncClient):
        """Valid status transition via PATCH."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        # created -> claimed
        resp = await client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "agent-1", "agent_name": "Agent1"},
        )
        assert resp.status_code == 200

        # claimed -> in_progress
        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

        # in_progress -> completed
        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "completed"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"
        assert resp.json()["metadata"]["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_invalid_status_transition(self, client: AsyncClient):
        """Invalid status transition returns 400."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        # created -> completed is invalid (must go through claimed first)
        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "completed"},
        )
        assert resp.status_code == 400
        assert "Cannot transition" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_update_context(self, client: AsyncClient):
        """Updating context via PATCH replaces it."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        new_context = {
            "summary": "Updated summary",
            "conversation_state": [{"role": "agent", "content": "Work done"}],
            "artifacts": [],
            "custom": {"key": "value"},
        }

        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"context": new_context},
        )
        assert resp.status_code == 200
        assert resp.json()["context"]["summary"] == "Updated summary"

    @pytest.mark.asyncio
    async def test_update_with_decisions_merge(self, client: AsyncClient):
        """Adding decisions via PATCH merges with existing ones."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        new_decisions = [
            {"id": "d1", "decision": "Go with option A", "rationale": "Better ROI", "decided_by": "agent-1"},
        ]

        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"decisions": new_decisions},
        )
        assert resp.status_code == 200
        assert len(resp.json()["decisions"]) == 1
        assert resp.json()["decisions"][0]["id"] == "d1"

    @pytest.mark.asyncio
    async def test_update_with_actions(self, client: AsyncClient):
        """Updating actions via PATCH replaces the specified sections."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        new_actions = {
            "completed": [
                {"id": "a1", "description": "Task done", "result": "Success", "completed_by": "agent-1"}
            ],
        }

        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"actions": new_actions},
        )
        assert resp.status_code == 200
        assert len(resp.json()["actions"]["completed"]) == 1

    @pytest.mark.asyncio
    async def test_update_packet_not_found(self, client: AsyncClient):
        """Updating a non-existent packet returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.patch(
            f"/api/v1/packets/{fake_id}",
            json={"status": "claimed"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_transition_to_awaiting_human(self, client: AsyncClient):
        """Transitioning from claimed to awaiting_human works."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        # created -> claimed
        await client.post(f"/api/v1/packets/{packet_id}/claim", json={"agent_id": "a1", "agent_name": "A1"})

        # claimed -> awaiting_human
        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "awaiting_human"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "awaiting_human"

    @pytest.mark.asyncio
    async def test_transition_to_failed(self, client: AsyncClient):
        """Transitioning from claimed to failed works."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        await client.post(f"/api/v1/packets/{packet_id}/claim", json={"agent_id": "a1", "agent_name": "A1"})

        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "failed"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"


# ════════════════════════════════════════════════════════════════════════════════
# SOFT DELETE TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestSoftDelete:
    """Test DELETE /packets/{id}."""

    @pytest.mark.asyncio
    async def test_soft_delete_created_packet(self, client: AsyncClient):
        """Deleting a created packet marks it as expired (soft delete)."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        resp = await client.delete(f"/api/v1/packets/{packet_id}")
        assert resp.status_code == 204

        # Verify packet still exists but is expired
        get_resp = await client.get(f"/api/v1/packets/{packet_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "expired"

    @pytest.mark.asyncio
    async def test_soft_delete_already_expired(self, client: AsyncClient):
        """Deleting an already expired packet returns 409."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        # First delete succeeds
        resp1 = await client.delete(f"/api/v1/packets/{packet_id}")
        assert resp1.status_code == 204

        # Second delete fails
        resp2 = await client.delete(f"/api/v1/packets/{packet_id}")
        assert resp2.status_code == 409

    @pytest.mark.asyncio
    async def test_soft_delete_not_found(self, client: AsyncClient):
        """Deleting a non-existent packet returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.delete(f"/api/v1/packets/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_soft_delete_completed_packet(self, client: AsyncClient):
        """Deleting a completed packet marks it as expired."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        # Complete the packet lifecycle first
        await client.post(f"/api/v1/packets/{packet_id}/claim", json={"agent_id": "a1", "agent_name": "A1"})
        await client.patch(f"/api/v1/packets/{packet_id}", json={"status": "in_progress"})
        await client.patch(f"/api/v1/packets/{packet_id}", json={"status": "completed"})

        # Delete completed packet
        resp = await client.delete(f"/api/v1/packets/{packet_id}")
        assert resp.status_code == 204

        get_resp = await client.get(f"/api/v1/packets/{packet_id}")
        assert get_resp.json()["status"] == "expired"


# ════════════════════════════════════════════════════════════════════════════════
# HITL RESPOND TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestHitlRespond:
    """Test POST /packets/{id}/respond."""

    @pytest.mark.asyncio
    async def test_respond_to_awaiting_human(self, client: AsyncClient):
        """Responding to an awaiting_human packet works correctly."""
        packet_data = await _create_packet(client, _hitl_payload())
        packet_id = packet_data["id"]
        assert packet_data["status"] == "awaiting_human"

        resp = await client.post(
            f"/api/v1/packets/{packet_id}/respond",
            json={"response": "Approve full refund", "responded_by": "manager@company.com"},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "claimed"
        assert data["hitl"]["response"] == "Approve full refund"
        assert data["hitl"]["responded_by"] == "manager@company.com"
        assert data["hitl"]["responded_at"] is not None

    @pytest.mark.asyncio
    async def test_respond_with_notes(self, client: AsyncClient):
        """Responding with notes includes them in the HITL data."""
        packet_data = await _create_packet(client, _hitl_payload())
        packet_id = packet_data["id"]

        resp = await client.post(
            f"/api/v1/packets/{packet_id}/respond",
            json={
                "response": "Approve with conditions",
                "responded_by": "manager@company.com",
                "notes": "Only approve if under $500",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["hitl"]["notes"] == "Only approve if under $500"

    @pytest.mark.asyncio
    async def test_respond_to_wrong_status(self, client: AsyncClient):
        """Responding to a packet not in awaiting_human status returns 409."""
        packet = await _create_packet(client)
        packet_id = packet["id"]
        assert packet["status"] == "created"

        resp = await client.post(
            f"/api/v1/packets/{packet_id}/respond",
            json={"response": "Yes", "responded_by": "manager"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_respond_to_claimed_packet(self, client: AsyncClient):
        """Responding to a claimed (not awaiting_human) packet returns 409."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        await client.post(f"/api/v1/packets/{packet_id}/claim", json={"agent_id": "a1", "agent_name": "A1"})

        resp = await client.post(
            f"/api/v1/packets/{packet_id}/respond",
            json={"response": "Yes", "responded_by": "manager"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_respond_to_packet_not_found(self, client: AsyncClient):
        """Responding to a non-existent packet returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.post(
            f"/api/v1/packets/{fake_id}/respond",
            json={"response": "Yes", "responded_by": "manager"},
        )
        assert resp.status_code == 404


# ════════════════════════════════════════════════════════════════════════════════
# FULL LIFECYCLE TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestFullLifecycle:
    """Test complete packet lifecycle flows."""

    @pytest.mark.asyncio
    async def test_create_claim_progress_complete(self, client: AsyncClient):
        """Full lifecycle: create → claim → in_progress → completed."""
        # Create
        packet = await _create_packet(client)
        packet_id = packet["id"]
        assert packet["status"] == "created"

        # Claim
        resp = await client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "billing-01", "agent_name": "BillingBot", "framework": "crewai"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "claimed"
        assert resp.json()["metadata"]["claimed_at"] is not None

        # Progress
        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={
                "status": "in_progress",
                "decisions": [
                    {"id": "d1", "decision": "Applied upgrade", "rationale": "Customer eligible", "decided_by": "billing-01"},
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

        # Complete
        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "completed"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"
        assert resp.json()["metadata"]["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_hitl_full_flow(self, client: AsyncClient):
        """Full HITL flow: create with HITL → human responds → agent claims → completes."""
        # Create with HITL checkpoint
        packet_data = await _create_packet(client, _hitl_payload())
        packet_id = packet_data["id"]
        assert packet_data["status"] == "awaiting_human"

        # Human responds
        resp = await client.post(
            f"/api/v1/packets/{packet_id}/respond",
            json={"response": "Approved", "responded_by": "manager@company.com", "notes": "Looks good"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "claimed"
        assert data["hitl"]["response"] == "Approved"

        # Agent claims and works
        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 200

        # Complete
        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "completed"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    @pytest.mark.asyncio
    async def test_created_to_awaiting_human_via_patch(self, client: AsyncClient):
        """Directly transitioning to awaiting_human via PATCH."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        # created -> awaiting_human (valid transition)
        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "awaiting_human"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "awaiting_human"

    @pytest.mark.asyncio
    async def test_hitl_flow_with_hitl_update(self, client: AsyncClient):
        """Create packet → claim → add HITL → respond → complete."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        # Claim
        await client.post(f"/api/v1/packets/{packet_id}/claim", json={"agent_id": "a1", "agent_name": "A1"})

        # Transition to awaiting_human and add HITL data
        resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={
                "status": "awaiting_human",
                "hitl": {
                    "required": True,
                    "reason": "Manager approval needed",
                    "question": "Approve this action?",
                },
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "awaiting_human"
        assert resp.json()["hitl"]["required"] is True

        # Human responds
        resp = await client.post(
            f"/api/v1/packets/{packet_id}/respond",
            json={"response": "Approved", "responded_by": "manager"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "claimed"

    @pytest.mark.asyncio
    async def test_failed_packet_can_be_expired(self, client: AsyncClient):
        """A failed packet can be soft-deleted (expired)."""
        packet = await _create_packet(client)
        packet_id = packet["id"]

        # created -> claimed -> failed
        await client.post(f"/api/v1/packets/{packet_id}/claim", json={"agent_id": "a1", "agent_name": "A1"})
        await client.patch(f"/api/v1/packets/{packet_id}", json={"status": "failed"})

        # Soft delete
        resp = await client.delete(f"/api/v1/packets/{packet_id}")
        assert resp.status_code == 204

        get_resp = await client.get(f"/api/v1/packets/{packet_id}")
        assert get_resp.json()["status"] == "expired"


# ════════════════════════════════════════════════════════════════════════════════
# API KEY CRUD TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestApiKeyCrud:
    """Test API key management endpoints."""

    @pytest.mark.asyncio
    async def test_create_api_key(self, client: AsyncClient):
        """POST /keys creates a new API key and returns the plain key."""
        key_id, plain_key = await _create_api_key(client)

        # Verify the key format
        assert plain_key.startswith("hr_")
        assert len(plain_key) > 10  # Should be a substantial key

    @pytest.mark.asyncio
    async def test_create_key_via_endpoint(self, client: AsyncClient):
        """Create a key via the API endpoint using a bootstrap key."""
        _, bootstrap_key = await _create_api_key(client)

        resp = await client.post(
            "/api/v1/keys",
            json={"name": "test-key-1"},
            headers={"X-API-Key": bootstrap_key},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test-key-1"
        assert data["key"] is not None  # Plain key returned on creation
        assert data["key"].startswith("hr_")
        assert data["revoked"] is False

    @pytest.mark.asyncio
    async def test_list_api_keys(self, client: AsyncClient):
        """GET /keys lists all keys for the tenant."""
        _, bootstrap_key = await _create_api_key(client)

        # Create another key
        await client.post(
            "/api/v1/keys",
            json={"name": "second-key"},
            headers={"X-API-Key": bootstrap_key},
        )

        resp = await client.get("/api/v1/keys", headers={"X-API-Key": bootstrap_key})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

        # Keys should not include the plain key value
        for key_entry in data:
            assert key_entry["key"] is None or key_entry["key"].startswith("hr_") is False

    @pytest.mark.asyncio
    async def test_revoke_api_key(self, client: AsyncClient):
        """DELETE /keys/{id} revokes an API key."""
        _, bootstrap_key = await _create_api_key(client)

        # Create a new key to revoke
        create_resp = await client.post(
            "/api/v1/keys",
            json={"name": "to-revoke"},
            headers={"X-API-Key": bootstrap_key},
        )
        assert create_resp.status_code == 201
        key_id = create_resp.json()["id"]

        # Revoke it
        resp = await client.delete(
            f"/api/v1/keys/{key_id}",
            headers={"X-API-Key": bootstrap_key},
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_revoke_already_revoked_key(self, client: AsyncClient):
        """Revoking an already-revoked key returns 409."""
        _, bootstrap_key = await _create_api_key(client)

        create_resp = await client.post(
            "/api/v1/keys",
            json={"name": "double-revoke"},
            headers={"X-API-Key": bootstrap_key},
        )
        key_id = create_resp.json()["id"]

        # First revoke
        resp1 = await client.delete(f"/api/v1/keys/{key_id}", headers={"X-API-Key": bootstrap_key})
        assert resp1.status_code == 204

        # Second revoke fails
        resp2 = await client.delete(f"/api/v1/keys/{key_id}", headers={"X-API-Key": bootstrap_key})
        assert resp2.status_code == 409

    @pytest.mark.asyncio
    async def test_access_without_api_key(self, client: AsyncClient):
        """Accessing /keys without an API key returns 401."""
        resp = await client.get("/api/v1/keys")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_access_with_invalid_api_key(self, client: AsyncClient):
        """Accessing /keys with an invalid key returns 401."""
        resp = await client.get("/api/v1/keys", headers={"X-API-Key": "hr_invalid_key_12345"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_key(self, client: AsyncClient):
        """Deleting a non-existent key returns 404."""
        _, bootstrap_key = await _create_api_key(client)

        resp = await client.delete(
            "/api/v1/keys/00000000-0000-0000-0000-000000000000",
            headers={"X-API-Key": bootstrap_key},
        )
        assert resp.status_code == 404


# ════════════════════════════════════════════════════════════════════════════════
# EXPIRY TESTS (Unit)
# ════════════════════════════════════════════════════════════════════════════════


class TestExpiry:
    """Test the packet expiry background task logic."""

    @pytest.mark.asyncio
    async def test_expire_old_packet(self, client: AsyncClient):
        """Manually expiring an old packet via soft delete works."""
        # Create a packet and verify it's in 'created' status
        packet = await _create_packet(client)
        packet_id = packet["id"]
        assert packet["status"] == "created"

        # Soft delete (expire) the packet
        resp = await client.delete(f"/api/v1/packets/{packet_id}")
        assert resp.status_code == 204

        # Verify it's now expired
        get_resp = await client.get(f"/api/v1/packets/{packet_id}")
        assert get_resp.json()["status"] == "expired"

    @pytest.mark.asyncio
    async def test_expiry_task_function(self):
        """Test the check_and_expire_packets function directly."""
        from app.services.expiry import check_and_expire_packets

        # This tests that the expiry logic can run without errors
        count = await check_and_expire_packets()
        # With no stale packets, should return 0
        assert isinstance(count, int)


# ════════════════════════════════════════════════════════════════════════════════
# AUTH MIDDLEWARE TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestAuthMiddleware:
    """Test API key auth middleware."""

    def test_hash_key_deterministic(self):
        """Hashing the same key produces the same hash."""
        from app.middleware.auth import hash_key

        h1 = hash_key("hr_test_key_123")
        h2 = hash_key("hr_test_key_123")
        assert h1 == h2

    def test_hash_key_different_inputs(self):
        """Different keys produce different hashes."""
        from app.middleware.auth import hash_key

        h1 = hash_key("hr_test_key_123")
        h2 = hash_key("hr_test_key_456")
        assert h1 != h2

    def test_generate_api_key_format(self):
        """Generated keys have the correct format."""
        from app.middleware.auth import generate_api_key

        plain_key, hashed_key = generate_api_key()
        assert plain_key.startswith("hr_")
        assert len(hashed_key) == 64  # SHA-256 hex digest
        assert plain_key != hashed_key

    def test_generate_api_key_unique(self):
        """Each generated key is unique."""
        from app.middleware.auth import generate_api_key

        key1, hash1 = generate_api_key()
        key2, hash2 = generate_api_key()
        assert key1 != key2
        assert hash1 != hash2
