"""HandoffRail CLI — history command. View event trail for a packet."""

from __future__ import annotations

import click

import cli.utils as utils
from cli.commands.errors import handle_error


@click.command("history")
@click.argument("packet_id")
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.pass_context
def history_cmd(ctx: click.Context, packet_id: str, output_format: str) -> None:
    """View the event trail for a handoff packet."""
    ctx.obj["format"] = output_format
    client = utils.get_client(ctx)
    try:
        result = client.get_history(packet_id)
        utils.format_output(ctx, result, _format_history_table)
    except Exception as exc:
        handle_error(exc, ctx, resource=packet_id)


def _format_history_table(result) -> None:
    """Pretty-print packet event history as a table."""
    events = result.events
    if not events:
        click.echo(f"No events found for packet {result.packet_id}.")
        return

    click.echo(f"Event history for packet {result.packet_id}:")
    click.echo()
    click.echo(f"  {'TIMESTAMP':<26} {'EVENT':<22} {'ACTOR':<20} DETAILS")
    click.echo("  " + "-" * 90)

    for event in events:
        details_str = ""
        if event.details:
            items = []
            for k, v in event.details.items():
                val_str = str(v)
                if len(val_str) > 40:
                    val_str = val_str[:37] + "..."
                items.append(f"{k}={val_str}")
            details_str = ", ".join(items)

        ts = str(event.timestamp) if event.timestamp else "N/A"
        click.echo(f"  {ts:<26} {event.event_type:<22} {event.actor:<20} {details_str}")

    click.echo(f"\n  Total events: {len(events)}")
