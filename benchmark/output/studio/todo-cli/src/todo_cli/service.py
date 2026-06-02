import uuid
from datetime import datetime, timezone

from todo_cli.models import Todo
from todo_cli.repository import TodoRepository


class TodoService:
    def __init__(self, repo: TodoRepository) -> None:
        self._repo = repo

    def add(self, title: str) -> Todo:
        if not title or not title.strip():
            raise ValueError("title cannot be empty")
        if len(title) > 256:
            raise ValueError("title exceeds 256 characters")
        todo = Todo(
            id=str(uuid.uuid4()),
            title=title.strip(),
            completed=False,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._repo.add(todo)
        return todo

    def list_all(self) -> list[Todo]:
        return self._repo.list()

    def complete(self, id_prefix: str) -> Todo:
        todo = self._resolve_by_prefix(id_prefix)
        todo.completed = True
        self._repo.update(todo)
        return todo

    def remove(self, id_prefix: str) -> Todo:
        todo = self._resolve_by_prefix(id_prefix)
        self._repo.remove(todo.id)
        return todo

    def _resolve_by_prefix(self, id_prefix: str) -> Todo:
        matches = [t for t in self._repo.list() if t.id.startswith(id_prefix)]
        if len(matches) == 0:
            raise ValueError(f"no todo with id {id_prefix}")
        if len(matches) > 1:
            raise ValueError(f"prefix matches {len(matches)} todos, be more specific")
        return matches[0]
