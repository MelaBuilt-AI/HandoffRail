"""HandoffRail CLI — claim command. Claim a packet for processing."""

from __future__ import annotations

import click

import cli.utils as utils
from cli.commands.errors import handle_error


@click.command("claim")
@click.argument("packet_id")
@click.option("--agent-id", required=True, help="Claiming agent's ID.")
@click.option("--agent-name", required=True, help="Claiming agent's name.")
@click.option("--framework", help="Framework identifier (e.g. 'langchain', 'crewai').")
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.pass_context
def claim_cmd(
    ctx: click.Context,
    packet_id: str,
    agent_id: str,
    agent_name: str,
    framework: str | None,
    output_format: str,
) -> None:
    """Claim a handoff packet for processing."""
    ctx.obj["format"] = output_format
    client = utils.get_client(ctx)
    try:
        result = client.claim_packet(
            packet_id,
            agent_id=agent_id,
            agent_name=agent_name,
            framework=framework,
        )
        utils.format_output(ctx, result, _format_claim_table)
    except Exception as exc:
        handle_error(exc, ctx, resource=packet_id)


def _format_claim_table(packet) -> None:
    """Pretty-print a claimed packet."""
    click.echo("  Packet claimed successfully!")
    click.echo(f"  ID:         {packet.id}")
    click.echo(f"  Status:     {packet.status}")
    click.echo(f"  Claimed by: {packet.metadata.source_agent.name} ({packet.metadata.source_agent.id})")
    click.echo(f"  Updated:    {packet.updated_at}")
