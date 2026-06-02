"""Unit tests for SandboxRunner.

Regression: verification used to `docker exec` into a persistent container backed
by a shared volume that never contained the host-built project, so every run failed
and the friction loop exhausted max_design_iterations ("Max iterations reached
without verified skeleton"). The runner now bind-mounts the real project_path into
an ephemeral, network-isolated container.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from studio.verification.sandbox import SANDBOX_MOUNT, SandboxRunner


def _fake_proc(returncode=0, stdout=b"ok", stderr=b""):
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return proc


@pytest.mark.asyncio
async def test_run_bind_mounts_project_with_network_isolation():
    captured: dict = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        return _fake_proc()

    runner = SandboxRunner(project_path="/host/proj", image="img:test")
    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        result = await runner.run("pytest -q")

    cmd = captured["cmd"]
    assert cmd[0:2] == ("docker", "run")
    assert "--rm" in cmd
    # network isolation (§5)
    assert "--network" in cmd and cmd[cmd.index("--network") + 1] == "none"
    # resource caps (§5)
    assert "--memory" in cmd and "--cpus" in cmd
    # the REAL project is mounted at /project — this is the fix
    assert "--volume" in cmd
    assert cmd[cmd.index("--volume") + 1] == f"/host/proj:{SANDBOX_MOUNT}"
    # command is handed to bash inside the container
    assert cmd[-3:] == ("img:test", "-c", "pytest -q")
    assert result.succeeded


@pytest.mark.asyncio
async def test_run_uses_absolute_path_for_mount():
    captured: dict = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        return _fake_proc()

    runner = SandboxRunner(project_path="relative/dir")
    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        await runner.run("echo hi")

    mount = captured["cmd"][captured["cmd"].index("--volume") + 1]
    host_path = mount.rsplit(":", 1)[0]
    assert host_path.startswith("/"), "bind-mount source must be absolute"


@pytest.mark.asyncio
async def test_run_without_project_path_fails_cleanly():
    runner = SandboxRunner(project_path=None)
    result = await runner.run("pytest")
    assert not result.succeeded
    assert "no project_path" in result.stderr


@pytest.mark.asyncio
async def test_is_alive_checks_image_availability():
    runner = SandboxRunner(project_path="/p", image="img:test")

    async def ok_exec(*cmd, **kwargs):
        assert cmd[:3] == ("docker", "image", "inspect")
        assert cmd[3] == "img:test"
        return _fake_proc(returncode=0)

    async def missing_exec(*cmd, **kwargs):
        return _fake_proc(returncode=1)

    with patch("asyncio.create_subprocess_exec", side_effect=ok_exec):
        assert await runner.is_alive() is True
    with patch("asyncio.create_subprocess_exec", side_effect=missing_exec):
        assert await runner.is_alive() is False


@pytest.mark.asyncio
async def test_run_handles_missing_docker():
    async def boom(*cmd, **kwargs):
        raise FileNotFoundError

    runner = SandboxRunner(project_path="/p")
    with patch("asyncio.create_subprocess_exec", side_effect=boom):
        result = await runner.run("pytest")
    assert result.exit_code == 127
