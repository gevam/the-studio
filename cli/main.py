"""Studio CLI — Typer-based, full parity with REST API (§6.3).

Sprint 0: config show, session list.
"""

import json
import sys
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()
app = typer.Typer(
    name="studio",
    help="The Studio — AI-native software development orchestrator",
    no_args_is_help=True,
)

config_app = typer.Typer(help="Configuration management")
session_app = typer.Typer(help="Session management")

app.add_typer(config_app, name="config")
app.add_typer(session_app, name="session")


# ── Config commands ──────────────────────────────────────────────────────────

@config_app.command("show")
def config_show(
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Show current configuration."""
    from studio.config import settings

    data = {
        "database_url": settings.database_url,
        "redis_url": settings.redis_url,
        "environment": settings.environment,
        "log_level": settings.log_level,
        "rest_api_enabled": settings.rest_api_enabled,
        "default_token_budget": settings.default_token_budget,
        "default_cost_budget": settings.default_cost_budget,
        "worker_concurrency": settings.worker_concurrency,
    }

    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return

    table = Table(title="Studio Configuration", show_header=True)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")

    for key, value in data.items():
        # Mask sensitive values
        display = "***" if "key" in key.lower() or "password" in key.lower() else str(value)
        table.add_row(key, display)

    console.print(table)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key to set"),
    value: str = typer.Argument(..., help="Value to set"),
) -> None:
    """Set a configuration value (updates .env.local)."""
    console.print(
        f"[yellow]Warning: config set writes to .env.local. "
        f"Setting {key}={value}[/yellow]"
    )
    # Read existing .env.local, update or append
    env_path = ".env.local"
    try:
        with open(env_path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    env_key = key.upper()
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{env_key}=") or line.startswith(f"#{env_key}="):
            new_lines.append(f"{env_key}={value}\n")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"{env_key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)

    console.print(f"[green]Set {env_key}={value} in {env_path}[/green]")


# ── Session commands ──────────────────────────────────────────────────────────

@session_app.command("list")
def session_list(
    status: Optional[str] = typer.Option(None, help="Filter by status"),
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List sessions."""
    import asyncio

    sessions = asyncio.run(_fetch_sessions(status))

    if as_json:
        typer.echo(json.dumps(sessions, indent=2, default=str))
        return

    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        return

    table = Table(title="Sessions", show_header=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="white")
    table.add_column("Status", style="green")
    table.add_column("Node", style="yellow")
    table.add_column("Created", style="dim")

    for s in sessions:
        status_color = {
            "running": "green",
            "paused": "yellow",
            "error": "red",
            "completed": "blue",
            "awaiting_human": "magenta",
        }.get(s.get("status", ""), "white")
        table.add_row(
            str(s.get("id", ""))[:8] + "...",
            s.get("name", ""),
            f"[{status_color}]{s.get('status', '')}[/{status_color}]",
            s.get("current_node") or "-",
            str(s.get("created_at", ""))[:19],
        )

    console.print(table)


async def _fetch_sessions(status: Optional[str]) -> list[dict]:
    """Fetch sessions from the DB directly (bypasses HTTP for CLI)."""
    try:
        from sqlalchemy import select

        from studio.db.models import Session
        from studio.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            q = select(Session).order_by(Session.created_at.desc()).limit(100)
            if status:
                q = q.where(Session.status == status)
            result = await db.execute(q)
            rows = result.scalars().all()
            return [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "status": row.status,
                    "current_node": row.current_node,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]
    except Exception as exc:
        console.print(f"[red]Error connecting to database: {exc}[/red]")
        return []


if __name__ == "__main__":
    app()
