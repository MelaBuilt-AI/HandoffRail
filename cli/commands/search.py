"""HandoffRail CLI — search command. Full-text search packets."""

from __future__ import annotations

import click
from handoffrail.sdk.models import SearchOptions

import cli.utils as utils
from cli.commands.errors import handle_error


@click.command("search")
@click.argument("query")
@click.option("--status", help="Filter by status (comma-separated).")
@click.option("--priority", help="Filter by priority (low, normal, high, critical).")
@click.option("--limit", type=int, default=20, help="Max results (1-200).", show_default=True)
@click.option("--offset", type=int, default=0, help="Pagination offset.", show_default=True)
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.pass_context
def search_cmd(
    ctx: click.Context,
    query: str,
    status: str | None,
    priority: str | None,
    limit: int,
    offset: int,
    output_format: str,
) -> None:
    """Full-text search handoff packets by summary and context.

    QUERY is the search term (min 2 characters).
    """
    if len(query.strip()) < 2:
        raise click.ClickException("Search query must be at least 2 characters.")

    ctx.obj["format"] = output_format
    client = utils.get_client(ctx)

    options = SearchOptions(limit=limit, offset=offset)
    if status:
        options.status = status
    if priority:
        options.priority = priority

    try:
        result = client.search_packets(query, options)
        utils.format_output(ctx, result, _format_search_table)
    except Exception as exc:
        handle_error(exc, ctx)


def _format_search_table(result) -> None:
    """Pretty-print search results as a table."""
    packets = result.packets
    if not packets:
        click.echo("No matching packets found.")
        return

    click.echo(f"{'ID':<38} {'STATUS':<16} {'PRIORITY':<8} {'SOURCE → TARGET'}  SUMMARY")
    click.echo("-" * 120)
    for pkt in packets:
        src = pkt.metadata.source_agent.name
        tgt = pkt.metadata.target_agent.name
        summary = pkt.context.summary[:60].replace("\n", " ")
        click.echo(f"{pkt.id} {pkt.status:<16} {pkt.metadata.priority:<8} {src} → {tgt}  {summary}")

    click.echo(f"\nShowing {len(packets)} of {result.total} (offset={result.offset}, limit={result.limit})")
