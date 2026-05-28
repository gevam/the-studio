import dataclasses
import json
import shutil
from pathlib import Path
from typing import Protocol

from todo_cli.models import Todo


class TodoRepository(Protocol):
    def list(self) -> list[Todo]: ...
    def add(self, todo: Todo) -> None: ...
    def remove(self, id: str) -> None: ...
    def update(self, todo: Todo) -> None: ...


class InMemoryRepository:
    def __init__(self, todos: list[Todo] | None = None) -> None:
        self._todos: list[Todo] = list(todos) if todos else []

    def list(self) -> list[Todo]:
        return list(self._todos)

    def add(self, todo: Todo) -> None:
        self._todos.append(todo)

    def remove(self, id: str) -> None:
        self._todos = [t for t in self._todos if t.id != id]

    def update(self, todo: Todo) -> None:
        self._todos = [todo if t.id == todo.id else t for t in self._todos]


class FileRepository:
    _SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self._path = path

    def _load(self) -> list[Todo]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text())
            return [Todo(**item) for item in data.get("todos", [])]
        except (json.JSONDecodeError, TypeError, KeyError):
            backup = self._path.with_suffix(".json.bak")
            shutil.copy2(self._path, backup)
            return []

    def _save(self, todos: list[Todo]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self._SCHEMA_VERSION,
            "todos": [dataclasses.asdict(t) for t in todos],
        }
        self._path.write_text(json.dumps(payload, indent=2))

    def list(self) -> list[Todo]:
        return self._load()

    def add(self, todo: Todo) -> None:
        todos = self._load()
        todos.append(todo)
        self._save(todos)

    def remove(self, id: str) -> None:
        todos = [t for t in self._load() if t.id != id]
        self._save(todos)

    def update(self, todo: Todo) -> None:
        todos = [todo if t.id == todo.id else t for t in self._load()]
        self._save(todos)
