import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from todo.storage import Storage
from todo.models import Todo, TodoStatus
from todo.manager import TodoManager


# ─── Storage ────────────────────────────────────────────────────────────────

class TestStorage:
    def test_load_returns_empty_list_when_file_missing(self, tmp_path):
        storage = Storage(tmp_path / "todos.json")
        assert storage.load() == []

    def test_save_and_load_roundtrip(self, tmp_path):
        storage = Storage(tmp_path / "todos.json")
        todos = [
            Todo(id=1, text="Buy milk", status=TodoStatus.PENDING),
            Todo(id=2, text="Walk dog", status=TodoStatus.DONE),
        ]
        storage.save(todos)
        loaded = storage.load()
        assert len(loaded) == 2
        assert loaded[0].id == 1
        assert loaded[0].text == "Buy milk"
        assert loaded[0].status == TodoStatus.PENDING
        assert loaded[1].status == TodoStatus.DONE

    def test_save_creates_parent_dirs(self, tmp_path):
        storage = Storage(tmp_path / "deep" / "nested" / "todos.json")
        storage.save([Todo(id=1, text="Task", status=TodoStatus.PENDING)])
        assert (tmp_path / "deep" / "nested" / "todos.json").exists()

    def test_load_corrupted_file_raises(self, tmp_path):
        path = tmp_path / "todos.json"
        path.write_text("not valid json")
        storage = Storage(path)
        with pytest.raises(ValueError, match="corrupt"):
            storage.load()


# ─── Models ─────────────────────────────────────────────────────────────────

class TestTodo:
    def test_todo_defaults_to_pending(self):
        todo = Todo(id=1, text="Read a book")
        assert todo.status == TodoStatus.PENDING

    def test_todo_equality_by_id(self):
        a = Todo(id=1, text="A")
        b = Todo(id=1, text="B")
        assert a == b

    def test_todo_serialise_deserialise(self):
        todo = Todo(id=5, text="Cook dinner", status=TodoStatus.DONE)
        data = todo.to_dict()
        restored = Todo.from_dict(data)
        assert restored.id == 5
        assert restored.text == "Cook dinner"
        assert restored.status == TodoStatus.DONE

    def test_todo_from_dict_invalid_status_raises(self):
        with pytest.raises(ValueError):
            Todo.from_dict({"id": 1, "text": "x", "status": "flying"})


# ─── Manager ────────────────────────────────────────────────────────────────

class TestTodoManager:
    @pytest.fixture
    def manager(self, tmp_path):
        return TodoManager(Storage(tmp_path / "todos.json"))

    def test_add_returns_new_todo(self, manager):
        todo = manager.add("Write tests")
        assert todo.text == "Write tests"
        assert todo.status == TodoStatus.PENDING
        assert todo.id >= 1

    def test_add_multiple_todos_have_unique_ids(self, manager):
        t1 = manager.add("First")
        t2 = manager.add("Second")
        assert t1.id != t2.id

    def test_list_returns_all_todos(self, manager):
        manager.add("A")
        manager.add("B")
        todos = manager.list()
        assert len(todos) == 2

    def test_list_empty_when_no_todos(self, manager):
        assert manager.list() == []

    def test_complete_marks_todo_done(self, manager):
        todo = manager.add("Finish report")
        manager.complete(todo.id)
        updated = manager.list()[0]
        assert updated.status == TodoStatus.DONE

    def test_complete_nonexistent_id_raises(self, manager):
        with pytest.raises(KeyError):
            manager.complete(999)

    def test_remove_deletes_todo(self, manager):
        todo = manager.add("Temporary task")
        manager.remove(todo.id)
        assert manager.list() == []

    def test_remove_nonexistent_id_raises(self, manager):
        with pytest.raises(KeyError):
            manager.remove(999)

    def test_todos_persist_across_manager_instances(self, tmp_path):
        path = tmp_path / "todos.json"
        m1 = TodoManager(Storage(path))
        m1.add("Persist me")
        m2 = TodoManager(Storage(path))
        assert len(m2.list()) == 1
        assert m2.list()[0].text == "Persist me"

    def test_ids_do_not_reset_after_reload(self, tmp_path):
        path = tmp_path / "todos.json"
        m1 = TodoManager(Storage(path))
        t1 = m1.add("First")
        m2 = TodoManager(Storage(path))
        t2 = m2.add("Second")
        assert t2.id != t1.id

    def test_complete_already_done_todo_is_idempotent(self, manager):
        todo = manager.add("Already done")
        manager.complete(todo.id)
        manager.complete(todo.id)  # should not raise
        assert manager.list()[0].status == TodoStatus.DONE


# ─── CLI (integration) ───────────────────────────────────────────────────────

class TestCLI:
    """Light integration tests for the CLI entry point."""

    @pytest.fixture
    def db(self, tmp_path):
        return str(tmp_path / "todos.json")

    def _run(self, args, db):
        from click.testing import CliRunner
        from todo.cli import cli
        runner = CliRunner()
        return runner.invoke(cli, ["--db", db] + args)

    def test_add_prints_confirmation(self, db):
        result = self._run(["add", "Buy groceries"], db)
        assert result.exit_code == 0
        assert "Buy groceries" in result.output

    def test_list_shows_todos(self, db):
        self._run(["add", "Task one"], db)
        self._run(["add", "Task two"], db)
        result = self._run(["list"], db)
        assert "Task one" in result.output
        assert "Task two" in result.output

    def test_list_empty_message_when_no_todos(self, db):
        result = self._run(["list"], db)
        assert result.exit_code == 0
        assert "No todos" in result.output

    def test_complete_marks_done_in_list(self, db):
        add_result = self._run(["add", "Finish it"], db)
        # extract id from output "Added [1]: Finish it"
        todo_id = _parse_id(add_result.output)
        self._run(["complete", str(todo_id)], db)
        result = self._run(["list"], db)
        assert "[x]" in result.output

    def test_remove_deletes_from_list(self, db):
        add_result = self._run(["add", "Remove me"], db)
        todo_id = _parse_id(add_result.output)
        self._run(["remove", str(todo_id)], db)
        result = self._run(["list"], db)
        assert "Remove me" not in result.output

    def test_complete_unknown_id_exits_nonzero(self, db):
        result = self._run(["complete", "999"], db)
        assert result.exit_code != 0

    def test_remove_unknown_id_exits_nonzero(self, db):
        result = self._run(["remove", "999"], db)
        assert result.exit_code != 0


def _parse_id(output: str) -> int:
    """Extract the id from CLI output like 'Added [3]: text'."""
    import re
    match = re.search(r"\[(\d+)\]", output)
    assert match, f"Could not parse id from: {output!r}"
    return int(match.group(1))
