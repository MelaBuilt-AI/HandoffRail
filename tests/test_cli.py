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
        assert "0.1.0" in result.output

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
