"""Tests for the full-text search endpoint."""

import pytest
from httpx import AsyncClient


def _make_packet(summary: str, priority: str = "normal") -> dict:
    """Create a minimal packet payload with a given summary."""
    return {
        "metadata": {
            "source_agent": {"id": "agent-1", "name": "Agent One"},
            "target_agent": {"id": "agent-2", "name": "Agent Two"},
            "priority": priority,
        },
        "context": {"summary": summary},
        "decisions": [],
        "actions": {"pending": [], "completed": [], "failed": []},
        "dependencies": [],
    }


@pytest.mark.asyncio
class TestSearch:
    """Tests for GET /api/v1/packets/search."""

    async def test_search_finds_by_summary(self, client: AsyncClient):
        """Search finds packets by summary content."""
        # Create packets with distinct summaries
        resp1 = await client.post("/api/v1/packets", json=_make_packet("billing invoice processing"))
        assert resp1.status_code == 201
        resp2 = await client.post("/api/v1/packets", json=_make_packet("user authentication flow"))
        assert resp2.status_code == 201

        # Search for "billing"
        resp = await client.get("/api/v1/packets/search", params={"q": "billing"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        summaries = [p["context"]["summary"] for p in data["packets"]]
        assert any("billing" in s for s in summaries)

    async def test_search_no_results(self, client: AsyncClient):
        """Search with non-matching query returns empty results."""
        await client.post("/api/v1/packets", json=_make_packet("billing invoice processing"))

        resp = await client.get("/api/v1/packets/search", params={"q": "xyznonexistent"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["packets"] == []

    async def test_search_empty_query_returns_422(self, client: AsyncClient):
        """Empty query returns 422 (validation error)."""
        resp = await client.get("/api/v1/packets/search", params={"q": ""})
        assert resp.status_code == 422

    async def test_search_short_query_returns_422(self, client: AsyncClient):
        """Query shorter than 2 characters returns 422 (validation error)."""
        resp = await client.get("/api/v1/packets/search", params={"q": "a"})
        assert resp.status_code == 422

    async def test_search_with_status_filter(self, client: AsyncClient):
        """Search with status filter only returns matching packets."""
        await client.post("/api/v1/packets", json=_make_packet("billing invoice processing"))

        resp = await client.get(
            "/api/v1/packets/search",
            params={"q": "billing", "status": "completed"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # No packets should be completed yet
        assert data["total"] == 0

    async def test_search_fts_sync_after_update(self, client: AsyncClient):
        """FTS table stays in sync after packet update."""
        # Create a packet
        create_resp = await client.post(
            "/api/v1/packets",
            json=_make_packet("original summary text"),
        )
        assert create_resp.status_code == 201
        packet_id = create_resp.json()["id"]

        # Search for "original" — should find it
        resp = await client.get("/api/v1/packets/search", params={"q": "original"})
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

        # Update the packet's context with a new summary
        update_resp = await client.patch(
            f"/api/v1/packets/{packet_id}",
            json={"context": {"summary": "completely different content"}},
        )
        assert update_resp.status_code == 200

        # Search for "original" — should not find the updated packet
        resp = await client.get("/api/v1/packets/search", params={"q": "original"})
        assert resp.status_code == 200
        data = resp.json()
        packet_ids = [p["id"] for p in data["packets"]]
        assert packet_id not in packet_ids

        # Search for "completely different" — should find it now
        resp = await client.get("/api/v1/packets/search", params={"q": "completely"})
        assert resp.status_code == 200
        data = resp.json()
        packet_ids = [p["id"] for p in data["packets"]]
        assert packet_id in packet_ids

    async def test_search_fts_sync_after_delete(self, client: AsyncClient):
        """FTS table stays in sync after packet soft-delete (status changes to expired)."""
        create_resp = await client.post(
            "/api/v1/packets",
            json=_make_packet("deletable searchable content"),
        )
        assert create_resp.status_code == 201
        packet_id = create_resp.json()["id"]

        # Should find it
        resp = await client.get("/api/v1/packets/search", params={"q": "deletable"})
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

        # Soft-delete the packet (sets status to expired)
        del_resp = await client.delete(f"/api/v1/packets/{packet_id}")
        assert del_resp.status_code == 204

        # Should still find it in FTS, but filter by status=expired to verify it's expired
        resp = await client.get(
            "/api/v1/packets/search",
            params={"q": "deletable", "status": "expired"},
        )
        assert resp.status_code == 200
        data = resp.json()
        packet_ids = [p["id"] for p in data["packets"]]
        assert packet_id in packet_ids

        # Search without status filter also finds it (FTS entry still exists)
        # but search with status=created should NOT find it
        resp = await client.get(
            "/api/v1/packets/search",
            params={"q": "deletable", "status": "created"},
        )
        assert resp.status_code == 200
        data = resp.json()
        packet_ids = [p["id"] for p in data["packets"]]
        assert packet_id not in packet_ids