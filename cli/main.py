"""HandoffRail CLI — Main Click group and entry point."""

from __future__ import annotations

import logging
import sys

import click

from cli.commands.claim import claim_cmd
from cli.commands.create import create_cmd
from cli.commands.get import get_cmd
from cli.commands.history import history_cmd
from cli.commands.hooks import hooks_cmd
from cli.commands.keys_cmd import keys_cmd
from cli.commands.list import list_cmd
from cli.commands.respond import respond_cmd
from cli.commands.search import search_cmd
from cli.commands.serve import serve_cmd
from cli.config import load_config


@click.group()
@click.option(
    "--server-url",
    envvar="HANDOFFRAIL_URL",
    default=None,
    help="HandoffRail API base URL. Falls back to HANDOFFRAIL_URL env, then ~/.handoffrail.toml.",
    show_default=False,
)
@click.option(
    "--api-key",
    envvar="HANDOFFRAIL_API_KEY",
    default=None,
    help="API key for authentication. Falls back to HANDOFFRAIL_API_KEY env, then ~/.handoffrail.toml.",
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
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]),
    default=None,
    help="Output format (can be overridden by subcommand --format).",
)
@click.version_option(version="0.2.0", prog_name="handoffrail")
@click.pass_context
def cli(
    ctx: click.Context,
    server_url: str | None,
    api_key: str | None,
    verbose: bool,
    quiet: bool,
    output_format: str | None,
) -> None:
    """HandoffRail — Session-continuity middleware for multi-agent AI workflows."""
    ctx.ensure_object(dict)

    # Load config file (~/.handoffrail.toml) as fallback
    config = load_config()

    # Resolve server_url: CLI flag > env var (via click default) > config file > hardcoded default
    if not server_url:
        server_url = config.get("server_url", "http://localhost:8080/api/v1")
    ctx.obj["server_url"] = server_url.rstrip("/")

    # Resolve api_key: CLI flag > env var > config file
    if not api_key:
        api_key = config.get("api_key", "")
    ctx.obj["api_key"] = api_key

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
    if output_format:
        ctx.obj["format"] = output_format


# ── Flat subcommands (backward compatible) ───────────────────────────────

cli.add_command(create_cmd, "create")
cli.add_command(get_cmd, "get")
cli.add_command(list_cmd, "list")
cli.add_command(claim_cmd, "claim")
cli.add_command(search_cmd, "search")
cli.add_command(respond_cmd, "respond")
cli.add_command(history_cmd, "history")
cli.add_command(serve_cmd, "serve")

# ── Subcommand groups ────────────────────────────────────────────────────


@click.group("packets")
def packets_group() -> None:
    """Manage handoff packets (list, create, get, claim, search)."""


packets_group.add_command(list_cmd, "list")
packets_group.add_command(create_cmd, "create")
packets_group.add_command(get_cmd, "get")
packets_group.add_command(claim_cmd, "claim")
packets_group.add_command(search_cmd, "search")
cli.add_command(packets_group, "packets")


cli.add_command(hooks_cmd, "hooks")
cli.add_command(keys_cmd, "keys")


# ── Completion command ───────────────────────────────────────────────────


@cli.command("completion")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion_cmd(shell: str) -> None:
    """Generate shell completion script.

    Usage:

        handoffrail completion bash > ~/.handoffrail-completion.sh
        echo "source ~/.handoffrail-completion.sh" >> ~/.bashrc

        handoffrail completion zsh > ~/.handoffrail-completion.zsh
        echo "source ~/.handoffrail-completion.zsh" >> ~/.zshrc

        handoffrail completion fish > ~/.config/fish/completions/handoffrail.fish
    """
    import click.shell_completion as sc

    classes = {
        "bash": sc.BashComplete,
        "zsh": sc.ZshComplete,
        "fish": sc.FishComplete,
    }
    comp = classes[shell](
        cli,
        ctx_args={},
        prog_name="handoffrail",
        complete_var="_HANDOFFRAIL_COMPLETE",
    )
    click.echo(comp.source())


if __name__ == "__main__":
    cli()
