"""HandoffRail CLI — create command.

Create a handoff packet from a YAML/JSON file or CLI arguments.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

import cli.utils as utils
from cli.commands.errors import handle_error


@click.command("create")
@click.option(
    "--file", "-f",
    type=click.Path(exists=True),
    help="Path to YAML or JSON file defining the packet.",
)
@click.option("--source-id", help="Source agent ID.")
@click.option("--source-name", help="Source agent name.")
@click.option("--target-id", help="Target agent ID.")
@click.option("--target-name", help="Target agent name.")
@click.option("--summary", help="Context summary text.")
@click.option(
    "--priority",
    type=click.Choice(["low", "normal", "high", "critical"]),
    default=None,
    help="Packet priority.",
)
@click.option("--tag", "tags", multiple=True, help="Tags (can specify multiple times).")
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.pass_context
def create_cmd(
    ctx: click.Context,
    file: str | None,
    source_id: str | None,
    source_name: str | None,
    target_id: str | None,
    target_name: str | None,
    summary: str | None,
    priority: str | None,
    tags: tuple[str, ...],
    output_format: str,
) -> None:
    """Create a new handoff packet.

    Provide a YAML/JSON file with --file, or use individual flags.
    """
    from handoffrail.sdk.models import (
        AgentInfo,
        Metadata,
        PacketContext,
        PacketCreate,
        Priority,
        TargetAgentInfo,
    )

    ctx.obj["format"] = output_format

    if file:
        packet_data = _load_packet_file(file)
        try:
            packet = PacketCreate.from_dict(packet_data)
        except Exception as exc:
            raise click.ClickException(f"Invalid packet data in {file}: {exc}") from exc
    else:
        if not source_id or not source_name or not target_id or not target_name:
            raise click.ClickException(
                "Either --file or --source-id, --source-name, --target-id, --target-name are required."
            )
        if not summary:
            raise click.ClickException("--summary is required when not using --file.")

        packet = PacketCreate(
            metadata=Metadata(
                source_agent=AgentInfo(id=source_id, name=source_name),
                target_agent=TargetAgentInfo(id=target_id, name=target_name),
                priority=Priority(priority) if priority else Priority.normal,
                tags=list(tags) if tags else [],
            ),
            context=PacketContext(summary=summary),
        )

    # Validate packet size (max 256KB serialized)
    payload_size = len(json.dumps(packet.to_dict(), default=str).encode("utf-8"))
    max_size = 256 * 1024
    if payload_size > max_size:
        raise click.ClickException(
            f"Packet payload too large: {payload_size:,} bytes (max {max_size:,} bytes). "
            "Reduce context or artifacts size."
        )

    client = utils.get_client(ctx)
    try:
        result = client.create_packet(packet)
        utils.format_output(ctx, result, _format_packet_table)
    except Exception as exc:
        handle_error(exc, ctx)


def _load_packet_file(path: str) -> dict:
    """Load packet data from YAML or JSON file."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()

    if suffix in (".yml", ".yaml"):
        try:
            import yaml
        except ImportError:
            raise click.ClickException(
                "PyYAML is required to load YAML files. Install it with: pip install pyyaml"
            )
        with open(file_path) as f:
            return yaml.safe_load(f)
    elif suffix == ".json":
        with open(file_path) as f:
            return json.load(f)
    else:
        try:
            with open(file_path) as f:
                return json.load(f)
        except json.JSONDecodeError:
            try:
                import yaml
                with open(file_path) as f:
                    return yaml.safe_load(f)
            except ImportError:
                raise click.ClickException(
                    f"Cannot parse {path}: not valid JSON, and PyYAML not installed."
                )


def _format_packet_table(packet) -> None:
    """Pretty-print a packet as a table."""
    click.echo(f"  ID:         {packet.id}")
    click.echo(f"  Version:    {packet.version}")
    click.echo(f"  Status:     {packet.status}")
    click.echo(f"  Priority:   {packet.metadata.priority}")
    click.echo(f"  Source:     {packet.metadata.source_agent.name} ({packet.metadata.source_agent.id})")
    click.echo(f"  Target:     {packet.metadata.target_agent.name} ({packet.metadata.target_agent.id})")
    click.echo(f"  Summary:    {packet.context.summary[:100]}{'...' if len(packet.context.summary) > 100 else ''}")
    if packet.metadata.tags:
        click.echo(f"  Tags:       {', '.join(packet.metadata.tags)}")
    click.echo(f"  Created:    {packet.created_at}")
    click.echo(f"  Updated:    {packet.updated_at}")
    if packet.hitl:
        click.echo(f"  HITL:       required={packet.hitl.required}, reason={packet.hitl.reason}")
