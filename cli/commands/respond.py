"""HandoffRail CLI — respond command. Respond to a HITL checkpoint."""

from __future__ import annotations

import click

import cli.utils as utils
from cli.commands.errors import handle_error


@click.command("respond")
@click.argument("packet_id")
@click.option("--response", "-r", required=True, help="The human's response text.")
@click.option("--responded-by", "-b", required=True, help="Identifier of the human responder.")
@click.option("--notes", "-n", help="Optional additional notes.")
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.pass_context
def respond_cmd(
    ctx: click.Context,
    packet_id: str,
    response: str,
    responded_by: str,
    notes: str | None,
    output_format: str,
) -> None:
    """Submit a human response to a HITL checkpoint."""
    ctx.obj["format"] = output_format
    client = utils.get_client(ctx)
    try:
        result = client.respond_to_hitl(
            packet_id,
            response=response,
            responded_by=responded_by,
            notes=notes,
        )
        utils.format_output(ctx, result, _format_respond_table)
    except Exception as exc:
        handle_error(exc, ctx, resource=packet_id)


def _format_respond_table(packet) -> None:
    """Pretty-print a packet after HITL response."""
    click.echo("  HITL response submitted successfully!")
    click.echo(f"  Packet ID:  {packet.id}")
    click.echo(f"  Status:     {packet.status}")
    if packet.hitl:
        click.echo(f"  HITL response: {packet.hitl.response}")
        click.echo(f"  Responded by:  {packet.hitl.responded_by}")
    click.echo(f"  Updated:    {packet.updated_at}")
