"""Tests for structured audit log endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from httpx import AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))


def _minimal_payload() -> dict:
    return {
        "metadata": {
            "source_agent": {"id": "audit-source", "name": "AuditSource"},
            "target_agent": {"id": "audit-target", "name": "AuditTarget"},
        },
        "context": {"summary": "Audit packet"},
    }


@pytest.mark.asyncio
async def test_audit_log_lists_packet_events(client: AsyncClient):
    create_resp = await client.post("/api/v1/packets", json=_minimal_payload())
    assert create_resp.status_code == 201
    packet_id = create_resp.json()["id"]

    audit_resp = await client.get("/api/v1/audit")
    assert audit_resp.status_code == 200
    data = audit_resp.json()

    assert data["total"] >= 1
    assert data["entries"][0]["packet_id"] == packet_id
    assert data["entries"][0]["action"] == "created"
    assert data["entries"][0]["resource"] == "packet"


@pytest.mark.asyncio
async def test_audit_log_filters_by_action_and_packet(client: AsyncClient):
    create_resp = await client.post("/api/v1/packets", json=_minimal_payload())
    assert create_resp.status_code == 201
    packet_id = create_resp.json()["id"]

    audit_resp = await client.get(
        "/api/v1/audit",
        params={"action": "created", "packet_id": packet_id},
    )
    assert audit_resp.status_code == 200
    data = audit_resp.json()

    assert data["total"] == 1
    assert data["entries"][0]["packet_id"] == packet_id
    assert data["entries"][0]["action"] == "created"
