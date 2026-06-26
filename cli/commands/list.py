"""HandoffRail CLI — list command. List packets with filters."""

from __future__ import annotations

import click

import cli.utils as utils
from cli.commands.errors import handle_error


@click.command("list")
@click.option("--status", help="Filter by status (comma-separated, e.g. 'created,claimed').")
@click.option("--source-agent", help="Filter by source agent ID.")
@click.option("--target-agent", help="Filter by target agent ID.")
@click.option("--tags", help="Filter by tags (comma-separated, all must match).")
@click.option("--priority", help="Filter by priority (low, normal, high, critical).")
@click.option("--created-after", help="Filter packets created after (ISO 8601 datetime).")
@click.option("--created-before", help="Filter packets created before (ISO 8601 datetime).")
@click.option("--limit", type=int, default=20, help="Max results per page (1-200).", show_default=True)
@click.option("--offset", type=int, default=0, help="Pagination offset.", show_default=True)
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    status: str | None,
    source_agent: str | None,
    target_agent: str | None,
    tags: str | None,
    priority: str | None,
    created_after: str | None,
    created_before: str | None,
    limit: int,
    offset: int,
    output_format: str,
) -> None:
    """List handoff packets with optional filters."""
    ctx.obj["format"] = output_format
    client = utils.get_client(ctx)
    try:
        result = client.list_packets(
            status=status,
            source_agent=source_agent,
            target_agent=target_agent,
            tags=tags,
            priority=priority,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
            offset=offset,
        )
        utils.format_output(ctx, result, _format_list_table)
    except Exception as exc:
        handle_error(exc, ctx)


def _format_list_table(result) -> None:
    """Pretty-print a packet list as a table."""
    packets = result.packets
    if not packets:
        click.echo("No packets found.")
        return

    click.echo(f"{'ID':<38} {'STATUS':<16} {'PRIORITY':<8} {'SOURCE → TARGET'}")
    click.echo("-" * 90)
    for pkt in packets:
        src = pkt.metadata.source_agent.name
        tgt = pkt.metadata.target_agent.name
        click.echo(f"{pkt.id} {pkt.status:<16} {pkt.metadata.priority:<8} {src} → {tgt}")

    click.echo(f"\nShowing {len(packets)} of {result.total} (offset={result.offset}, limit={result.limit})")
