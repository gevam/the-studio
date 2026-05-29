"""Sandbox runner: executes commands in the verification Docker container."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

# The sandbox container name matches docker-compose.yml
SANDBOX_CONTAINER = "the-studio-sandbox-1"
SANDBOX_TIMEOUT_SECONDS = 300


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


class SandboxRunner:
    """Runs commands inside the verification sandbox container via docker exec."""

    def __init__(
        self,
        container: str = SANDBOX_CONTAINER,
        timeout: int = SANDBOX_TIMEOUT_SECONDS,
    ) -> None:
        self._container = container
        self._timeout = timeout

    async def run(self, command: str, *, workdir: str = "/project") -> SandboxResult:
        """Execute a shell command inside the sandbox container."""
        cmd = [
            "docker", "exec",
            "--workdir", workdir,
            self._container,
            "bash", "-c", command,
        ]
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "sandbox_timeout",
                command=command[:100],
                timeout=self._timeout,
            )
            return SandboxResult(
                exit_code=124,
                stdout="",
                stderr=f"Command timed out after {self._timeout}s",
                duration_ms=duration_ms,
            )
        except FileNotFoundError:
            duration_ms = int((time.monotonic() - start) * 1000)
            return SandboxResult(
                exit_code=127,
                stdout="",
                stderr="docker command not found — is Docker installed?",
                duration_ms=duration_ms,
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        result = SandboxResult(
            exit_code=proc.returncode,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            duration_ms=duration_ms,
        )
        logger.info(
            "sandbox_run",
            command=command[:80],
            exit_code=result.exit_code,
            duration_ms=duration_ms,
        )
        return result

    async def is_alive(self) -> bool:
        """Check if the sandbox container is running."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "inspect", "--format", "{{.State.Running}}", self._container,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            return stdout.decode().strip() == "true"
        except Exception:
            return False
