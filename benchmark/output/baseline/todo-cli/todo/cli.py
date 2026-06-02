from __future__ import annotations

import sys
from pathlib import Path

import click

from .manager import TodoManager
from .models import TodoStatus
from .storage import Storage

DEFAULT_DB = Path.home() / ".todo" / "todos.json"

STATUS_SYMBOL = {TodoStatus.PENDING: "[ ]", TodoStatus.DONE: "[x]"}


@click.group()
@click.option("--db", default=str(DEFAULT_DB), show_default=True, help="Path to storage file.")
@click.pass_context
def cli(ctx: click.Context, db: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["manager"] = TodoManager(Storage(db))


@cli.command()
@click.argument("text")
@click.pass_context
def add(ctx: click.Context, text: str) -> None:
    """Add a new todo."""
    manager: TodoManager = ctx.obj["manager"]
    todo = manager.add(text)
    click.echo(f"Added [{todo.id}]: {todo.text}")


@cli.command(name="list")
@click.pass_context
def list_todos(ctx: click.Context) -> None:
    """List all todos."""
    manager: TodoManager = ctx.obj["manager"]
    todos = manager.list()
    if not todos:
        click.echo("No todos yet.")
        return
    for todo in todos:
        symbol = STATUS_SYMBOL[todo.status]
        click.echo(f"  {symbol} [{todo.id}] {todo.text}")


@cli.command()
@click.argument("todo_id", type=int)
@click.pass_context
def complete(ctx: click.Context, todo_id: int) -> None:
    """Mark a todo as done."""
    manager: TodoManager = ctx.obj["manager"]
    try:
        todo = manager.complete(todo_id)
    except KeyError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Done [{todo.id}]: {todo.text}")


@cli.command()
@click.argument("todo_id", type=int)
@click.pass_context
def remove(ctx: click.Context, todo_id: int) -> None:
    """Remove a todo."""
    manager: TodoManager = ctx.obj["manager"]
    try:
        manager.remove(todo_id)
    except KeyError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Removed [{todo_id}]")
