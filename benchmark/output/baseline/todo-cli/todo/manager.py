from __future__ import annotations

from .models import Todo, TodoStatus
from .storage import Storage


class TodoManager:
    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._todos: list[Todo] = storage.load()

    def list(self) -> list[Todo]:
        return list(self._todos)

    def add(self, text: str) -> Todo:
        next_id = max((t.id for t in self._todos), default=0) + 1
        todo = Todo(id=next_id, text=text)
        self._todos.append(todo)
        self._storage.save(self._todos)
        return todo

    def complete(self, todo_id: int) -> Todo:
        todo = self._find(todo_id)
        todo.status = TodoStatus.DONE
        self._storage.save(self._todos)
        return todo

    def remove(self, todo_id: int) -> None:
        todo = self._find(todo_id)
        self._todos.remove(todo)
        self._storage.save(self._todos)

    def _find(self, todo_id: int) -> Todo:
        for todo in self._todos:
            if todo.id == todo_id:
                return todo
        raise KeyError(f"No todo with id {todo_id}")
