"""HandoffRail CLI — Shared error handling utilities."""

from __future__ import annotations

import click


def handle_error(exc: Exception, ctx: click.Context, resource: str = "") -> None:
    """Map SDK exceptions to Click errors with user-friendly messages.

    Raises click.ClickException with a clean message. Raw tracebacks are
    hidden unless --verbose is set.
    """
    from handoffrail.sdk.exceptions import (
        AuthenticationError,
        ConnectionError,
        HandoffRailError,
        NotFoundError,
        RateLimitError,
        ServerError,
        ValidationError,
    )

    if isinstance(exc, AuthenticationError):
        raise click.ClickException(f"Authentication failed: {exc.message}")
    if isinstance(exc, NotFoundError):
        label = f" {resource}" if resource else ""
        raise click.ClickException(f"Not found:{label} — {exc.message}")
    if isinstance(exc, ValidationError):
        raise click.ClickException(f"Validation error: {exc.message}")
    if isinstance(exc, RateLimitError):
        retry = f" Retry after {exc.retry_after}s." if exc.retry_after else ""
        raise click.ClickException(f"Rate limit exceeded.{retry}")
    if isinstance(exc, ServerError):
        raise click.ClickException(f"Server error: {exc.message}")
    if isinstance(exc, ConnectionError):
        raise click.ClickException(f"Connection error: {exc.message}")
    if isinstance(exc, HandoffRailError):
        raise click.ClickException(f"Error: {exc.message}")
    # Unexpected errors — don't leak tracebacks unless verbose
    if ctx.obj.get("verbose"):
        raise click.ClickException(f"Unexpected error: {exc}")
    raise click.ClickException("An unexpected error occurred. Use --verbose for details.")


def format_packet_brief(packet) -> str:
    """Format a packet as a single summary line for list output."""
    tags_str = f" [{', '.join(packet.metadata.tags)}]" if packet.metadata.tags else ""
    return (
        f"{packet.id}  {packet.status:<16} {packet.metadata.priority:<8} "
        f"{packet.metadata.source_agent.name} → {packet.metadata.target_agent.name}{tags_str}"
    )
