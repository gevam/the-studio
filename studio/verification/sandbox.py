"""Sandbox runner: executes verification commands in an ephemeral Docker container.

Each run launches a fresh `docker run` with the project bind-mounted at /project,
network disabled (`--network none`), and CPU/memory capped per §5. Running the build
on the host while verifying in a shared persistent volume meant the sandbox never saw
the generated project; bind-mounting the real project_path is what lets verification
actually evaluate what the build agent produced.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

# Image built from ./sandbox (docker build -t the-studio-sandbox:latest ./sandbox).
SANDBOX_IMAGE = os.environ.get("STUDIO_SANDBOX_IMAGE", "the-studio-sandbox:latest")
SANDBOX_TIMEOUT_SECONDS = 300
SANDBOX_MEMORY = "2g"
SANDBOX_CPUS = "2"
# Mount point inside the container; checks default their workdir to this.
SANDBOX_MOUNT = "/project"


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
    """Runs commands inside an ephemeral, network-isolated verification container.

    The host ``project_path`` is bind-mounted read-write at ``/project`` for the
    lifetime of each command, so checks operate on the freshly built project.
    """

    def __init__(
        self,
        project_path: str | None = None,
        *,
        image: str = SANDBOX_IMAGE,
        timeout: int = SANDBOX_TIMEOUT_SECONDS,
    ) -> None:
        # Absolute path required for a bind mount.
        self._project_path = os.path.abspath(project_path) if project_path else None
        self._image = image
        self._timeout = timeout

    async def run(self, command: str, *, workdir: str = SANDBOX_MOUNT) -> SandboxResult:
        """Execute a shell command inside a fresh sandbox container."""
        if not self._project_path:
            return SandboxResult(
                exit_code=126,
                stdout="",
                stderr="SandboxRunner has no project_path to mount",
                duration_ms=0,
            )

        cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--memory", SANDBOX_MEMORY,
            "--cpus", SANDBOX_CPUS,
            "--volume", f"{self._project_path}:{SANDBOX_MOUNT}",
            "--workdir", workdir,
            "--entrypoint", "bash",
            self._image,
            "-c", command,
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
        except TimeoutError:
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
            exit_code=proc.returncode if proc.returncode is not None else -1,
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
        """Check that Docker is reachable and the sandbox image is available."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "image", "inspect", self._image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            return proc.returncode == 0
        except Exception:
            return False
