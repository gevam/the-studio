"""End-to-end test: exercises CLI → service → repository (InMemory) vertical slice."""
import pytest

from todo_cli.cli import main
from todo_cli.repository import InMemoryRepository
from todo_cli.service import TodoService


@pytest.fixture
def service():
    return TodoService(InMemoryRepository())


def test_full_lifecycle(service, capsys):
    # add
    exit_code = main(["add", "Buy milk"], service=service)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Added" in out
    assert "Buy milk" in out

    # list shows the todo
    exit_code = main(["list"], service=service)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Buy milk" in out
    assert "[ ]" in out

    # get the id prefix from the list output: "[ ] <id_prefix>  Buy milk ..."
    id_prefix = out.split()[2]

    # complete
    exit_code = main(["complete", id_prefix], service=service)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Done" in out

    # list shows completed
    main(["list"], service=service)
    out = capsys.readouterr().out
    assert "[x]" in out

    # remove
    exit_code = main(["remove", id_prefix], service=service)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Removed" in out

    # list is empty
    main(["list"], service=service)
    out = capsys.readouterr().out
    assert "No todos yet" in out


def test_add_empty_title_exits_1(service, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["add", ""], service=service)
    assert exc.value.code == 1


def test_complete_unknown_id_exits_1(service, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["complete", "nonexistent"], service=service)
    assert exc.value.code == 1


def test_remove_unknown_id_exits_1(service, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["remove", "nonexistent"], service=service)
    assert exc.value.code == 1


def test_no_command_returns_1(service, capsys):
    exit_code = main([], service=service)
    assert exit_code == 1
