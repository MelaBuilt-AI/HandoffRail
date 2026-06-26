"""HandoffRail CLI — Shared utilities for Click commands.

Contains client factory and output formatting helpers.
Imported by cli.main and command modules to avoid circular imports.
"""

from __future__ import annotations

import json

import click


def get_client(ctx: click.Context):
    """Build an SDK client from Click context options.

    This function is called dynamically (not bound at import time),
    so mocking cli.utils.get_client will work correctly in tests.
    """
    from handoffrail.sdk import HandoffRailClient

    server_url = ctx.obj["server_url"]
    api_key = ctx.obj["api_key"]
    if not api_key:
        raise click.ClickException(
            "API key required. Use --api-key or set HANDOFFRAIL_API_KEY env var."
        )
    return HandoffRailClient(base_url=server_url, api_key=api_key)


def format_output(ctx: click.Context, data, default_formatter=None):
    """Format output based on --format flag (table or json)."""
    fmt = ctx.obj.get("format", "table")
    if fmt == "json":
        if hasattr(data, "to_dict"):
            click.echo(json.dumps(data.to_dict(), indent=2, default=str))
        elif isinstance(data, list):
            click.echo(json.dumps(
                [d.to_dict() if hasattr(d, "to_dict") else d for d in data],
                indent=2, default=str,
            ))
        elif isinstance(data, dict):
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            click.echo(json.dumps(data, indent=2, default=str))
    elif default_formatter and callable(default_formatter):
        default_formatter(data)
    else:
        click.echo(data)
