"""HandoffRail API Server — RBAC integration tests.

Tests role-based access control enforcement:
  - admin: all operations including key management
  - writer: create/update/claim/complete packets
  - reader: list/get/search only
  - agent: claim/complete packets only (no create)

Creates a separate test app with RBAC middleware enabled for these tests.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Add server dir to Python path so `app` module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from app.database import async_session
from app.main import create_app
from app.middleware.auth import generate_api_key
from app.models.db import ApiKey

# Create a dedicated test app with RBAC middleware ENABLED
_rbac_app = create_app(
    tier_limits={"free": 100000, "pro": 100000, "business": 100000},
    rate_limit_per_minute=100000,
    disable_rbac=False,
)


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
    }


async def _make_admin_key() -> str:
    """Create an admin API key in the database and return the plain key."""
    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]

    async with async_session() as session:
        db_key = ApiKey(
            id=str(uuid4()),
            name="rbac-admin-key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            tenant_id="default",
            tier="business",
            role="admin",
        )
        session.add(db_key)
        await session.commit()
        await session.refresh(db_key)

    return plain_key


async def _make_role_key(role: str, admin_client: AsyncClient) -> str:
    """Create an API key with a specific role using the admin client."""
    resp = await admin_client.post(
        "/api/v1/keys",
        json={"name": f"rbac-{role}-key", "role": role},
    )
    assert resp.status_code == 201, f"Failed to create {role} key: {resp.text}"
    return resp.json()["key"]


# ════════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ════════════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def admin_client() -> AsyncClient:
    """HTTP client with an admin API key (RBAC active)."""
    admin_key = await _make_admin_key()
    transport = ASGITransport(app=_rbac_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": admin_key},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def writer_key(admin_client: AsyncClient) -> str:
    """Create a writer API key."""
    return await _make_role_key("writer", admin_client)


@pytest_asyncio.fixture
async def reader_key(admin_client: AsyncClient) -> str:
    """Create a reader API key."""
    return await _make_role_key("reader", admin_client)


@pytest_asyncio.fixture
async def agent_key(admin_client: AsyncClient) -> str:
    """Create an agent API key."""
    return await _make_role_key("agent", admin_client)


def _make_client(api_key: str) -> AsyncClient:
    """Create an HTTP client with a specific API key using the RBAC-enabled app."""
    transport = ASGITransport(app=_rbac_app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    )


@pytest_asyncio.fixture
async def writer_client(writer_key: str) -> AsyncClient:
    """HTTP client with a writer API key."""
    client = _make_client(writer_key)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def reader_client(reader_key: str) -> AsyncClient:
    """HTTP client with a reader API key."""
    client = _make_client(reader_key)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def agent_client(agent_key: str) -> AsyncClient:
    """HTTP client with an agent API key."""
    client = _make_client(agent_key)
    yield client
    await client.aclose()


# ════════════════════════════════════════════════════════════════════════════════
# ROLE CREATION TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestRoleCreation:
    """Test that API keys can be created with specific roles."""

    @pytest.mark.asyncio
    async def test_create_admin_key(self, admin_client: AsyncClient):
        """Admin can create an admin key."""
        resp = await admin_client.post(
            "/api/v1/keys",
            json={"name": "new-admin", "role": "admin"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "admin"

    @pytest.mark.asyncio
    async def test_create_writer_key(self, admin_client: AsyncClient):
        """Admin can create a writer key."""
        resp = await admin_client.post(
            "/api/v1/keys",
            json={"name": "writer-key", "role": "writer"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "writer"

    @pytest.mark.asyncio
    async def test_create_reader_key(self, admin_client: AsyncClient):
        """Admin can create a reader key."""
        resp = await admin_client.post(
            "/api/v1/keys",
            json={"name": "reader-key", "role": "reader"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "reader"

    @pytest.mark.asyncio
    async def test_create_agent_key(self, admin_client: AsyncClient):
        """Admin can create an agent key."""
        resp = await admin_client.post(
            "/api/v1/keys",
            json={"name": "agent-key", "role": "agent"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "agent"

    @pytest.mark.asyncio
    async def test_default_role_is_admin(self, admin_client: AsyncClient):
        """Creating a key without specifying role defaults to admin."""
        resp = await admin_client.post(
            "/api/v1/keys",
            json={"name": "default-role-key"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "admin"

    @pytest.mark.asyncio
    async def test_invalid_role_rejected(self, admin_client: AsyncClient):
        """Creating a key with an invalid role returns 422."""
        resp = await admin_client.post(
            "/api/v1/keys",
            json={"name": "bad-role", "role": "superadmin"},
        )
        assert resp.status_code == 422


# ════════════════════════════════════════════════════════════════════════════════
# ADMIN ROLE TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestAdminRole:
    """Admin keys can do everything."""

    @pytest.mark.asyncio
    async def test_admin_can_create_packet(self, admin_client: AsyncClient):
        """Admin can create a packet."""
        resp = await admin_client.post("/api/v1/packets", json=_minimal_payload())
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_admin_can_manage_keys(self, admin_client: AsyncClient):
        """Admin can create, list, and revoke keys."""
        resp = await admin_client.post("/api/v1/keys", json={"name": "test-key"})
        assert resp.status_code == 201

        resp = await admin_client.get("/api/v1/keys")
        assert resp.status_code == 200

        key_id = resp.json()[0]["id"]
        resp = await admin_client.delete(f"/api/v1/keys/{key_id}")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_admin_can_search(self, admin_client: AsyncClient):
        """Admin can search packets."""
        resp = await admin_client.get("/api/v1/packets/search?q=test")
        assert resp.status_code == 200


# ════════════════════════════════════════════════════════════════════════════════
# WRITER ROLE TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestWriterRole:
    """Writer keys can create/update/claim/complete packets but not manage keys."""

    @pytest.mark.asyncio
    async def test_writer_can_create_packet(self, writer_client: AsyncClient):
        """Writer can create a packet."""
        resp = await writer_client.post("/api/v1/packets", json=_minimal_payload())
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_writer_can_claim_packet(self, writer_client: AsyncClient):
        """Writer can claim a packet."""
        create_resp = await writer_client.post("/api/v1/packets", json=_minimal_payload())
        packet_id = create_resp.json()["id"]

        resp = await writer_client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "agent-1", "agent_name": "Agent1"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_writer_can_update_packet(self, writer_client: AsyncClient):
        """Writer can update a packet."""
        create_resp = await writer_client.post("/api/v1/packets", json=_minimal_payload())
        packet_id = create_resp.json()["id"]

        await writer_client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "agent-1", "agent_name": "Agent1"},
        )
        resp = await writer_client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_writer_can_delete_packet(self, writer_client: AsyncClient):
        """Writer can soft-delete a packet."""
        create_resp = await writer_client.post("/api/v1/packets", json=_minimal_payload())
        packet_id = create_resp.json()["id"]

        resp = await writer_client.delete(f"/api/v1/packets/{packet_id}")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_writer_cannot_create_key(self, writer_client: AsyncClient):
        """Writer cannot create API keys (returns 403)."""
        resp = await writer_client.post(
            "/api/v1/keys",
            json={"name": "writer-trying-to-create-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_writer_cannot_list_keys(self, writer_client: AsyncClient):
        """Writer cannot list API keys (returns 403)."""
        resp = await writer_client.get("/api/v1/keys")
        assert resp.status_code == 403


# ════════════════════════════════════════════════════════════════════════════════
# READER ROLE TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestReaderRole:
    """Reader keys can only list/get/search packets."""

    @pytest.mark.asyncio
    async def test_reader_can_list_packets(self, admin_client: AsyncClient, reader_client: AsyncClient):
        """Reader can list packets."""
        resp = await admin_client.post("/api/v1/packets", json=_minimal_payload())
        assert resp.status_code == 201

        resp = await reader_client.get("/api/v1/packets")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_reader_can_get_packet(self, admin_client: AsyncClient, reader_client: AsyncClient):
        """Reader can get a single packet."""
        create_resp = await admin_client.post("/api/v1/packets", json=_minimal_payload())
        packet_id = create_resp.json()["id"]

        resp = await reader_client.get(f"/api/v1/packets/{packet_id}")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_reader_can_search(self, reader_client: AsyncClient):
        """Reader can search packets."""
        resp = await reader_client.get("/api/v1/packets/search?q=test")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_reader_cannot_create_packet(self, reader_client: AsyncClient):
        """Reader cannot create a packet (returns 403)."""
        resp = await reader_client.post("/api/v1/packets", json=_minimal_payload())
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_reader_cannot_claim_packet(self, admin_client: AsyncClient, reader_client: AsyncClient):
        """Reader cannot claim a packet (returns 403)."""
        create_resp = await admin_client.post("/api/v1/packets", json=_minimal_payload())
        packet_id = create_resp.json()["id"]

        resp = await reader_client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "agent-1", "agent_name": "Agent1"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_reader_cannot_delete_packet(self, admin_client: AsyncClient, reader_client: AsyncClient):
        """Reader cannot soft-delete a packet (returns 403)."""
        create_resp = await admin_client.post("/api/v1/packets", json=_minimal_payload())
        packet_id = create_resp.json()["id"]

        resp = await reader_client.delete(f"/api/v1/packets/{packet_id}")
        assert resp.status_code == 403


# ════════════════════════════════════════════════════════════════════════════════
# AGENT ROLE TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestAgentRole:
    """Agent keys can only claim/complete packets, not create them."""

    @pytest.mark.asyncio
    async def test_agent_cannot_create_packet(self, agent_client: AsyncClient):
        """Agent cannot create a packet (returns 403)."""
        resp = await agent_client.post("/api/v1/packets", json=_minimal_payload())
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_agent_can_claim_packet(self, admin_client: AsyncClient, agent_client: AsyncClient):
        """Agent can claim a packet."""
        create_resp = await admin_client.post("/api/v1/packets", json=_minimal_payload())
        packet_id = create_resp.json()["id"]

        resp = await agent_client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "agent-1", "agent_name": "Agent1"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_agent_can_complete_packet(self, admin_client: AsyncClient, agent_client: AsyncClient):
        """Agent can update a packet's status (complete it)."""
        create_resp = await admin_client.post("/api/v1/packets", json=_minimal_payload())
        packet_id = create_resp.json()["id"]

        await agent_client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "agent-1", "agent_name": "Agent1"},
        )

        resp = await agent_client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "in_progress"},
        )
        assert resp.status_code == 200

        resp = await agent_client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "completed"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_agent_can_respond_hitl(self, admin_client: AsyncClient, agent_client: AsyncClient):
        """Agent can respond to HITL checkpoints."""
        payload = _minimal_payload()
        payload["hitl"] = {
            "required": True,
            "reason": "Needs approval",
            "question": "Proceed?",
        }
        create_resp = await admin_client.post("/api/v1/packets", json=payload)
        packet_id = create_resp.json()["id"]
        assert create_resp.json()["status"] == "awaiting_human"

        resp = await agent_client.post(
            f"/api/v1/packets/{packet_id}/respond",
            json={"response": "Approved", "responded_by": "agent-bot"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_agent_can_list_packets(self, agent_client: AsyncClient):
        """Agent can list packets (for discovering claimable work)."""
        resp = await agent_client.get("/api/v1/packets")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_agent_cannot_delete_packet(self, admin_client: AsyncClient, agent_client: AsyncClient):
        """Agent cannot soft-delete a packet (returns 403)."""
        create_resp = await admin_client.post("/api/v1/packets", json=_minimal_payload())
        packet_id = create_resp.json()["id"]

        resp = await agent_client.delete(f"/api/v1/packets/{packet_id}")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_agent_cannot_manage_keys(self, agent_client: AsyncClient):
        """Agent cannot manage keys (returns 403)."""
        resp = await agent_client.post("/api/v1/keys", json={"name": "key-from-agent"})
        assert resp.status_code == 403

        resp = await agent_client.get("/api/v1/keys")
        assert resp.status_code == 403


# ════════════════════════════════════════════════════════════════════════════════
# ROLE HIERARCHY TESTS
# ════════════════════════════════════════════════════════════════════════════════


class TestRoleHierarchy:
    """Verify that role levels are properly enforced."""

    @pytest.mark.asyncio
    async def test_admin_can_create_keys_with_any_role(self, admin_client: AsyncClient):
        """Admin can create keys with any valid role."""
        for role in ["admin", "writer", "reader", "agent"]:
            resp = await admin_client.post(
                "/api/v1/keys",
                json={"name": f"{role}-test", "role": role},
            )
            assert resp.status_code == 201, f"Failed to create {role} key: {resp.text}"

    @pytest.mark.asyncio
    async def test_writer_cannot_manage_keys(self, writer_client: AsyncClient):
        """Writer cannot manage keys."""
        resp = await writer_client.get("/api/v1/keys")
        assert resp.status_code == 403

        resp = await writer_client.post("/api/v1/keys", json={"name": "another"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_reader_cannot_manage_keys(self, reader_client: AsyncClient):
        """Reader cannot manage keys."""
        resp = await reader_client.get("/api/v1/keys")
        assert resp.status_code == 403
