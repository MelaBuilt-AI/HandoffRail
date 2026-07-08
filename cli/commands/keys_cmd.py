"""HandoffRail CLI — keys commands. Manage API keys."""

from __future__ import annotations

import click

import cli.utils as utils
from cli.commands.errors import handle_error


@click.group("keys")
def keys_group() -> None:
    """Manage API keys."""


@keys_group.command("create")
@click.option("--name", required=True, help="Human-readable name for the API key.")
@click.option("--tenant-id", default=None, help="Tenant ID (defaults to current key's tenant).")
@click.option(
    "--role",
    default="admin",
    type=click.Choice(["admin", "writer", "reader", "agent"]),
    help="Role for the API key (admin, writer, reader, agent). Default admin.",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.pass_context
def keys_create(ctx: click.Context, name: str, tenant_id: str | None, role: str, output_format: str) -> None:
    """Create a new API key.

    The key value is shown only once on creation. Save it securely.
    """
    ctx.obj["format"] = output_format
    client = utils.get_client(ctx)

    try:
        result = client.create_api_key(name=name, tenant_id=tenant_id, role=role)
        utils.format_output(ctx, result, _format_key_table)
    except Exception as exc:
        handle_error(exc, ctx)


@keys_group.command("list")
@click.option(
    "--format", "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.pass_context
def keys_list(ctx: click.Context, output_format: str) -> None:
    """List all API keys for the current tenant.

    The actual key values are not shown in the list.
    """
    ctx.obj["format"] = output_format
    client = utils.get_client(ctx)

    try:
        keys = client.list_api_keys()
        utils.format_output(ctx, keys, _format_keys_table)
    except Exception as exc:
        handle_error(exc, ctx)


def _format_key_table(key) -> None:
    """Pretty-print a single API key."""
    click.echo(f"  ID:         {key.id}")
    click.echo(f"  Name:       {key.name}")
    click.echo(f"  Prefix:     {key.key_prefix}")
    click.echo(f"  Role:       {key.role}")
    click.echo(f"  Tenant:     {key.tenant_id}")
    click.echo(f"  Revoked:    {key.revoked}")
    click.echo(f"  Created:    {key.created_at}")
    if key.key:
        click.echo(f"  Key:        {key.key}")
        click.echo("")
        click.echo("  ⚠️  Save this key securely. It will not be shown again.")


def _format_keys_table(keys: list) -> None:
    """Pretty-print a list of API keys as a table."""
    if not keys:
        click.echo("No API keys found.")
        return

    click.echo(f"{'ID':<38} {'NAME':<18} {'ROLE':<8} {'PREFIX':<10} {'REVOKED':<8} {'CREATED'}")
    click.echo("-" * 110)
    for k in keys:
        revoked_str = "✓" if k.revoked else "─"
        click.echo(f"{k.id} {k.name:<18} {k.role:<8} {k.key_prefix:<10} {revoked_str:<8} {k.created_at}")


keys_cmd = keys_group
