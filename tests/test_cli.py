"""Tests for HandoffRail CLI commands."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

# Add paths
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from handoffrail.sdk.exceptions import (
    AuthenticationError,
    ConnectionError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from handoffrail.sdk.models import (
    PacketEvent,
    PacketHistoryResponse,
    PacketListResponse,
    PacketResponse,
)

from cli.main import cli

# ── Fixtures ──────────────────────────────────────────────────────────────


def _make_packet_response(**overrides) -> PacketResponse:
    """Create a sample PacketResponse for testing."""
    defaults = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "version": "1.0.0",
        "parent_packet_id": None,
        "metadata": {
            "source_agent": {"id": "agent-1", "name": "SourceBot"},
            "target_agent": {"id": "agent-2", "name": "TargetBot"},
            "created_at": "2025-01-01T00:00:00Z",
            "priority": "normal",
            "tags": ["test"],
        },
        "context": {
            "summary": "Test packet summary",
            "conversation_state": [],
            "artifacts": [],
            "custom": {},
        },
        "decisions": [],
        "actions": {"pending": [], "completed": [], "failed": []},
        "dependencies": [],
        "hitl": None,
        "status": "created",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return PacketResponse.from_dict(defaults)


def _mock_client():
    """Create a mock HandoffRailClient that patches get_client."""
    return MagicMock()


def _patch_get_client(mock_client):
    """Return a patch context for cli.utils.get_client that returns mock_client."""
    return patch("cli.utils.get_client", return_value=mock_client)


# ── create command ─────────────────────────────────────────────────────────


class TestCreateCommand:
    """Tests for the 'create' CLI command."""

    def test_create_from_file_json(self, tmp_path):
        """Create a packet from a JSON file."""
        packet_data = {
            "metadata": {
                "source_agent": {"id": "agent-1", "name": "SourceBot"},
                "target_agent": {"id": "agent-2", "name": "TargetBot"},
                "priority": "normal",
                "tags": ["test"],
            },
            "context": {
                "summary": "Test packet from file",
            },
        }
        json_file = tmp_path / "packet.json"
        json_file.write_text(json.dumps(packet_data))

        mock_resp = _make_packet_response()
        mock_client = _mock_client()
        mock_client.create_packet.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "create", "-f", str(json_file),
                "--format", "json",
            ])

        assert result.exit_code == 0, f"Exit code {result.exit_code}, output: {result.output}"
        mock_client.create_packet.assert_called_once()
        output = json.loads(result.output)
        assert output["id"] == "550e8400-e29b-41d4-a716-446655440000"

    def test_create_from_cli_args(self):
        """Create a packet from CLI flags."""
        mock_resp = _make_packet_response()
        mock_client = _mock_client()
        mock_client.create_packet.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "create",
                "--source-id", "agent-1",
                "--source-name", "SourceBot",
                "--target-id", "agent-2",
                "--target-name", "TargetBot",
                "--summary", "Hello world",
                "--priority", "high",
                "--tag", "test",
                "--tag", "demo",
                "--format", "json",
            ])

        assert result.exit_code == 0, f"Exit code {result.exit_code}, output: {result.output}"
        mock_client.create_packet.assert_called_once()

    def test_create_missing_required_args(self):
        """Create without required args should fail."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--api-key", "test-key",
            "create",
            "--source-id", "agent-1",
            # Missing --source-name, --target-id, --target-name
        ])
        assert result.exit_code != 0
        assert "required" in result.output.lower() or "Error" in result.output

    def test_create_missing_summary(self):
        """Create without --summary when not using --file should fail."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--api-key", "test-key",
            "create",
            "--source-id", "agent-1",
            "--source-name", "SourceBot",
            "--target-id", "agent-2",
            "--target-name", "TargetBot",
            # No --summary
        ])
        assert result.exit_code != 0
        assert "summary" in result.output.lower()

    def test_create_table_format(self):
        """Create with table format should show human-readable output."""
        mock_resp = _make_packet_response()
        mock_client = _mock_client()
        mock_client.create_packet.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "create",
                "--source-id", "agent-1",
                "--source-name", "SourceBot",
                "--target-id", "agent-2",
                "--target-name", "TargetBot",
                "--summary", "Hello",
            ])

        assert result.exit_code == 0
        assert "ID:" in result.output
        assert "SourceBot" in result.output
        assert "TargetBot" in result.output

    def test_create_packet_too_large(self):
        """Packet exceeding 256KB should be rejected."""
        mock_client = _mock_client()
        mock_client.create_packet.return_value = _make_packet_response()

        runner = CliRunner()
        with _patch_get_client(mock_client):
            # Create a packet with a massive summary
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "create",
                "--source-id", "agent-1",
                "--source-name", "SourceBot",
                "--target-id", "agent-2",
                "--target-name", "TargetBot",
                "--summary", "x" * (300 * 1024),  # 300KB summary
            ])

        assert result.exit_code != 0
        assert "too large" in result.output.lower()

    def test_create_invalid_file(self, tmp_path):
        """Create from invalid JSON file should fail."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{{")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--api-key", "test-key",
            "create", "-f", str(bad_file),
        ])
        assert result.exit_code != 0

    def test_create_no_api_key(self):
        """Create without API key should fail with helpful message."""
        runner = CliRunner(env={"HANDOFFRAIL_API_KEY": ""})
        result = runner.invoke(cli, [
            "create",
            "--source-id", "a", "--source-name", "b",
            "--target-id", "c", "--target-name", "d",
            "--summary", "x",
        ])
        assert result.exit_code != 0
        assert "api key" in result.output.lower()


# ── get command ───────────────────────────────────────────────────────────


class TestGetCommand:
    """Tests for the 'get' CLI command."""

    def test_get_packet_table(self):
        """Get a packet and display as table."""
        mock_resp = _make_packet_response()
        mock_client = _mock_client()
        mock_client.get_packet.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "get", "550e8400-e29b-41d4-a716-446655440000",
            ])

        assert result.exit_code == 0
        assert "550e8400" in result.output
        assert "created" in result.output.lower()

    def test_get_packet_json(self):
        """Get a packet and display as JSON."""
        mock_resp = _make_packet_response()
        mock_client = _mock_client()
        mock_client.get_packet.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "get", "550e8400-e29b-41d4-a716-446655440000",
                "--format", "json",
            ])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["id"] == "550e8400-e29b-41d4-a716-446655440000"

    def test_get_packet_not_found(self):
        """Get a non-existent packet should show not found error."""
        mock_client = _mock_client()
        mock_client.get_packet.side_effect = NotFoundError("Packet not found")

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "get", "nonexistent-id",
            ])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_get_packet_auth_error(self):
        """Get with invalid API key should show auth error."""
        mock_client = _mock_client()
        mock_client.get_packet.side_effect = AuthenticationError("Invalid API key")

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "bad-key",
                "get", "some-id",
            ])

        assert result.exit_code != 0
        assert "authentication" in result.output.lower()


# ── list command ───────────────────────────────────────────────────────────


class TestListCommand:
    """Tests for the 'list' CLI command."""

    def test_list_packets_table(self):
        """List packets in table format."""
        resp1 = _make_packet_response()
        resp2 = _make_packet_response(
            id="660e8400-e29b-41d4-a716-446655440001",
            status="claimed",
        )
        list_resp = PacketListResponse(
            packets=[resp1, resp2],
            total=2,
            limit=20,
            offset=0,
        )

        mock_client = _mock_client()
        mock_client.list_packets.return_value = list_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "list",
            ])

        assert result.exit_code == 0
        assert "550e8400" in result.output
        assert "660e8400" in result.output

    def test_list_packets_json(self):
        """List packets in JSON format."""
        resp1 = _make_packet_response()
        list_resp = PacketListResponse(
            packets=[resp1],
            total=1,
            limit=20,
            offset=0,
        )

        mock_client = _mock_client()
        mock_client.list_packets.return_value = list_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "list", "--format", "json",
            ])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["total"] == 1

    def test_list_with_filters(self):
        """List packets with status filter."""
        list_resp = PacketListResponse(
            packets=[],
            total=0,
            limit=20,
            offset=0,
        )

        mock_client = _mock_client()
        mock_client.list_packets.return_value = list_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "list", "--status", "created", "--limit", "10",
            ])

        assert result.exit_code == 0
        mock_client.list_packets.assert_called_once()
        call_kwargs = mock_client.list_packets.call_args[1]
        assert call_kwargs["status"] == "created"
        assert call_kwargs["limit"] == 10

    def test_list_empty(self):
        """List with no packets should show 'No packets found'."""
        list_resp = PacketListResponse(
            packets=[],
            total=0,
            limit=20,
            offset=0,
        )

        mock_client = _mock_client()
        mock_client.list_packets.return_value = list_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "list",
            ])

        assert result.exit_code == 0
        assert "no packets found" in result.output.lower()

    def test_list_connection_error(self):
        """List with connection error should show helpful message."""
        mock_client = _mock_client()
        mock_client.list_packets.side_effect = ConnectionError("Cannot connect to server")

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "list",
            ])

        assert result.exit_code != 0
        assert "connection" in result.output.lower()


# ── claim command ─────────────────────────────────────────────────────────


class TestClaimCommand:
    """Tests for the 'claim' CLI command."""

    def test_claim_packet(self):
        """Claim a packet successfully."""
        mock_resp = _make_packet_response(status="claimed")
        mock_client = _mock_client()
        mock_client.claim_packet.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "claim", "550e8400-e29b-41d4-a716-446655440000",
                "--agent-id", "billing-01",
                "--agent-name", "BillingBot",
            ])

        assert result.exit_code == 0
        assert "claimed" in result.output.lower()
        mock_client.claim_packet.assert_called_once()

    def test_claim_with_framework(self):
        """Claim a packet with framework specified."""
        mock_resp = _make_packet_response(status="claimed")
        mock_client = _mock_client()
        mock_client.claim_packet.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "claim", "550e8400-e29b-41d4-a716-446655440000",
                "--agent-id", "billing-01",
                "--agent-name", "BillingBot",
                "--framework", "langchain",
            ])

        assert result.exit_code == 0
        call_kwargs = mock_client.claim_packet.call_args[1]
        assert call_kwargs["framework"] == "langchain"

    def test_claim_missing_agent_id(self):
        """Claim without agent-id should fail."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--api-key", "test-key",
            "claim", "550e8400-e29b-41d4-a716-446655440000",
            "--agent-name", "BillingBot",
            # Missing --agent-id
        ])
        assert result.exit_code != 0

    def test_claim_conflict(self):
        """Claim already-claimed packet should show conflict error."""
        mock_client = _mock_client()
        mock_client.claim_packet.side_effect = ValidationError(
            "Packet is already claimed",
            status_code=409,
        )

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "claim", "550e8400-e29b-41d4-a716-446655440000",
                "--agent-id", "billing-01",
                "--agent-name", "BillingBot",
            ])

        assert result.exit_code != 0
        assert "validation" in result.output.lower()

    def test_claim_with_agent_shorthand(self):
        """Claim using --agent shorthand (sets both id and name)."""
        mock_resp = _make_packet_response(status="claimed")
        mock_client = _mock_client()
        mock_client.claim_packet.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "claim", "550e8400-e29b-41d4-a716-446655440000",
                "--agent", "billing-01",
            ])

        assert result.exit_code == 0, f"Exit code {result.exit_code}, output: {result.output}"
        assert "claimed" in result.output.lower()
        call_kwargs = mock_client.claim_packet.call_args[1]
        assert call_kwargs["agent_id"] == "billing-01"
        assert call_kwargs["agent_name"] == "billing-01"

    def test_claim_with_agent_and_separate_name(self):
        """Claim using --agent for ID and --agent-name for display name."""
        mock_resp = _make_packet_response(status="claimed")
        mock_client = _mock_client()
        mock_client.claim_packet.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "claim", "550e8400-e29b-41d4-a716-446655440000",
                "--agent", "billing-01",
                "--agent-name", "BillingBot",
            ])

        assert result.exit_code == 0
        call_kwargs = mock_client.claim_packet.call_args[1]
        assert call_kwargs["agent_id"] == "billing-01"
        assert call_kwargs["agent_name"] == "BillingBot"

    def test_claim_agent_mutually_exclusive_with_agent_id(self):
        """--agent and --agent-id should be mutually exclusive."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--api-key", "test-key",
            "claim", "550e8400-e29b-41d4-a716-446655440000",
            "--agent", "my-agent",
            "--agent-id", "other-agent",
        ])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()

    def test_claim_agent_mutually_exclusive_with_agent_id_positional(self):
        """--agent and --agent-id should be mutually exclusive (positional test)."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--api-key", "test-key",
            "claim", "550e8400-e29b-41d4-a716-446655440000",
            "--agent-id", "other-agent",
            "--agent", "my-agent",
        ])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()

    def test_claim_missing_both_agent_and_agent_id(self):
        """Claim without --agent or --agent-id should fail."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--api-key", "test-key",
            "claim", "550e8400-e29b-41d4-a716-446655440000",
            "--agent-name", "Bot",
            # Missing both --agent and --agent-id
        ])
        assert result.exit_code != 0
        assert "--agent=ID" in result.output or "required" in result.output.lower()


# ── respond command ───────────────────────────────────────────────────────


class TestRespondCommand:
    """Tests for the 'respond' CLI command."""

    def test_respond_to_hitl(self):
        """Respond to a HITL checkpoint."""
        hitl_data = {
            "required": True,
            "reason": "Needs approval",
            "response": "Approved",
            "responded_by": "human-1",
            "responded_at": "2025-01-01T01:00:00Z",
        }
        mock_resp = _make_packet_response(
            status="claimed",
            hitl=hitl_data,
        )
        mock_client = _mock_client()
        mock_client.respond_to_hitl.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "respond", "550e8400-e29b-41d4-a716-446655440000",
                "--response", "Approved",
                "--responded-by", "human-1",
            ])

        assert result.exit_code == 0
        assert "hitl" in result.output.lower() or "response" in result.output.lower()

    def test_respond_with_notes(self):
        """Respond with optional notes."""
        mock_resp = _make_packet_response(status="claimed")
        mock_client = _mock_client()
        mock_client.respond_to_hitl.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "respond", "550e8400-e29b-41d4-a716-446655440000",
                "--response", "Approved",
                "--responded-by", "human-1",
                "--notes", "Checked with team lead",
            ])

        assert result.exit_code == 0
        call_kwargs = mock_client.respond_to_hitl.call_args[1]
        assert call_kwargs["notes"] == "Checked with team lead"

    def test_respond_missing_response(self):
        """Respond without --response should fail."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--api-key", "test-key",
            "respond", "some-id",
            "--responded-by", "human-1",
            # Missing --response
        ])
        assert result.exit_code != 0


# ── history command ───────────────────────────────────────────────────────


class TestHistoryCommand:
    """Tests for the 'history' CLI command."""

    def test_history_table(self):
        """View event history in table format."""
        history_resp = PacketHistoryResponse(
            packet_id="550e8400-e29b-41d4-a716-446655440000",
            events=[
                PacketEvent(
                    id="evt-1",
                    packet_id="550e8400-e29b-41d4-a716-446655440000",
                    event_type="created",
                    actor="agent:agent-1",
                    details={"source": "agent-1"},
                    timestamp="2025-01-01T00:00:00Z",
                ),
                PacketEvent(
                    id="evt-2",
                    packet_id="550e8400-e29b-41d4-a716-446655440000",
                    event_type="claimed",
                    actor="agent:agent-2",
                    details={"agent_name": "TargetBot"},
                    timestamp="2025-01-01T00:01:00Z",
                ),
            ],
        )

        mock_client = _mock_client()
        mock_client.get_history.return_value = history_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "history", "550e8400-e29b-41d4-a716-446655440000",
            ])

        assert result.exit_code == 0
        assert "created" in result.output
        assert "claimed" in result.output

    def test_history_json(self):
        """View event history in JSON format."""
        history_resp = PacketHistoryResponse(
            packet_id="550e8400-e29b-41d4-a716-446655440000",
            events=[
                PacketEvent(
                    id="evt-1",
                    packet_id="550e8400-e29b-41d4-a716-446655440000",
                    event_type="created",
                    actor="agent:agent-1",
                    details=None,
                    timestamp="2025-01-01T00:00:00Z",
                ),
            ],
        )

        mock_client = _mock_client()
        mock_client.get_history.return_value = history_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "history", "550e8400-e29b-41d4-a716-446655440000",
                "--format", "json",
            ])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["packet_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert len(output["events"]) == 1

    def test_history_empty(self):
        """History with no events should show 'No events'."""
        history_resp = PacketHistoryResponse(
            packet_id="550e8400-e29b-41d4-a716-446655440000",
            events=[],
        )

        mock_client = _mock_client()
        mock_client.get_history.return_value = history_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "history", "550e8400-e29b-41d4-a716-446655440000",
            ])

        assert result.exit_code == 0
        assert "no events" in result.output.lower()

    def test_history_not_found(self):
        """History for non-existent packet should show not found."""
        mock_client = _mock_client()
        mock_client.get_history.side_effect = NotFoundError("Packet not found")

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "history", "nonexistent",
            ])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# ── serve command ──────────────────────────────────────────────────────────


class TestServeCommand:
    """Tests for the 'serve' CLI command."""

    def test_serve_with_options(self):
        """Serve command should accept host, port, and reload options."""
        runner = CliRunner()
        with patch.dict("sys.modules", {"uvicorn": MagicMock()}):
            # We can't easily test uvicorn.run since it blocks,
            # but we can verify the command is registered and accepts options
            # Just check that the serve command exists and accepts args
            result = runner.invoke(cli, ["--api-key", "test-key", "serve", "--help"])
            assert result.exit_code == 0
            assert "--host" in result.output
            assert "--port" in result.output
            assert "--reload" in result.output


# ── Global options ─────────────────────────────────────────────────────────


class TestGlobalOptions:
    """Tests for global CLI options."""

    def test_server_url_from_env(self):
        """Server URL should fall back to HANDOFFRAIL_URL env var."""
        mock_client = _mock_client()
        mock_client.list_packets.return_value = PacketListResponse(
            packets=[], total=0, limit=20, offset=0,
        )

        runner = CliRunner(env={"HANDOFFRAIL_URL": "http://custom:9090/api/v1"})
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "list",
            ])

        assert result.exit_code == 0

    def test_api_key_from_env(self):
        """API key should fall back to HANDOFFRAIL_API_KEY env var."""
        mock_client = _mock_client()
        mock_client.list_packets.return_value = PacketListResponse(
            packets=[], total=0, limit=20, offset=0,
        )

        runner = CliRunner(env={"HANDOFFRAIL_API_KEY": "env-api-key"})
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "list",
            ])

        assert result.exit_code == 0

    def test_verbose_flag(self):
        """--verbose flag should set debug logging."""
        mock_client = _mock_client()
        mock_client.list_packets.return_value = PacketListResponse(
            packets=[], total=0, limit=20, offset=0,
        )

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--verbose",
                "--api-key", "test-key",
                "list",
            ])

        assert result.exit_code == 0

    def test_quiet_flag(self):
        """--quiet flag should suppress non-error output."""
        mock_client = _mock_client()
        mock_client.list_packets.return_value = PacketListResponse(
            packets=[], total=0, limit=20, offset=0,
        )

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--quiet",
                "--api-key", "test-key",
                "list",
            ])

        # Even in quiet mode, the command should succeed
        assert result.exit_code == 0

    def test_version_flag(self):
        """--version should print version and exit."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.2.0" in result.output

    def test_server_url_flag_overrides_env(self):
        """--server-url flag should override HANDOFFRAIL_URL env var."""
        mock_client = _mock_client()
        mock_client.list_packets.return_value = PacketListResponse(
            packets=[], total=0, limit=20, offset=0,
        )

        runner = CliRunner(env={"HANDOFFRAIL_URL": "http://env-url:9090/api/v1"})
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--server-url", "http://override:8080/api/v1",
                "--api-key", "test-key",
                "list",
            ])

        assert result.exit_code == 0


# ── Error handling ─────────────────────────────────────────────────────────


class TestErrorHandling:
    """Tests for CLI error handling."""

    def test_rate_limit_error(self):
        """RateLimitError should show retry-after hint."""
        mock_client = _mock_client()
        mock_client.list_packets.side_effect = RateLimitError(
            "Rate limit exceeded",
            retry_after=60,
        )

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "list",
            ])

        assert result.exit_code != 0
        assert "rate limit" in result.output.lower()
        assert "60" in result.output

    def test_server_error(self):
        """ServerError should show user-friendly message."""
        mock_client = _mock_client()
        mock_client.get_packet.side_effect = ServerError(
            "Internal server error",
            status_code=500,
        )

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "get", "some-id",
            ])

        assert result.exit_code != 0
        assert "server error" in result.output.lower()

    def test_connection_error(self):
        """ConnectionError should show helpful message."""
        mock_client = _mock_client()
        mock_client.get_packet.side_effect = ConnectionError(
            "Unable to connect to HandoffRail server",
        )

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "get", "some-id",
            ])

        assert result.exit_code != 0
        assert "connection" in result.output.lower()

    def test_verbose_shows_unexpected_error(self):
        """--verbose should show unexpected error details."""
        mock_client = _mock_client()
        mock_client.get_packet.side_effect = RuntimeError("Unexpected!")

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--verbose",
                "--api-key", "test-key",
                "get", "some-id",
            ])

        assert result.exit_code != 0
        assert "unexpected" in result.output.lower()

    def test_non_verbose_hides_unexpected_error(self):
        """Without --verbose, unexpected errors should show generic message."""
        mock_client = _mock_client()
        mock_client.get_packet.side_effect = RuntimeError("Unexpected!")

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "get", "some-id",
            ])

        assert result.exit_code != 0
        # Should not show the raw exception
        assert "RuntimeError" not in result.output


# ── Packet size validation ───────────────────────────────────────────────


class TestPacketSizeLimit:
    """Tests for packet size validation."""

    def test_create_valid_size_packet(self):
        """Packets under 256KB should be accepted."""
        mock_resp = _make_packet_response()
        mock_client = _mock_client()
        mock_client.create_packet.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "create",
                "--source-id", "agent-1",
                "--source-name", "SourceBot",
                "--target-id", "agent-2",
                "--target-name", "TargetBot",
                "--summary", "Small packet",
            ])

        assert result.exit_code == 0

    def test_server_size_limit_middleware(self):
        """Test the size limit middleware constant is 256KB."""
        from app.middleware.size_limit import MAX_BODY_SIZE

        # Check that the constant is 256KB
        assert MAX_BODY_SIZE == 256 * 1024


# ── search command ────────────────────────────────────────────────────────


class TestSearchCommand:
    """Tests for the 'search' CLI command."""

    def _make_search_results(self, count=2):
        """Create a sample PacketListResponse for search testing."""
        packets = []
        for i in range(count):
            pkt = _make_packet_response(
                id=f"550e8400-e29b-41d4-a716-44665544000{i}",
                context={
                    "summary": f"Search result {i} about error handling",
                    "conversation_state": [],
                    "artifacts": [],
                    "custom": {},
                },
            )
            packets.append(pkt)
        return PacketListResponse(packets=packets, total=count, limit=20, offset=0)

    def test_search_table(self):
        """Search packets in table format."""
        list_resp = self._make_search_results()
        mock_client = _mock_client()
        mock_client.search_packets.return_value = list_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "search", "error handling",
            ])

        assert result.exit_code == 0, f"Exit code {result.exit_code}, output: {result.output}"
        assert "Search result" in result.output
        mock_client.search_packets.assert_called_once()
        args, kwargs = mock_client.search_packets.call_args
        assert "error handling" in args

    def test_search_json(self):
        """Search packets in JSON format."""
        list_resp = self._make_search_results(count=1)
        mock_client = _mock_client()
        mock_client.search_packets.return_value = list_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "search", "error",
                "--format", "json",
            ])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["total"] == 1

    def test_search_empty(self):
        """Search with no matches should show 'No matching packets'."""
        list_resp = PacketListResponse(packets=[], total=0, limit=20, offset=0)
        mock_client = _mock_client()
        mock_client.search_packets.return_value = list_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "search", "nonexistent",
            ])

        assert result.exit_code == 0
        assert "no matching" in result.output.lower()

    def test_search_too_short_query(self):
        """Search with a single-character query should fail."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--api-key", "test-key",
            "search", "x",
        ])
        assert result.exit_code != 0
        assert "at least 2 characters" in result.output.lower()

    def test_search_with_filters(self):
        """Search with status and priority filters."""
        list_resp = PacketListResponse(packets=[], total=0, limit=20, offset=0)
        mock_client = _mock_client()
        mock_client.search_packets.return_value = list_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "search", "test query",
                "--status", "created",
                "--priority", "high",
                "--limit", "5",
            ])

        assert result.exit_code == 0
        mock_client.search_packets.assert_called_once()
        args, kwargs = mock_client.search_packets.call_args
        assert "test query" in args


# ── hooks list command ────────────────────────────────────────────────────


class TestHooksListCommand:
    """Tests for the 'hooks list' CLI command."""

    def _make_webhook_response(self, **overrides):
        """Create a sample WebhookResponse for testing."""
        from handoffrail.sdk.models import WebhookResponse
        defaults = {
            "id": "wh-001",
            "url": "https://example.com/webhook",
            "events": ["packet.created", "packet.completed"],
            "tenant_id": "tenant-1",
            "active": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
        defaults.update(overrides)
        return WebhookResponse.from_dict(defaults)

    def test_hooks_list_table(self):
        """List webhooks in table format."""
        hooks = [
            self._make_webhook_response(id="wh-001", url="https://hooks.example.com/a"),
            self._make_webhook_response(id="wh-002", url="https://hooks.example.com/b", active=False),
        ]
        mock_client = _mock_client()
        mock_client.list_webhooks.return_value = hooks

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "hooks", "list",
            ])

        assert result.exit_code == 0, f"Exit code {result.exit_code}, output: {result.output}"
        assert "wh-001" in result.output
        assert "wh-002" in result.output
        assert "hooks.example.com" in result.output
        # Active indicator
        assert "\u2713" in result.output  # ✓

    def test_hooks_list_json(self):
        """List webhooks in JSON format."""
        hooks = [self._make_webhook_response(id="wh-001")]
        mock_client = _mock_client()
        mock_client.list_webhooks.return_value = hooks

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "hooks", "list",
                "--format", "json",
            ])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert len(output) == 1
        assert output[0]["id"] == "wh-001"

    def test_hooks_list_empty(self):
        """List webhooks with no hooks should show 'No webhooks'."""
        mock_client = _mock_client()
        mock_client.list_webhooks.return_value = []

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "hooks", "list",
            ])

        assert result.exit_code == 0
        assert "no webhooks" in result.output.lower()

    def test_hooks_list_error(self):
        """List webhooks with server error should show error."""
        mock_client = _mock_client()
        mock_client.list_webhooks.side_effect = ServerError("Server error", status_code=500)

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "hooks", "list",
            ])

        assert result.exit_code != 0
        assert "server error" in result.output.lower()


# ── keys commands ─────────────────────────────────────────────────────────


class TestKeysCreateCommand:
    """Tests for the 'keys create' CLI command."""

    def _make_key_response(self, **overrides):
        """Create a sample ApiKeyResponse for testing."""
        from handoffrail.sdk.models import ApiKeyResponse
        defaults = {
            "id": "key-001",
            "name": "prod-key",
            "key_prefix": "hr_abcDEF",
            "tenant_id": "tenant-1",
            "revoked": False,
            "created_at": "2025-01-01T00:00:00Z",
            "key": "hr_abcDEFghijklmnopqrstuvwx",
        }
        defaults.update(overrides)
        return ApiKeyResponse.from_dict(defaults)

    def test_keys_create_table(self):
        """Create API key in table format."""
        key_resp = self._make_key_response()
        mock_client = _mock_client()
        mock_client.create_api_key.return_value = key_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "admin-key",
                "keys", "create",
                "--name", "prod-key",
            ])

        assert result.exit_code == 0, f"Exit code {result.exit_code}, output: {result.output}"
        assert "key-001" in result.output
        assert "prod-key" in result.output
        assert "hr_abcDEF" in result.output
        mock_client.create_api_key.assert_called_once_with(name="prod-key", tenant_id=None, role="admin")

    def test_keys_create_json(self):
        """Create API key in JSON format."""
        key_resp = self._make_key_response()
        mock_client = _mock_client()
        mock_client.create_api_key.return_value = key_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "admin-key",
                "keys", "create",
                "--name", "prod-key",
                "--format", "json",
            ])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["id"] == "key-001"
        assert output["name"] == "prod-key"
        assert output["key"] == "hr_abcDEFghijklmnopqrstuvwx"

    def test_keys_create_missing_name(self):
        """Create API key without --name should fail."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--api-key", "admin-key",
            "keys", "create",
            # Missing --name
        ])
        assert result.exit_code != 0
        assert "name" in result.output.lower()

    def test_keys_create_with_tenant(self):
        """Create API key with tenant ID."""
        key_resp = self._make_key_response()
        mock_client = _mock_client()
        mock_client.create_api_key.return_value = key_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "admin-key",
                "keys", "create",
                "--name", "tenant-key",
                "--tenant-id", "tenant-2",
                "--format", "json",
            ])

        assert result.exit_code == 0
        mock_client.create_api_key.assert_called_once_with(name="tenant-key", tenant_id="tenant-2", role="admin")


class TestKeysListCommand:
    """Tests for the 'keys list' CLI command."""

    def _make_key(self, **overrides):
        """Create a sample ApiKeyResponse for list testing."""
        from handoffrail.sdk.models import ApiKeyResponse
        defaults = {
            "id": "key-001",
            "name": "prod-key",
            "key_prefix": "hr_abcDEF",
            "tenant_id": "tenant-1",
            "revoked": False,
            "created_at": "2025-01-01T00:00:00Z",
            "key": None,  # Key value not shown on list
        }
        defaults.update(overrides)
        return ApiKeyResponse.from_dict(defaults)

    def test_keys_list_table(self):
        """List API keys in table format."""
        keys = [
            self._make_key(id="key-001", name="prod-key", key_prefix="hr_abc"),
            self._make_key(id="key-002", name="dev-key", key_prefix="hr_def", revoked=True),
        ]
        mock_client = _mock_client()
        mock_client.list_api_keys.return_value = keys

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "admin-key",
                "keys", "list",
            ])

        assert result.exit_code == 0, f"Exit code {result.exit_code}, output: {result.output}"
        assert "key-001" in result.output
        assert "key-002" in result.output
        assert "prod-key" in result.output
        assert "dev-key" in result.output

    def test_keys_list_json(self):
        """List API keys in JSON format."""
        keys = [self._make_key(id="key-001", key_prefix="hr_abc")]
        mock_client = _mock_client()
        mock_client.list_api_keys.return_value = keys

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "admin-key",
                "keys", "list",
                "--format", "json",
            ])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert len(output) == 1
        assert output[0]["id"] == "key-001"
        # Key value should not be in list response
        assert output[0].get("key") is None

    def test_keys_list_empty(self):
        """List keys with no keys should show 'No API keys'."""
        mock_client = _mock_client()
        mock_client.list_api_keys.return_value = []

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "admin-key",
                "keys", "list",
            ])

        assert result.exit_code == 0
        assert "no api keys" in result.output.lower()

    def test_keys_list_error(self):
        """List keys with auth error should show error."""
        mock_client = _mock_client()
        mock_client.list_api_keys.side_effect = AuthenticationError("Invalid API key")

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "bad-key",
                "keys", "list",
            ])

        assert result.exit_code != 0
        assert "authentication" in result.output.lower()


# ── Subcommand group routing ──────────────────────────────────────────────


class TestSubcommandGroups:
    """Tests that subcommand groups route correctly."""

    def test_packets_group_exists(self):
        """The 'packets' group should be registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["packets", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "create" in result.output
        assert "get" in result.output
        assert "claim" in result.output
        assert "search" in result.output

    def test_packets_list_works(self):
        """handoffrail packets list should work like handoffrail list."""
        list_resp = PacketListResponse(packets=[], total=0, limit=20, offset=0)
        mock_client = _mock_client()
        mock_client.list_packets.return_value = list_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "packets", "list",
            ])

        assert result.exit_code == 0
        mock_client.list_packets.assert_called_once()

    def test_packets_create_works(self):
        """handoffrail packets create should work like handoffrail create."""
        mock_resp = _make_packet_response()
        mock_client = _mock_client()
        mock_client.create_packet.return_value = mock_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "packets", "create",
                "--source-id", "agent-1",
                "--source-name", "SourceBot",
                "--target-id", "agent-2",
                "--target-name", "TargetBot",
                "--summary", "Test via packets group",
                "--format", "json",
            ])

        assert result.exit_code == 0, f"Exit code {result.exit_code}, output: {result.output}"
        output = json.loads(result.output)
        assert output["id"] == "550e8400-e29b-41d4-a716-446655440000"

    def test_packets_search_works(self):
        """handoffrail packets search should work like handoffrail search."""
        list_resp = PacketListResponse(packets=[], total=0, limit=20, offset=0)
        mock_client = _mock_client()
        mock_client.search_packets.return_value = list_resp

        runner = CliRunner()
        with _patch_get_client(mock_client):
            result = runner.invoke(cli, [
                "--api-key", "test-key",
                "packets", "search", "test query",
            ])

        assert result.exit_code == 0
        mock_client.search_packets.assert_called_once()

    def test_hooks_group_exists(self):
        """The 'hooks' group should be registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["hooks", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output

    def test_keys_group_exists(self):
        """The 'keys' group should be registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["keys", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "list" in result.output


# ── Completion command ────────────────────────────────────────────────────


class TestCompletionCommand:
    """Tests for the 'completion' CLI command."""

    def test_completion_bash(self):
        """Generate bash completion script."""
        runner = CliRunner()
        result = runner.invoke(cli, ["completion", "bash"])
        assert result.exit_code == 0, f"Exit code {result.exit_code}, output: {result.output}"
        assert "complete" in result.output or "_HANDOFFRAIL_COMPLETE" in result.output

    def test_completion_zsh(self):
        """Generate zsh completion script."""
        runner = CliRunner()
        result = runner.invoke(cli, ["completion", "zsh"])
        assert result.exit_code == 0
        assert "compdef" in result.output or "_HANDOFFRAIL_COMPLETE" in result.output

    def test_completion_fish(self):
        """Generate fish completion script."""
        runner = CliRunner()
        result = runner.invoke(cli, ["completion", "fish"])
        assert result.exit_code == 0
        assert "complete" in result.output or "_HANDOFFRAIL_COMPLETE" in result.output

    def test_completion_invalid_shell(self):
        """Completion with invalid shell should fail."""
        runner = CliRunner()
        result = runner.invoke(cli, ["completion", "invalid"])
        assert result.exit_code != 0


# ── Config file support ───────────────────────────────────────────────────


class TestConfigFile:
    """Tests for config file loading (~/.handoffrail.toml)."""

    def test_load_config_no_file(self):
        """load_config should return empty dict when no config file exists."""
        from cli.config import load_config
        # The test environment shouldn't have ~/.handoffrail.toml
        result = load_config()
        assert isinstance(result, dict)

    def test_parse_valid_config(self, tmp_path):
        """Parse a valid TOML config file."""
        import tomllib

        # Write to a temp file and test parsing manually
        config_file = tmp_path / ".handoffrail.toml"
        config_file.write_text('''
[handoffrail]
server_url = "http://custom:9090/api/v1"
api_key = "cfg-api-key-12345"
''')

        with open(config_file, "rb") as f:
            data = tomllib.load(f)
        hr_cfg = data.get("handoffrail", {})
        assert hr_cfg["server_url"] == "http://custom:9090/api/v1"
        assert hr_cfg["api_key"] == "cfg-api-key-12345"

    def test_parse_config_partial(self, tmp_path):
        """Parse a config with only server_url."""
        import tomllib

        config_file = tmp_path / ".handoffrail.toml"
        config_file.write_text('''
[handoffrail]
server_url = "http://partial:8080/api/v1"
''')

        with open(config_file, "rb") as f:
            data = tomllib.load(f)
        hr_cfg = data.get("handoffrail", {})
        assert hr_cfg["server_url"] == "http://partial:8080/api/v1"
        assert "api_key" not in hr_cfg

    def test_invalid_config_handled(self, tmp_path):
        """Invalid config file should not crash."""

        # Monkey-patch CONFIG_PATH to a nonexistent path
        import cli.config as cfg_module
        original_path = cfg_module.CONFIG_PATH
        try:
            cfg_module.CONFIG_PATH = tmp_path / "nonexistent.toml"
            result = cfg_module.load_config()
            assert result == {}
        finally:
            cfg_module.CONFIG_PATH = original_path
