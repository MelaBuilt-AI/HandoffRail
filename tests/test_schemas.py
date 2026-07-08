"""HandoffRail API Server — Integration tests for schema registry and validation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from httpx import AsyncClient

# Add server dir to Python path so `app` module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))


def _valid_schema() -> dict:
    """Return a valid JSON schema."""
    return {
        "type": "object",
        "required": ["summary", "custom"],
        "properties": {
            "summary": {"type": "string"},
            "custom": {
                "type": "object",
                "required": ["amount"],
                "properties": {
                    "amount": {"type": "number"},
                    "currency": {"type": "string"},
                },
            },
            "conversation_state": {"type": "array"},
            "artifacts": {"type": "array"},
        },
        "additionalProperties": True,
    }


def _minimal_packet_payload(schema_id: str | None = None) -> dict:
    """Return a minimal valid packet creation payload."""
    payload = {
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
    if schema_id is not None:
        payload["schema_id"] = schema_id
    return payload


_SAMPLE_SCHEMA_DEF = {
    "type": "object",
    "required": ["summary"],
    "properties": {
        "summary": {"type": "string"},
        "custom": {
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
            },
        },
    },
    "additionalProperties": True,
}


# ── Schema CRUD Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_schema(client: AsyncClient):
    """POST /schemas with valid payload returns 201."""
    response = await client.post("/api/v1/schemas", json={
        "name": "payment-schema",
        "json_schema": _SAMPLE_SCHEMA_DEF,
        "version": 1,
    })
    assert response.status_code == 201

    data = response.json()
    assert data["name"] == "payment-schema"
    assert data["version"] == 1
    assert data["json_schema"]["type"] == "object"
    assert data["id"] is not None
    assert data["tenant_id"] == "default"


@pytest.mark.asyncio
async def test_create_schema_without_type(client: AsyncClient):
    """POST /schemas with schema missing 'type' returns 422."""
    response = await client.post("/api/v1/schemas", json={
        "name": "invalid-schema",
        "json_schema": {"properties": {"foo": {"type": "string"}}},
        "version": 1,
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_schemas(client: AsyncClient):
    """GET /schemas returns schemas for the tenant."""
    # Create a schema first
    await client.post("/api/v1/schemas", json={
        "name": "schema-a",
        "json_schema": _SAMPLE_SCHEMA_DEF,
        "version": 1,
    })

    response = await client.get("/api/v1/schemas")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] >= 1
    assert len(data["schemas"]) >= 1
    assert data["schemas"][0]["name"] == "schema-a"


@pytest.mark.asyncio
async def test_get_schema(client: AsyncClient):
    """GET /schemas/{id} returns a single schema."""
    create_resp = await client.post("/api/v1/schemas", json={
        "name": "my-schema",
        "json_schema": _SAMPLE_SCHEMA_DEF,
        "version": 2,
    })
    assert create_resp.status_code == 201
    schema_id = create_resp.json()["id"]

    response = await client.get(f"/api/v1/schemas/{schema_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == schema_id
    assert data["name"] == "my-schema"
    assert data["version"] == 2


@pytest.mark.asyncio
async def test_get_schema_not_found(client: AsyncClient):
    """GET /schemas/{id} with non-existent ID returns 404."""
    response = await client.get("/api/v1/schemas/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


# ── Schema Validation on Packet Creation Tests ──────────────────────────────────


@pytest.mark.asyncio
async def test_create_packet_with_valid_schema(client: AsyncClient):
    """POST /packets with schema_id that validates successfully returns 201."""
    # Create a schema that requires "custom.amount" to be a number
    schema_resp = await client.post("/api/v1/schemas", json={
        "name": "payment-validation",
        "json_schema": _SAMPLE_SCHEMA_DEF,
        "version": 1,
    })
    schema_id = schema_resp.json()["id"]

    # Create a packet matching the schema
    payload = _minimal_packet_payload(schema_id)
    payload["context"]["custom"] = {"amount": 42}

    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["status"] == "created"


@pytest.mark.asyncio
async def test_create_packet_with_invalid_schema(client: AsyncClient):
    """POST /packets with schema_id that fails validation returns 422."""
    # Create a schema that requires "custom.amount" to be a number
    schema_resp = await client.post("/api/v1/schemas", json={
        "name": "payment-validation",
        "json_schema": {
            "type": "object",
            "required": ["custom"],
            "properties": {
                "custom": {
                    "type": "object",
                    "required": ["amount"],
                    "properties": {
                        "amount": {"type": "number"},
                    },
                },
            },
            "additionalProperties": True,
        },
        "version": 1,
    })
    schema_id = schema_resp.json()["id"]

    # Create a packet that violates the schema (amount is a string)
    payload = _minimal_packet_payload(schema_id)
    payload["context"]["custom"] = {"amount": "not-a-number"}

    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 422

    data = response.json()
    assert "detail" in data
    assert "validation failed" in data["detail"].lower() or "not a number" in data["detail"].lower()


@pytest.mark.asyncio
async def test_create_packet_with_nonexistent_schema(client: AsyncClient):
    """POST /packets with non-existent schema_id returns 422."""
    payload = _minimal_packet_payload("00000000-0000-0000-0000-000000000000")

    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 422

    data = response.json()
    assert "detail" in data
    assert "not found" in data["detail"]


@pytest.mark.asyncio
async def test_create_packet_without_schema_id(client: AsyncClient):
    """POST /packets without schema_id succeeds as before (backward compatible)."""
    payload = _minimal_packet_payload()
    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 201
    assert response.json()["status"] == "created"


@pytest.mark.asyncio
async def test_batch_create_with_schema_validation(client: AsyncClient):
    """POST /packets/batch with schema_id validates each packet."""
    # Create a schema
    schema_resp = await client.post("/api/v1/schemas", json={
        "name": "batch-validation",
        "json_schema": {
            "type": "object",
            "required": ["summary"],
            "properties": {
                "summary": {"type": "string"},
                "custom": {
                    "type": "object",
                    "required": ["priority"],
                    "properties": {
                        "priority": {"type": "string"},
                    },
                },
            },
            "additionalProperties": True,
        },
        "version": 1,
    })
    schema_id = schema_resp.json()["id"]

    # Valid packet
    valid_packet = _minimal_packet_payload()
    valid_packet["context"]["custom"] = {"priority": "high"}

    # Invalid packet (missing required custom.priority)
    invalid_packet = _minimal_packet_payload()

    response = await client.post("/api/v1/packets/batch", json={
        "packets": [
            {**valid_packet, "schema_id": schema_id},
            {**invalid_packet, "schema_id": schema_id},
        ],
    })
    assert response.status_code == 201

    data = response.json()
    assert len(data["created"]) == 1
    assert len(data["errors"]) == 1
    assert data["errors"][0]["error"] is not None


@pytest.mark.asyncio
async def test_chain_with_schema_validation(client: AsyncClient):
    """POST /packets/{id}/chain with schema_id validates context."""
    # Create a parent packet
    parent_resp = await client.post("/api/v1/packets", json=_minimal_packet_payload())
    assert parent_resp.status_code == 201
    parent_id = parent_resp.json()["id"]

    # Create a schema
    schema_resp = await client.post("/api/v1/schemas", json={
        "name": "chain-validation",
        "json_schema": {
            "type": "object",
            "required": ["summary"],
            "properties": {
                "summary": {"type": "string"},
                "custom": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {
                        "status": {"type": "string"},
                    },
                },
            },
            "additionalProperties": True,
        },
        "version": 1,
    })
    schema_id = schema_resp.json()["id"]

    # Chain with invalid context (missing custom.status)
    chain_payload = {
        "metadata": {
            "source_agent": {"id": "test-source", "name": "TestSource", "framework": "test"},
            "target_agent": {"id": "test-target", "name": "TestTarget"},
            "priority": "normal",
        },
        "context": {
            "summary": "Chain test",
            "custom": {"status": 123},  # should be a string
        },
        "decisions": [],
        "actions": {"pending": [], "completed": [], "failed": []},
        "dependencies": [],
        "hitl": None,
        "schema_id": schema_id,
    }

    response = await client.post(f"/api/v1/packets/{parent_id}/chain", json=chain_payload)
    assert response.status_code == 422

    data = response.json()
    assert "detail" in data
    assert "validation failed" in data["detail"].lower() or "123 is not of type" in data["detail"]


@pytest.mark.asyncio
async def test_schema_tenant_isolation(client: AsyncClient, tenant2_client: AsyncClient):
    """Schemas from one tenant are not visible to another."""
    # Create schema as tenant1 (default)
    create_resp = await client.post("/api/v1/schemas", json={
        "name": "tenant1-schema",
        "json_schema": _SAMPLE_SCHEMA_DEF,
        "version": 1,
    })
    schema_id = create_resp.json()["id"]

    # Tenant2 should not see this schema
    list_resp = await tenant2_client.get("/api/v1/schemas")
    assert list_resp.status_code == 200
    data = list_resp.json()
    for s in data["schemas"]:
        assert s["id"] != schema_id

    # Tenant2 should get 404 trying to access it
    get_resp = await tenant2_client.get(f"/api/v1/schemas/{schema_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_schema_validation_required_fields(client: AsyncClient):
    """Schema validation enforces required fields in context."""
    # Create a schema with required fields
    schema_resp = await client.post("/api/v1/schemas", json={
        "name": "strict-schema",
        "json_schema": {
            "type": "object",
            "required": ["summary", "custom"],
            "properties": {
                "summary": {"type": "string"},
                "custom": {
                    "type": "object",
                    "required": ["order_id", "amount"],
                    "properties": {
                        "order_id": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                },
            },
            "additionalProperties": True,
        },
        "version": 1,
    })
    schema_id = schema_resp.json()["id"]

    # Missing required fields in custom
    payload = _minimal_packet_payload(schema_id)
    payload["context"]["custom"] = {"order_id": "ORD-123"}  # missing amount

    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_schema_validation_nested_custom(client: AsyncClient):
    """Schema validation works on the nested custom object in context."""
    schema_resp = await client.post("/api/v1/schemas", json={
        "name": "nested-validation",
        "json_schema": {
            "type": "object",
            "required": ["summary"],
            "properties": {
                "summary": {"type": "string"},
                "custom": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["sku", "qty"],
                                "properties": {
                                    "sku": {"type": "string"},
                                    "qty": {"type": "integer"},
                                },
                            },
                        },
                    },
                },
            },
            "additionalProperties": True,
        },
        "version": 1,
    })
    schema_id = schema_resp.json()["id"]

    # Valid nested
    payload = _minimal_packet_payload(schema_id)
    payload["context"]["custom"] = {
        "items": [
            {"sku": "SKU-001", "qty": 2},
            {"sku": "SKU-002", "qty": 1},
        ],
    }
    response = await client.post("/api/v1/packets", json=payload)
    assert response.status_code == 201

    # Invalid nested (missing qty)
    payload2 = _minimal_packet_payload(schema_id)
    payload2["context"]["custom"] = {
        "items": [
            {"sku": "SKU-001"},  # missing qty
        ],
    }
    response2 = await client.post("/api/v1/packets", json=payload2)
    assert response2.status_code == 422
