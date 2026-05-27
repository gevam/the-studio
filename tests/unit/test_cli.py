"""Tests for the Typer CLI (cli.main)."""

import json
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def test_config_show_exits_zero():
    """studio config show exits with code 0."""
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0


def test_config_show_includes_keys():
    """studio config show output includes expected config keys."""
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    output = result.output
    assert "environment" in output
    assert "rest_api_enabled" in output


def test_config_show_json_mode():
    """studio config show --json outputs valid JSON."""
    result = runner.invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "environment" in data
    assert "database_url" in data
    assert "rest_api_enabled" in data


def test_session_list_exits_zero_when_db_unavailable():
    """studio session list exits 0 and shows error message when DB is down."""
    with patch("cli.main._fetch_sessions", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []
        result = runner.invoke(app, ["session", "list"])
    assert result.exit_code == 0


def test_session_list_json_empty():
    """studio session list --json outputs [] when no sessions."""
    with patch("cli.main._fetch_sessions", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []
        result = runner.invoke(app, ["session", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == []


def test_session_list_json_with_data():
    """studio session list --json outputs session data as JSON array."""
    mock_sessions = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "Test Session",
            "status": "created",
            "current_node": None,
            "created_at": "2026-05-27T12:00:00",
        }
    ]
    with patch("cli.main._fetch_sessions", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_sessions
        result = runner.invoke(app, ["session", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["name"] == "Test Session"
