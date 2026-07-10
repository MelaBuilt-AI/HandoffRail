"""Tests for multi-tenant isolation and tenant management.

Test categories:
1. Tenant isolation: create packets with different API keys (different tenants),
   verify each can only see their own.
2. Tenant management CRUD: create/read/update/delete tenants (as admin).
3. Cross-tenant access denial: try to access one tenant's data with another
   tenant's key.
4. API key tenant scoping: admin-only cross-tenant key creation, tenant-scoped
   revoke/rotate.
5. Admin-only endpoints: verify non-admin keys can't manage tenants.
"""

from __future__ import annotations

from uuid import uuid4

import pytest_asyncio
from app.database import async_session
from app.middleware.auth import generate_api_key
from app.models.db import ApiKey
from httpx import AsyncClient


@pytest_asyncio.fixture
async def limited_client(admin_client: AsyncClient, setup_db, client) -> AsyncClient:
    """Create a client with a writer-level API key (limited permissions).

    Uses the standard ``client`` fixture's app (``_test_app`` from conftest)
    by creating the writer key directly in the database.
    """
    # Create the writer key directly in the database
    plain_key, key_hash = generate_api_key()
    key_prefix = plain_key[:8]

    async with async_session() as session:
        db_key = ApiKey(
            id=str(uuid4()),
            name="limited-key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            tenant_id="default",
            role="writer",
        )
        session.add(db_key)
        await session.commit()

    # Use the same app as the client fixture by borrowing its transport
    transport = client._transport
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": plain_key},
    ) as ac:
        yield ac


class TestTenantIsolation:
    """Packets created in one tenant must not be visible in another tenant."""

    async def _create_packet(self, client, source_agent: str = "test-agent") -> dict:
        """Helper: create a packet and return the response."""
        response = await client.post(
            "/api/v1/packets",
            json={
                "metadata": {
                    "source_agent": {"id": source_agent, "name": "Test Agent"},
                    "target_agent": {"id": "target-agent", "name": "Target Agent"},
                },
                "context": {
                    "summary": "Test handoff for tenant isolation",
                },
            },
        )
        assert response.status_code == 201, f"Create failed: {response.text}"
        return response.json()

    async def test_packet_isolation_default_vs_tenant2(self, client, tenant2_client):
        """Tenant 1 and Tenant 2 should not see each other's packets."""
        # Create a packet in default tenant
        p1 = await self._create_packet(client)
        packet_id = p1["id"]

        # Default tenant can see its own packet
        response = await client.get(f"/api/v1/packets/{packet_id}")
        assert response.status_code == 200

        # Tenant 2 cannot see the default tenant's packet
        response = await tenant2_client.get(f"/api/v1/packets/{packet_id}")
        assert response.status_code == 404, "Cross-tenant access should 404"

    async def test_list_isolation(self, client, tenant2_client):
        """List endpoints should only show packets for the authenticated tenant."""
        # Create a packet in default tenant
        await self._create_packet(client)

        # Create a packet in tenant2
        await self._create_packet(tenant2_client, source_agent="tenant2-agent")

        # Default tenant list — should see only 1 packet
        response = await client.get("/api/v1/packets")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1, f"Expected 1 packet for default tenant, got {data['total']}"

        # Tenant 2 list — should see only 1 packet
        response = await tenant2_client.get("/api/v1/packets")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1, f"Expected 1 packet for tenant2, got {data['total']}"

    async def test_awaiting_isolation(self, client, tenant2_client):
        """Awaiting-human endpoint should be tenant-scoped."""
        # Create a packet with HITL in default tenant
        response = await client.post(
            "/api/v1/packets",
            json={
                "metadata": {
                    "source_agent": {"id": "agent-a", "name": "Agent A"},
                    "target_agent": {"id": "agent-b", "name": "Agent B"},
                },
                "context": {"summary": "HITL test"},
                "hitl": {"required": True, "reason": "Need approval"},
            },
        )
        assert response.status_code == 201

        # Default tenant sees 1 awaiting
        response = await client.get("/api/v1/packets/awaiting")
        assert response.status_code == 200
        assert response.json()["total"] == 1

        # Tenant 2 sees 0 awaiting
        response = await tenant2_client.get("/api/v1/packets/awaiting")
        assert response.status_code == 200
        assert response.json()["total"] == 0

    async def test_search_isolation(self, client, tenant2_client):
        """Full-text search should be tenant-scoped."""
        # Create a packet with distinctive summary in default tenant
        await client.post(
            "/api/v1/packets",
            json={
                "metadata": {
                    "source_agent": {"id": "agent-src", "name": "Source"},
                    "target_agent": {"id": "agent-tgt", "name": "Target"},
                },
                "context": {"summary": "UNIQUE_SEARCH_TERM_FOR_TESTING"},
            },
        )

        # Default tenant can find it
        response = await client.get(
            "/api/v1/packets/search",
            params={"q": "UNIQUE_SEARCH_TERM_FOR_TESTING"},
        )
        assert response.status_code == 200
        assert response.json()["total"] >= 1

        # Tenant 2 cannot find it
        response = await tenant2_client.get(
            "/api/v1/packets/search",
            params={"q": "UNIQUE_SEARCH_TERM_FOR_TESTING"},
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0

    async def test_claim_isolation(self, client, tenant2_client):
        """Cannot claim a packet from another tenant."""
        # Create packet in default tenant
        p1 = await self._create_packet(client)
        packet_id = p1["id"]

        # Tenant 2 cannot claim it
        response = await tenant2_client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "tenant2-agent", "agent_name": "Tenant2 Agent"},
        )
        assert response.status_code == 404, "Cross-tenant claim should 404"

    async def test_update_isolation(self, client, tenant2_client):
        """Cannot update a packet from another tenant."""
        p1 = await self._create_packet(client)
        packet_id = p1["id"]

        response = await tenant2_client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"status": "completed"},
        )
        assert response.status_code == 404

    async def test_delete_isolation(self, client, tenant2_client):
        """Cannot soft-delete a packet from another tenant."""
        p1 = await self._create_packet(client)
        packet_id = p1["id"]

        response = await tenant2_client.delete(f"/api/v1/packets/{packet_id}")
        assert response.status_code == 404

    async def test_chain_isolation(self, client, tenant2_client):
        """Cannot chain from a packet in another tenant."""
        p1 = await self._create_packet(client)
        packet_id = p1["id"]

        response = await tenant2_client.post(
            f"/api/v1/packets/{packet_id}/chain",
            json={
                "metadata": {
                    "source_agent": {"id": "agent-c", "name": "Agent C"},
                    "target_agent": {"id": "agent-d", "name": "Agent D"},
                },
                "context": {"summary": "Chain test"},
            },
        )
        assert response.status_code == 404

    async def test_history_isolation(self, client, tenant2_client):
        """Packet history should be tenant-scoped (prevent info leak)."""
        p1 = await self._create_packet(client)
        packet_id = p1["id"]

        # Claim to generate history
        await client.post(
            f"/api/v1/packets/{packet_id}/claim",
            json={"agent_id": "agent-a", "agent_name": "Agent A"},
        )

        # Tenant 2 cannot read history
        response = await tenant2_client.get(f"/api/v1/packets/{packet_id}/history")
        assert response.status_code == 404

    async def test_webhook_isolation(self, client, tenant2_client):
        """Webhooks should be tenant-scoped."""
        # Create webhook in default tenant
        response = await client.post(
            "/api/v1/hooks",
            json={
                "url": "https://example.com/hook1",
                "events": ["packet.created"],
                "secret": "test-secret-12345678",
            },
        )
        assert response.status_code == 201
        webhook_id = response.json()["id"]

        # Default tenant can see it
        response = await client.get("/api/v1/hooks")
        assert response.status_code == 200
        assert len(response.json()) == 1

        # Tenant 2 cannot see it
        response = await tenant2_client.get("/api/v1/hooks")
        assert response.status_code == 200
        assert len(response.json()) == 0

        # Tenant 2 cannot delete it
        response = await tenant2_client.delete(f"/api/v1/hooks/{webhook_id}")
        assert response.status_code == 404

    async def test_audit_isolation(self, client, tenant2_client):
        """Audit log should be tenant-scoped."""
        # Create a packet in default tenant (generates audit event)
        await self._create_packet(client)

        # Default tenant can see audit entries
        response = await client.get("/api/v1/audit")
        assert response.status_code == 200
        assert response.json()["total"] >= 1

        # Tenant 2 sees no audit entries for default tenant's packets
        response = await tenant2_client.get("/api/v1/audit")
        assert response.status_code == 200
        assert response.json()["total"] == 0


class TestTenantManagementCRUD:
    """Tenant management endpoints (admin only) CRUD."""

    async def test_create_tenant(self, admin_client):
        """Admin can create a new tenant."""
        response = await admin_client.post(
            "/api/v1/tenants",
            json={
                "name": "New Test Tenant",
                "tier": "pro",
                "handoffs_per_day": 100,
                "max_api_keys": 10,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Test Tenant"
        assert data["tier"] == "pro"
        assert data["handoffs_per_day"] == 100
        assert data["max_api_keys"] == 10
        assert data["deleted_at"] is None

    async def test_create_tenant_duplicate_name(self, admin_client):
        """Creating a tenant with a duplicate name should fail."""
        await admin_client.post(
            "/api/v1/tenants",
            json={"name": "Unique Tenant", "tier": "free"},
        )
        response = await admin_client.post(
            "/api/v1/tenants",
            json={"name": "Unique Tenant", "tier": "free"},
        )
        assert response.status_code == 409

    async def test_list_tenants(self, admin_client):
        """Admin can list all tenants."""
        await admin_client.post("/api/v1/tenants", json={"name": "Tenant A"})
        await admin_client.post("/api/v1/tenants", json={"name": "Tenant B"})

        response = await admin_client.get("/api/v1/tenants")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2
        names = [t["name"] for t in data]
        assert "Tenant A" in names
        assert "Tenant B" in names

    async def test_get_tenant(self, admin_client):
        """Admin can get tenant details by ID."""
        # Create tenant
        create_resp = await admin_client.post(
            "/api/v1/tenants",
            json={"name": "Get Test Tenant", "tier": "business"},
        )
        tenant_id = create_resp.json()["id"]

        # Get by ID
        response = await admin_client.get(f"/api/v1/tenants/{tenant_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Get Test Tenant"

    async def test_get_tenant_not_found(self, admin_client):
        """Getting a non-existent tenant should 404."""
        response = await admin_client.get("/api/v1/tenants/non-existent-id")
        assert response.status_code == 404

    async def test_update_tenant(self, admin_client):
        """Admin can update a tenant's configuration."""
        create_resp = await admin_client.post(
            "/api/v1/tenants",
            json={"name": "Update Tenant", "tier": "free", "handoffs_per_day": 5},
        )
        tenant_id = create_resp.json()["id"]

        response = await admin_client.patch(
            f"/api/v1/tenants/{tenant_id}",
            json={"name": "Updated Tenant", "tier": "pro", "handoffs_per_day": 200},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Tenant"
        assert data["tier"] == "pro"
        assert data["handoffs_per_day"] == 200

    async def test_delete_tenant(self, admin_client):
        """Admin can soft-delete a tenant."""
        create_resp = await admin_client.post(
            "/api/v1/tenants",
            json={"name": "Delete Tenant"},
        )
        tenant_id = create_resp.json()["id"]

        response = await admin_client.delete(f"/api/v1/tenants/{tenant_id}")
        assert response.status_code == 204

        # Verify it's gone
        response = await admin_client.get(f"/api/v1/tenants/{tenant_id}")
        assert response.status_code == 404

    async def test_list_tenant_keys(self, admin_client, client):
        """Admin can list API keys for a tenant."""
        response = await admin_client.get("/api/v1/tenants/default/keys")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        # The list should include the test key
        key_names = [k["name"] for k in data]
        assert "test" in key_names


class TestCrossTenantAccessDenial:
    """Non-admin users should not access tenant management or cross-tenant resources."""

    async def test_non_admin_cannot_create_tenant(self, limited_client):
        """Regular API key cannot create tenants."""
        response = await limited_client.post(
            "/api/v1/tenants",
            json={"name": "Hacker Tenant"},
        )
        assert response.status_code == 403

    async def test_non_admin_cannot_list_tenants(self, limited_client):
        """Regular API key cannot list tenants."""
        response = await limited_client.get("/api/v1/tenants")
        assert response.status_code == 403

    async def test_non_admin_cannot_get_tenant(self, limited_client):
        """Regular API key cannot get tenant details."""
        response = await limited_client.get("/api/v1/tenants/default")
        assert response.status_code == 403

    async def test_non_admin_cannot_update_tenant(self, limited_client):
        """Regular API key cannot update tenants."""
        response = await limited_client.patch(
            "/api/v1/tenants/default",
            json={"name": "Hacked"},
        )
        assert response.status_code == 403

    async def test_non_admin_cannot_delete_tenant(self, limited_client):
        """Regular API key cannot delete tenants."""
        response = await limited_client.delete("/api/v1/tenants/default")
        assert response.status_code == 403

    async def test_non_admin_cannot_list_tenant_keys(self, limited_client):
        """Regular API key cannot list keys for a tenant."""
        response = await limited_client.get("/api/v1/tenants/default/keys")
        assert response.status_code == 403

    async def test_non_admin_cannot_create_key_for_other_tenant(self, limited_client):
        """Non-admin cannot create an API key for a different tenant."""
        response = await limited_client.post(
            "/api/v1/keys",
            json={"name": "cross-tenant-key", "tenant_id": "other-tenant"},
        )
        assert response.status_code == 403

    async def test_cannot_revoke_other_tenant_key(self, limited_client, tenant2_client):
        """Non-admin cannot revoke a key from another tenant."""
        # Create a key in tenant2
        response = await tenant2_client.post(
            "/api/v1/keys",
            json={"name": "tenant2-key"},
        )
        assert response.status_code == 201
        key_id = response.json()["id"]

        # Try to revoke it from default tenant
        response = await limited_client.delete(f"/api/v1/keys/{key_id}")
        # Should not be found (different tenant, limited access)
        assert response.status_code in (403, 404)

    async def test_cannot_rotate_other_tenant_key(self, limited_client, tenant2_client):
        """Non-admin cannot rotate a key from another tenant."""
        response = await tenant2_client.post(
            "/api/v1/keys",
            json={"name": "tenant2-rotate-key"},
        )
        assert response.status_code == 201
        key_id = response.json()["id"]

        # Try to rotate it from default tenant
        response = await limited_client.post(f"/api/v1/keys/{key_id}/rotate")
        # Should not be found (different tenant, limited access)
        assert response.status_code in (403, 404)

    async def test_dashboard_is_tenant_scoped(self, client, tenant2_client):
        """Dashboard stats should be tenant-scoped."""
        response = await client.get("/api/v1/stats")
        assert response.status_code == 200
        default_stats = response.json()

        response = await tenant2_client.get("/api/v1/stats")
        assert response.status_code == 200
        tenant2_stats = response.json()

        # Both should have 0 packets (no packets created yet)
        assert default_stats["total_packets"] == 0
        assert tenant2_stats["total_packets"] == 0
