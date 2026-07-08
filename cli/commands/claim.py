"""HandoffRail CLI — claim command. Claim a packet for processing."""

from __future__ import annotations

import click

import cli.utils as utils
from cli.commands.errors import handle_error


@click.command("claim")
@click.argument("packet_id")
@click.option("--agent-id", default=None, help="Claiming agent's ID (mutually exclusive with --agent).")
@click.option("--agent-name", default=None, help="Claiming agent's name.")
@click.option(
    "--agent", default=None,
    help="Shorthand: set both agent ID and name (e.g. --agent=agent-01). Overrides --agent-name with same value.",
)
@click.option("--framework", help="Framework identifier (e.g. 'langchain', 'crewai').")
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]),
    default=None,
    help="Output format.",
)
@click.pass_context
def claim_cmd(
    ctx: click.Context,
    packet_id: str,
    agent_id: str | None,
    agent_name: str | None,
    agent: str | None,
    framework: str | None,
    output_format: str | None,
) -> None:
    """Claim a handoff packet for processing."""
    # Resolve output format: subcommand flag overrides parent
    if output_format:
        ctx.obj["format"] = output_format

    # Resolve agent identity: --agent shorthand vs --agent-id/--agent-name
    if agent and agent_id:
        raise click.ClickException(
            "--agent is mutually exclusive with --agent-id. "
            "Use --agent=ID for both, or --agent-id=ID --agent-name=NAME separately."
        )
    if agent:
        agent_id = agent
        if not agent_name:
            agent_name = agent
    elif not agent_id:
        raise click.ClickException(
            "Either --agent=ID or --agent-id=ID is required."
        )
    if not agent_name:
        agent_name = agent_id

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
