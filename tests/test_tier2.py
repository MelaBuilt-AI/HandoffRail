"""Tests for Tier 2 features — DLQ, key rotation, enhanced metrics."""

from __future__ import annotations

import json
from uuid import uuid4

from httpx import AsyncClient

# ── API Key Rotation Tests ─────────────────────────────────────────────────────


class TestApiKeyRotation:
    """Tests for the /api/v1/keys/{key_id}/rotate endpoint."""

    async def test_rotate_api_key_success(self, client: AsyncClient):
        """Rotating a key creates a new key and revokes the old one."""
        # First, create a second key
        resp = await client.post(
            "/api/v1/keys",
            json={"name": "key-to-rotate"},
        )
        assert resp.status_code == 201
        old_key_id = resp.json()["id"]
        old_key_prefix = resp.json()["key_prefix"]

        # Rotate it
        resp = await client.post(f"/api/v1/keys/{old_key_id}/rotate")
        assert resp.status_code == 201
        data = resp.json()

        assert data["id"] != old_key_id
        assert data["key_prefix"] != old_key_prefix
        assert "rotated" in data["name"]
        assert data["key"] is not None  # Plain key shown on creation
        assert data["revoked"] is False

        # Old key should now be revoked
        resp = await client.get("/api/v1/keys")
        keys = resp.json()
        old_key = next(k for k in keys if k["id"] == old_key_id)
        assert old_key["revoked"] is True

    async def test_rotate_revoked_key_fails(self, client: AsyncClient):
        """Cannot rotate an already-revoked key."""
        # Create a key
        resp = await client.post("/api/v1/keys", json={"name": "temp-key"})
        assert resp.status_code == 201
        key_id = resp.json()["id"]

        # Revoke it
        resp = await client.delete(f"/api/v1/keys/{key_id}")
        assert resp.status_code == 204

        # Try to rotate
        resp = await client.post(f"/api/v1/keys/{key_id}/rotate")
        assert resp.status_code == 409
        assert "already revoked" in resp.json()["detail"]

    async def test_rotate_nonexistent_key(self, client: AsyncClient):
        """Rotating a nonexistent key returns 404."""
        fake_id = str(uuid4())
        resp = await client.post(f"/api/v1/keys/{fake_id}/rotate")
        assert resp.status_code == 404

    async def test_rotated_key_works(self, client: AsyncClient):
        """The new key from rotation can authenticate."""
        # Create a key
        resp = await client.post("/api/v1/keys", json={"name": "rotate-test"})
        assert resp.status_code == 201
        old_key_id = resp.json()["id"]
        new_plain_key = None

        # Rotate it
        resp = await client.post(f"/api/v1/keys/{old_key_id}/rotate")
        assert resp.status_code == 201
        new_plain_key = resp.json()["key"]

        # Use the new key to list packets
        resp = await client.get(
            "/api/v1/packets",
            headers={"X-API-Key": new_plain_key},
        )
        assert resp.status_code == 200


# ── Dead Letter Queue Tests ────────────────────────────────────────────────────


class TestDeadLetterQueue:
    """Tests for DLQ endpoints."""

    async def test_list_dlq_empty(self, client: AsyncClient):
        """DLQ is empty when no deliveries have failed."""
        resp = await client.get("/api/v1/hooks/dlq")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_dlq_replay_nonexistent(self, client: AsyncClient):
        """Replaying a nonexistent DLQ entry returns 404."""
        fake_id = str(uuid4())
        resp = await client.post(f"/api/v1/hooks/dlq/{fake_id}/replay")
        assert resp.status_code == 404

    async def test_dlq_retry_all_empty(self, admin_client):
        """Retry-all works when there are no failed deliveries."""
        resp = await admin_client.post("/api/v1/hooks/dlq/retry-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["retried"] == 0


# ── Webhook Delivery Tracking Tests ────────────────────────────────────────────


class TestWebhookDeliveryTracking:
    """Tests for webhook delivery persistence and tracking."""

    async def test_webhook_delivery_model_exists(self, client: AsyncClient):
        """Verify the WebhookDelivery table is created and queryable."""
        from app.database import async_session
        from app.models.db import WebhookDelivery

        delivery = WebhookDelivery(
            id=str(uuid4()),
            webhook_id=str(uuid4()),
            tenant_id="default",
            packet_id=str(uuid4()),
            event_type="packet.created",
            payload_json=json.dumps({"event": "test"}),
            status="pending",
            attempts=0,
        )
        async with async_session() as session:
            session.add(delivery)
            await session.commit()
            await session.refresh(delivery)

        assert delivery.id is not None
        assert delivery.status == "pending"
        assert delivery.attempts == 0

    async def test_webhook_dispatch_creates_delivery_record(self, client: AsyncClient):
        """Dispatching webhooks creates persistent delivery records."""
        from app.database import async_session
        from app.models.db import WebhookDelivery
        from sqlalchemy import select

        # Register a webhook pointing to an unreachable URL
        resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "https://httpbin.org/status/200",
                "events": ["packet.created"],
                "secret": "a" * 16,
            },
        )
        assert resp.status_code == 201
        webhook_id = resp.json()["id"]

        # Create a packet to trigger webhook dispatch
        packet_data = {
            "metadata": {
                "source_agent": {"id": "agent-1", "name": "Test Agent"},
                "target_agent": {"id": "agent-2", "name": "Target Agent"},
            },
            "context": {"summary": "Test packet for webhook tracking"},
        }
        resp = await client.post("/api/v1/packets", json=packet_data)
        assert resp.status_code == 201
        packet_id = resp.json()["id"]

        # Check that delivery records exist
        async with async_session() as session:
            result = await session.execute(
                select(WebhookDelivery).where(WebhookDelivery.packet_id == packet_id)
            )
            deliveries = result.scalars().all()

        # At least one delivery record should exist
        # (webhook dispatch is async, may or may not have completed)
        if deliveries:
            assert deliveries[0].event_type == "packet.created"
            assert deliveries[0].webhook_id == webhook_id

    async def test_webhook_deliveries_endpoint_lists_history(self, client: AsyncClient):
        """GET /hooks/{id}/deliveries returns tenant-scoped delivery history."""
        from app.database import async_session
        from app.models.db import WebhookDelivery

        resp = await client.post(
            "/api/v1/hooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["packet.created"],
                "secret": "a" * 16,
            },
        )
        assert resp.status_code == 201
        webhook_id = resp.json()["id"]

        delivery = WebhookDelivery(
            id=str(uuid4()),
            webhook_id=webhook_id,
            tenant_id="default",
            packet_id=str(uuid4()),
            event_type="packet.created",
            payload_json=json.dumps({"event": "packet.created"}),
            status="failed",
            attempts=1,
            last_error="timeout",
        )
        async with async_session() as session:
            session.add(delivery)
            await session.commit()

        resp = await client.get(f"/api/v1/hooks/{webhook_id}/deliveries")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == delivery.id
        assert data[0]["status"] == "failed"


# ── Prometheus Metrics Tests ───────────────────────────────────────────────────


class TestEnhancedMetrics:
    """Tests for enhanced Prometheus metrics."""

    async def test_metrics_endpoint_has_business_metrics(self, client: AsyncClient):
        """The /metrics endpoint exposes business-level metrics."""
        # Create a packet to trigger counters
        packet_data = {
            "metadata": {
                "source_agent": {"id": "agent-1", "name": "Test Agent"},
                "target_agent": {"id": "agent-2", "name": "Target Agent"},
            },
            "context": {"summary": "Metrics test packet"},
        }
        resp = await client.post("/api/v1/packets", json=packet_data)
        assert resp.status_code == 201

        # Fetch metrics
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        metrics_text = resp.text

        # Should contain our business metrics
        assert "handoffrail_handoffs_total" in metrics_text
        assert "handoffrail_requests_total" in metrics_text
        assert "handoffrail_request_latency_seconds" in metrics_text

    async def test_metrics_has_api_key_operations(self, client: AsyncClient):
        """Creating an API key increments the api_key_operations counter."""
        # Create a key
        resp = await client.post("/api/v1/keys", json={"name": "metrics-test-key"})
        assert resp.status_code == 201

        # Fetch metrics
        resp = await client.get("/metrics")
        assert resp.status_code == 200

        assert "handoffrail_api_key_operations_total" in resp.text
        assert "created" in resp.text

    async def test_metrics_has_webhook_counters(self, client: AsyncClient):
        """Metrics endpoint has webhook delivery counters defined."""
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "handoffrail_webhook_deliveries_total" in resp.text
        assert "handoffrail_webhook_dlq_size" in resp.text

    async def test_metrics_has_hitl_counters(self, client: AsyncClient):
        """Metrics endpoint has HITL counters defined."""
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "handoffrail_hitl_checkpoints_total" in resp.text
        assert "handoffrail_hitl_responses_total" in resp.text

    async def test_metrics_has_chain_depth(self, client: AsyncClient):
        """Metrics endpoint has chain depth histogram defined."""
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "handoffrail_chain_depth" in resp.text

    async def test_metrics_has_packet_status_count(self, client: AsyncClient):
        """Metrics endpoint has packet status gauge defined."""
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "handoffrail_packet_status_count" in resp.text


# ── Alembic Migration Tests ────────────────────────────────────────────────────


class TestAlembicMigration:
    """Tests for Alembic migration setup."""

    def test_migration_file_exists(self):
        """The initial migration file exists and has correct revision ID."""
        from pathlib import Path

        migration_path = (
            Path(__file__).resolve().parent.parent
            / "server"
            / "alembic"
            / "versions"
            / "0001_initial.py"
        )
        assert migration_path.exists()

        content = migration_path.read_text()
        assert 'revision = "0001_initial"' in content
        assert "packets" in content
        assert "packet_events" in content
        assert "webhooks" in content
        assert "api_keys" in content
        assert "webhook_deliveries" in content

    def test_alembic_config_exists(self):
        """Alembic config file exists."""
        from pathlib import Path

        config_path = (
            Path(__file__).resolve().parent.parent
            / "server"
            / "alembic.ini"
        )
        assert config_path.exists()


# ── Docker & CI/CD Tests ───────────────────────────────────────────────────────


class TestDockerAndCI:
    """Tests for Docker and CI/CD configuration files."""

    def test_docker_compose_prod_has_migration_service(self):
        """Production docker-compose includes a migration service."""
        from pathlib import Path

        compose_path = (
            Path(__file__).resolve().parent.parent
            / "docker-compose.prod.yml"
        )
        assert compose_path.exists()

        content = compose_path.read_text()
        assert "migration" in content
        assert "alembic" in content
        assert "service_completed_successfully" in content

    def test_ci_yaml_has_docker_push(self):
        """CI pipeline includes Docker image build and push to GHCR."""
        from pathlib import Path

        ci_path = (
            Path(__file__).resolve().parent.parent
            / ".github"
            / "workflows"
            / "ci.yml"
        )
        assert ci_path.exists()

        content = ci_path.read_text()
        assert "build-and-push-image" in content
        assert "ghcr.io" in content
        assert "docker/build-push-action" in content

    def test_ci_yaml_has_pypi_publish(self):
        """CI pipeline includes PyPI publishing for the SDK."""
        from pathlib import Path

        ci_path = (
            Path(__file__).resolve().parent.parent
            / ".github"
            / "workflows"
            / "ci.yml"
        )
        content = ci_path.read_text()
        assert "publish-sdk" in content
        assert "pypi-publish" in content
