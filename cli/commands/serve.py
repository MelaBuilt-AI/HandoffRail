"""HandoffRail CLI — serve command. Start the API server (dev mode)."""

from __future__ import annotations

import click


@click.command("serve")
@click.option("--host", default="0.0.0.0", help="Bind host.", show_default=True)
@click.option("--port", type=int, default=8080, help="Bind port.", show_default=True)
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload for development.")
@click.pass_context
def serve_cmd(ctx: click.Context, host: str, port: int, reload: bool) -> None:
    """Start the HandoffRail API server (development mode).

    Uses uvicorn to run the FastAPI application. For production,
    use a proper ASGI server with workers.
    """
    try:
        import uvicorn
    except ImportError:
        raise click.ClickException(
            "uvicorn is required to run the server. Install it with: pip install uvicorn"
        )

    click.echo(f"Starting HandoffRail API server on {host}:{port}")
    if reload:
        click.echo("  Auto-reload enabled (development mode)")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info" if ctx.obj.get("verbose") else "warning",
    )
