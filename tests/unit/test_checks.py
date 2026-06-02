"""Unit tests for the deterministic verification checks.

Regression: run_secrets_check / run_pii_check piped grep into `head ... || echo`,
so the pipeline exit code was always head's (0) and the pass condition was never
true — the checks failed even on clean code, so full verification could never
pass and the friction loop always hit max_design_iterations.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from studio.verification.checks import run_pii_check, run_secrets_check


@dataclass
class _Result:
    exit_code: int
    stdout: str
    stderr: str = ""
    duration_ms: int = 1


class _FakeSandbox:
    """Records the command and returns a canned grep result."""

    def __init__(self, exit_code: int, stdout: str = "") -> None:
        self._exit_code = exit_code
        self._stdout = stdout
        self.last_command = ""

    async def run(self, command: str, *, workdir: str = "/project") -> _Result:
        self.last_command = command
        return _Result(exit_code=self._exit_code, stdout=self._stdout)


@pytest.mark.asyncio
async def test_secrets_check_passes_when_grep_finds_nothing():
    # grep exit code 1 == no matches == clean
    sandbox = _FakeSandbox(exit_code=1, stdout="")
    result = await run_secrets_check(sandbox, "/project")
    assert result.passed


@pytest.mark.asyncio
async def test_secrets_check_fails_when_secret_found():
    sandbox = _FakeSandbox(exit_code=0, stdout="cfg.py:3:API_KEY = 'sk-deadbeef12345678'")
    result = await run_secrets_check(sandbox, "/project")
    assert not result.passed
    assert "API_KEY" in result.output


@pytest.mark.asyncio
async def test_secrets_check_excludes_vendored_dirs():
    sandbox = _FakeSandbox(exit_code=1)
    await run_secrets_check(sandbox, "/project")
    assert "--exclude-dir=.venv" in sandbox.last_command
    assert "--exclude-dir=site-packages" in sandbox.last_command


@pytest.mark.asyncio
async def test_pii_check_passes_when_grep_finds_nothing():
    sandbox = _FakeSandbox(exit_code=1, stdout="")
    result = await run_pii_check(sandbox, "/project")
    assert result.passed


@pytest.mark.asyncio
async def test_pii_check_fails_when_pii_logged():
    sandbox = _FakeSandbox(exit_code=0, stdout="app.py:9:logger.info(user.email)")
    result = await run_pii_check(sandbox, "/project")
    assert not result.passed
    assert "--exclude-dir=.venv" in sandbox.last_command
