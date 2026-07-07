"""HandoffRail CLI — hooks commands. Manage webhook hooks."""

from __future__ import annotations

import click

import cli.utils as utils
from cli.commands.errors import handle_error


@click.group("hooks")
def hooks_group() -> None:
    """Manage webhook hooks."""


@hooks_group.command("list")
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.pass_context
def hooks_list(ctx: click.Context, output_format: str) -> None:
    """List all registered webhooks."""
    ctx.obj["format"] = output_format
    client = utils.get_client(ctx)

    try:
        hooks = client.list_webhooks()
        utils.format_output(ctx, hooks, _format_hooks_table)
    except Exception as exc:
        handle_error(exc, ctx)


def _format_hooks_table(hooks: list) -> None:
    """Pretty-print a list of webhooks as a table."""
    if not hooks:
        click.echo("No webhooks registered.")
        return

    click.echo(f"{'ID':<38} {'URL':<50} {'ACTIVE':<8} {'EVENTS'}")
    click.echo("-" * 130)
    for h in hooks:
        events = ", ".join(h.events) if h.events else "all"
        active_str = "✓" if h.active else "✗"
        click.echo(f"{h.id} {h.url:<50} {active_str:<8} {events}")


hooks_cmd = hooks_group
