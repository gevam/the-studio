import argparse
import sys

from todo_cli.config import get_data_path
from todo_cli.repository import FileRepository
from todo_cli.service import TodoService


def _handle_add(service: TodoService, args: argparse.Namespace) -> None:
    try:
        todo = service.add(args.title)
        print(f"Added [{todo.id[:8]}] {todo.title}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)


def _handle_list(service: TodoService, args: argparse.Namespace) -> None:
    todos = service.list_all()
    if not todos:
        print("No todos yet")
        return
    for todo in todos:
        status = "[x]" if todo.completed else "[ ]"
        date = todo.created_at[:10]
        print(f"{status} {todo.id[:8]}  {todo.title}  (created {date})")


def _handle_complete(service: TodoService, args: argparse.Namespace) -> None:
    try:
        todo = service.complete(args.id)
        print(f"Done [{todo.id[:8]}] {todo.title}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)


def _handle_remove(service: TodoService, args: argparse.Namespace) -> None:
    try:
        todo = service.remove(args.id)
        print(f"Removed [{todo.id[:8]}] {todo.title}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)


def main(argv: list[str] | None = None, service: TodoService | None = None) -> int:
    parser = argparse.ArgumentParser(prog="todo", description="Manage your todos")
    sub = parser.add_subparsers(dest="command")

    add_p = sub.add_parser("add", help="Add a new todo")
    add_p.add_argument("title", help="Todo title")

    sub.add_parser("list", help="List all todos")

    complete_p = sub.add_parser("complete", help="Mark a todo as complete")
    complete_p.add_argument("id", help="Todo id or prefix")

    remove_p = sub.add_parser("remove", help="Remove a todo")
    remove_p.add_argument("id", help="Todo id or prefix")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if service is None:
        service = TodoService(FileRepository(get_data_path()))

    dispatch = {
        "add": _handle_add,
        "list": _handle_list,
        "complete": _handle_complete,
        "remove": _handle_remove,
    }
    dispatch[args.command](service, args)
    return 0
