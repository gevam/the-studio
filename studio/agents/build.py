"""Build Agent — orchestrates coding agent to build slices and detect friction."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

import structlog

from studio.ai.llm_client import LLMClient, LLMResponse
from studio.ai.prompt_loader import PromptLoader
from studio.friction.contract import FrictionReport, FrictionCategory, FrictionSeverity, severity_from_score
from studio.friction.detector import analyze_project, CodeQualityMetrics

logger = structlog.get_logger(__name__)


@dataclass
class FileChange:
    path: str
    action: str  # "created" | "modified" | "deleted"
    lines_added: int = 0
    lines_removed: int = 0


@dataclass
class BuildAgentInput:
    session_id: uuid.UUID
    design_digest: str
    slice_name: str
    slice_description: str
    slice_type: str  # "skeleton" | "feature"
    project_name: str
    project_path: str
    stack: str
    iteration: int = 0
    budget_remaining: dict = field(default_factory=dict)


@dataclass
class BuildAgentOutput:
    files_changed: list[FileChange]
    tests_written: list[str]
    friction_items: list[FrictionReport]
    git_commit_hash: Optional[str]
    metrics: CodeQualityMetrics
    tokens_used: int
    cost_usd: float
    build_output: str


@runtime_checkable
class CodingAgent(Protocol):
    async def run(
        self,
        prompt: str,
        project_path: str,
        *,
        timeout_seconds: int = 300,
    ) -> tuple[str, int, float]:
        """Run coding agent with prompt. Returns (output, tokens_used, cost_usd)."""
        ...


class ClaudeCodeAgent:
    """Coding agent using the claude CLI subprocess.

    NOTE: The claude CLI lives on the host at ~/.local/bin/claude.
    It is NOT available inside Docker worker containers.
    For Sprint 1, run benchmarks directly via Python on the host.
    """

    _CLI_CANDIDATES = [
        "/home/geva/.local/bin/claude",
        "claude",
    ]

    def __init__(self) -> None:
        self._cli_path = self._find_cli()

    def _find_cli(self) -> str:
        import shutil

        for candidate in self._CLI_CANDIDATES:
            if candidate == "claude":
                found = shutil.which("claude")
                if found:
                    return found
            else:
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    return candidate
        return "claude"

    async def run(
        self,
        prompt: str,
        project_path: str,
        *,
        timeout_seconds: int = 300,
    ) -> tuple[str, int, float]:
        cmd = [
            self._cli_path,
            "-p",
            "--output-format", "json",
            "--add-dir", project_path,
        ]

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_path,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode()), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"Claude Code timed out after {timeout_seconds}s")
        except FileNotFoundError:
            raise RuntimeError(
                f"Claude CLI not found at {self._cli_path}. "
                "Install claude or set ANTHROPIC_API_KEY."
            )

        if proc.returncode != 0:
            err = stderr.decode(errors="replace")
            raise RuntimeError(f"Claude CLI exited {proc.returncode}: {err[:500]}")

        raw = stdout.decode(errors="replace").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Claude CLI returned non-JSON: {exc}\nRaw: {raw[:300]}")

        output = parsed.get("result", raw)
        cost_usd = float(parsed.get("total_cost_usd", 0.0))
        usage = parsed.get("usage", {})
        tokens_in = int(usage.get("input_tokens", 0))
        tokens_out = int(usage.get("output_tokens", 0))
        tokens_used = tokens_in + tokens_out

        return output, tokens_used, cost_usd


async def run_build_agent(
    input: BuildAgentInput,
    db,  # AsyncSession
    llm: LLMClient,
    prompt_loader: PromptLoader,
    coding_agent: Optional[CodingAgent] = None,
) -> BuildAgentOutput:
    """Orchestrate the build agent: generate code and detect friction."""

    from studio.db.models import DesignFriction, Slice
    from studio.events.emitter import emit_event
    from studio.observability.metrics import design_friction_total, slices_built_total

    if coding_agent is None:
        coding_agent = ClaudeCodeAgent()

    # 1. Choose prompt
    if input.slice_type == "skeleton":
        task_tpl = prompt_loader.load("build_agent", "skeleton")
        prompt = prompt_loader.render(
            task_tpl.content,
            project_name=input.project_name,
            design_digest=input.design_digest,
            project_path=input.project_path,
            stack=input.stack,
        )
    else:
        task_tpl = prompt_loader.load("build_agent", "skeleton")
        prompt = prompt_loader.render(
            task_tpl.content,
            project_name=input.project_name,
            design_digest=input.design_digest,
            project_path=input.project_path,
            stack=input.stack,
        )

    # 2. Run coding agent
    logger.info(
        "build_agent_starting",
        session_id=str(input.session_id),
        slice_type=input.slice_type,
        project_path=input.project_path,
    )

    try:
        build_output, tokens_used, cost_usd = await coding_agent.run(
            prompt,
            input.project_path,
            timeout_seconds=600,
        )
    except RuntimeError as exc:
        logger.error("build_agent_coding_failed", error=str(exc))
        build_output = f"Build failed: {exc}"
        tokens_used = 0
        cost_usd = 0.0

    # 3. Analyze project for friction
    project_path = Path(input.project_path)
    try:
        metrics, friction_reports = analyze_project(project_path)
    except Exception as exc:
        logger.warning("friction_analysis_failed", error=str(exc))
        metrics = CodeQualityMetrics()
        friction_reports = []

    # 4. Run friction detection prompt if we have LLM budget
    if friction_reports:
        friction_tpl = prompt_loader.load("build_agent", "friction_detection")
        friction_prompt = prompt_loader.render(
            friction_tpl.content,
            project_name=input.project_name,
            design_digest=input.design_digest,
            build_output=build_output[:2000],
        )
        try:
            llm_response: LLMResponse = await llm.complete(
                agent="build_agent",
                system_prompt=prompt_loader.load("build_agent", "system").content,
                user_content=friction_prompt,
                model="claude-sonnet-4-6",
                max_tokens=4096,
                temperature=0.0,
                prompt_hash=friction_tpl.hash,
                session_id=input.session_id,
                db=db,
            )
            tokens_used += llm_response.tokens_in + llm_response.tokens_out
            cost_usd += llm_response.cost_usd
            # Merge any additional friction the LLM detected
            llm_friction = _parse_llm_friction(llm_response.content)
            friction_reports.extend(llm_friction)
        except Exception as exc:
            logger.warning("friction_llm_failed", error=str(exc))

    # 5. Persist friction items to DB
    friction_db_ids: list[str] = []
    for report in friction_reports:
        row = DesignFriction(
            session_id=input.session_id,
            status="open",
            severity=report.severity,
            category=report.category,
            description=report.description,
            code_location=report.code_location,
            friction_score=report.friction_score,
        )
        db.add(row)
        await db.flush()
        friction_db_ids.append(str(row.id))

    # 6. Emit events for each friction item
    for report in friction_reports:
        await emit_event(
            db,
            input.session_id,
            "design_friction.reported",
            data={
                "severity": report.severity,
                "category": report.category,
                "description": report.description,
                "friction_score": report.friction_score,
                "slice_id": "",
                "code_location": report.code_location,
                "suggested_design_change": report.suggested_design_change,
            },
            agent="build_agent",
        )
        design_friction_total.labels(
            severity=report.severity, category=report.category
        ).inc()

    # 7. Detect changed files (simple heuristic: list git status)
    files_changed = await _detect_changed_files(input.project_path)
    tests_written = [f.path for f in files_changed if "test" in f.path]

    # 8. Try git commit
    git_commit_hash = await _try_git_commit(
        input.project_path,
        f"feat: {input.slice_type} - {input.slice_name}",
    )

    # 9. Emit build.completed event
    await emit_event(
        db,
        input.session_id,
        "agent.completed",
        data={
            "agent": "build_agent",
            "slice_type": input.slice_type,
            "files_changed": len(files_changed),
            "friction_items": len(friction_reports),
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
        },
        agent="build_agent",
    )

    slices_built_total.labels(type=input.slice_type).inc()

    return BuildAgentOutput(
        files_changed=files_changed,
        tests_written=tests_written,
        friction_items=friction_reports,
        git_commit_hash=git_commit_hash,
        metrics=metrics,
        tokens_used=tokens_used,
        cost_usd=cost_usd,
        build_output=build_output,
    )


def _parse_llm_friction(content: str) -> list[FrictionReport]:
    """Parse LLM friction detection response."""
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end])

    try:
        data = json.loads(text)
        items = data if isinstance(data, list) else data.get("friction_items", [])
        reports = []
        for item in items:
            score = float(item.get("friction_score", 5.0))
            reports.append(FrictionReport(
                severity=item.get("severity", severity_from_score(score)),
                category=item.get("category", "readability"),
                description=item.get("description", ""),
                code_location=item.get("code_location", ""),
                friction_score=score,
                suggested_design_change=item.get("suggested_design_change", ""),
            ))
        return reports
    except Exception:
        return []


async def _detect_changed_files(project_path: str) -> list[FileChange]:
    """Use git status to find changed files."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_path,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        lines = stdout.decode(errors="replace").strip().splitlines()
        changes = []
        for line in lines:
            if len(line) < 4:
                continue
            status = line[:2].strip()
            path = line[3:].strip()
            if status in ("A", "?"):
                action = "created"
            elif status == "D":
                action = "deleted"
            else:
                action = "modified"
            changes.append(FileChange(path=path, action=action))
        return changes
    except Exception:
        return []


async def _try_git_commit(project_path: str, message: str) -> Optional[str]:
    """Attempt to git add + commit all changes."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "add", "-A",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_path,
        )
        await asyncio.wait_for(proc.communicate(), timeout=30)

        proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", message,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_path,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode == 0:
            # Get hash
            proc2 = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "HEAD",
                stdout=asyncio.subprocess.PIPE,
                cwd=project_path,
            )
            out, _ = await asyncio.wait_for(proc2.communicate(), timeout=10)
            return out.decode().strip()[:12]
    except Exception as exc:
        logger.warning("git_commit_failed", error=str(exc))
    return None
