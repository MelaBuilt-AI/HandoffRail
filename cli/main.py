"""HandoffRail CLI — Main Click group and entry point."""

from __future__ import annotations

import logging
import os
import sys

import click

from cli.commands.create import create_cmd
from cli.commands.get import get_cmd
from cli.commands.list import list_cmd
from cli.commands.claim import claim_cmd
from cli.commands.respond import respond_cmd
from cli.commands.history import history_cmd
from cli.commands.serve import serve_cmd


@click.group()
@click.option(
    "--server-url",
    envvar="HANDOFFRAIL_URL",
    default="http://localhost:8080/api/v1",
    help="HandoffRail API base URL.",
    show_default=True,
)
@click.option(
    "--api-key",
    envvar="HANDOFFRAIL_API_KEY",
    default=None,
    help="API key for authentication. Falls back to HANDOFFRAIL_API_KEY env var.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Enable verbose (DEBUG) logging.",
)
@click.option(
    "--quiet", "-q",
    is_flag=True,
    default=False,
    help="Suppress all output except errors.",
)
@click.version_option(version="0.1.0", prog_name="handoffrail")
@click.pass_context
def cli(
    ctx: click.Context,
    server_url: str,
    api_key: str | None,
    verbose: bool,
    quiet: bool,
) -> None:
    """HandoffRail — Session-continuity middleware for multi-agent AI workflows."""
    ctx.ensure_object(dict)
    ctx.obj["server_url"] = server_url.rstrip("/")
    ctx.obj["api_key"] = api_key or os.environ.get("HANDOFFRAIL_API_KEY", "")

    # Configure logging
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet


# Register subcommands
cli.add_command(create_cmd, "create")
cli.add_command(get_cmd, "get")
cli.add_command(list_cmd, "list")
cli.add_command(claim_cmd, "claim")
cli.add_command(respond_cmd, "respond")
cli.add_command(history_cmd, "history")
cli.add_command(serve_cmd, "serve")
