"""HandoffRail CLI — get command. Inspect a packet by ID."""

from __future__ import annotations

import click

import cli.utils as utils
from cli.commands.errors import handle_error


@click.command("get")
@click.argument("packet_id")
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.pass_context
def get_cmd(ctx: click.Context, packet_id: str, output_format: str) -> None:
    """Inspect a handoff packet by ID."""
    ctx.obj["format"] = output_format
    client = utils.get_client(ctx)
    try:
        packet = client.get_packet(packet_id)
        utils.format_output(ctx, packet, _format_packet_table)
    except Exception as exc:
        handle_error(exc, ctx, resource=packet_id)


def _format_packet_table(packet) -> None:
    """Pretty-print a packet as a table."""
    click.echo(f"  ID:         {packet.id}")
    click.echo(f"  Version:    {packet.version}")
    if packet.parent_packet_id:
        click.echo(f"  Parent:     {packet.parent_packet_id}")
    click.echo(f"  Status:     {packet.status}")
    click.echo(f"  Priority:   {packet.metadata.priority}")
    click.echo(f"  Source:     {packet.metadata.source_agent.name} ({packet.metadata.source_agent.id})")
    click.echo(f"  Target:     {packet.metadata.target_agent.name} ({packet.metadata.target_agent.id})")
    click.echo(f"  Summary:    {packet.context.summary[:200]}{'...' if len(packet.context.summary) > 200 else ''}")
    if packet.metadata.tags:
        click.echo(f"  Tags:       {', '.join(packet.metadata.tags)}")
    click.echo(f"  Created:    {packet.created_at}")
    click.echo(f"  Updated:    {packet.updated_at}")

    if packet.context.conversation_state:
        click.echo(f"  Context entries: {len(packet.context.conversation_state)}")
    if packet.context.artifacts:
        click.echo(f"  Artifacts:      {len(packet.context.artifacts)}")
    if packet.context.custom:
        click.echo(f"  Custom keys:    {', '.join(packet.context.custom.keys())}")

    if packet.decisions:
        click.echo(f"  Decisions:  {len(packet.decisions)}")
        for d in packet.decisions:
            click.echo(f"    - {d.decision} (by {d.decided_by or 'unknown'})")

    actions = packet.actions
    if actions.pending:
        click.echo(f"  Pending actions:  {len(actions.pending)}")
    if actions.completed:
        click.echo(f"  Completed actions: {len(actions.completed)}")
    if actions.failed:
        click.echo(f"  Failed actions:    {len(actions.failed)}")

    if packet.dependencies:
        click.echo(f"  Dependencies: {len(packet.dependencies)}")

    if packet.hitl:
        hitl = packet.hitl
        click.echo(f"  HITL:        required={hitl.required}, reason={hitl.reason}")
        if hitl.response:
            click.echo(f"  HITL response: {hitl.response}")
            if hitl.responded_by:
                click.echo(f"  Responded by:  {hitl.responded_by}")
