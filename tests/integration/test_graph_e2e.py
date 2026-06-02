"""End-to-end graph tests against the live test DB (skipped if unreachable).

Covers:
- Fix 1: a pre-exhausted budget hard-stops mid-run — session ends `error`, with a
  session.error event and no design revision written.
- Fix 2: a happy-path run emits the §7.2 lifecycle events that were previously
  missing (agent.started, slice.started/built/verified, git.committed,
  ai.feedback_recorded).

The LLM provider and coding agent are mocked; verification is stubbed to pass.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select, text

from studio.ai.llm_client import LLMClient, LLMResponse, StructuredResponse
from studio.ai.prompt_loader import PromptTemplate
from studio.db.models import (
    DesignRevision,
    EventLog,
    Requirement,
    Session,
)
from studio.design.schema import LivingDesign
from studio.graph.builder import build_sprint1_graph


def _real_client_with_mock_provider():
    """Real LLMClient (so budget + ai_feedback logic runs) with a stubbed provider.

    Stubs both text and structured completion since the design agent now uses
    native structured output.
    """
    client = LLMClient(provider="claude_cli")
    client._provider = MagicMock()
    client._provider.complete = AsyncMock(
        return_value=LLMResponse(
            content="{}", tokens_in=20, tokens_out=10,
            cost_usd=0.002, model="m", latency_ms=10,
        )
    )
    client._provider.complete_structured = AsyncMock(
        return_value=StructuredResponse(
            parsed=LivingDesign(modules=[{"name": "cli", "responsibility": "x"}]),
            tokens_in=20, tokens_out=10, cost_usd=0.002, model="m", latency_ms=10,
        )
    )
    return client


def _mock_loader():
    loader = MagicMock()
    loader.load.return_value = PromptTemplate(content="p {{x}}", hash="h", path="/x")
    loader.render.return_value = "rendered"
    return loader


async def _event_types(session_factory, session_id) -> set[str]:
    async with session_factory() as db:
        rows = (
            await db.execute(
                select(EventLog.event_type).where(EventLog.session_id == session_id)
            )
        ).scalars().all()
    return set(rows)


async def _cleanup(session_factory, session_id) -> None:
    async with session_factory() as db:
        for table in (
            "event_log", "ai_feedback", "verification_results", "design_friction",
            "design_revisions", "slices", "requirements",
        ):
            await db.execute(
                text(f"DELETE FROM {table} WHERE session_id = :sid"),  # noqa: S608 — fixed table names
                {"sid": session_id},
            )
        await db.execute(text("DELETE FROM sessions WHERE id = :sid"), {"sid": session_id})
        await db.commit()


@pytest.mark.asyncio
async def test_budget_hardstop_errors_session_cleanly(session_factory):
    session_id = uuid.uuid4()
    async with session_factory() as db:
        db.add(Session(
            id=session_id, name="budget-test", status="created",
            token_budget=100, tokens_used=200,  # already exhausted
            config={"max_design_iterations": 3},
        ))
        await db.flush()
        db.add(Requirement(
            session_id=session_id, title="do a thing", priority="high", status="active",
        ))
        await db.commit()

    try:
        graph = build_sprint1_graph(
            db_factory=session_factory,
            llm=_real_client_with_mock_provider(),
            prompt_loader=_mock_loader(),
        )
        await graph.ainvoke({"session_id": str(session_id)})

        async with session_factory() as db:
            session = await db.get(Session, session_id)
            assert session.status == "error"
            revisions = (
                await db.execute(
                    select(DesignRevision).where(DesignRevision.session_id == session_id)
                )
            ).scalars().all()
            assert revisions == []  # budget tripped before any revision was written

        assert "session.error" in await _event_types(session_factory, session_id)
    finally:
        await _cleanup(session_factory, session_id)


@pytest.mark.asyncio
async def test_happy_path_emits_lifecycle_events(session_factory, tmp_path, monkeypatch):
    project_path = tmp_path / "proj"
    project_path.mkdir()
    # git repo so the build agent's commit succeeds → git.committed event.
    git = shutil.which("git") or "git"
    for args in (["init", "-q"], ["config", "user.email", "t@e"], ["config", "user.name", "t"]):
        subprocess.run([git, *args], cwd=project_path, check=True)  # noqa: S603

    class _FakeCodingAgent:
        def __init__(self, *a, **k):
            pass

        async def run(self, prompt, path, *, timeout_seconds=300):
            (Path(path) / "app.py").write_text("def main():\n    return 0\n")
            return ("built ok", 50, 0.005)

    monkeypatch.setattr("studio.agents.build.ClaudeCodeAgent", _FakeCodingAgent)

    from studio.verification.runner import VerificationResult

    async def _fake_verify(**kwargs):
        return VerificationResult(
            passed=True, build_passed=True, test_passed=True, lint_passed=True,
            coverage_pct=90.0, tests_run=3, tests_passed=3, tests_failed=0,
            build_output="", test_output="", lint_output="", duration_ms=5,
            check_results=[],
        )

    monkeypatch.setattr("studio.verification.runner.run_verification", _fake_verify)

    session_id = uuid.uuid4()
    async with session_factory() as db:
        db.add(Session(
            id=session_id, name="happy", status="created",
            config={"project_path": str(project_path), "stack": "python",
                    "max_design_iterations": 3},
        ))
        await db.flush()
        db.add(Requirement(
            session_id=session_id, title="build it", priority="high", status="active",
        ))
        await db.commit()

    try:
        graph = build_sprint1_graph(
            db_factory=session_factory,
            llm=_real_client_with_mock_provider(),
            prompt_loader=_mock_loader(),
        )
        await graph.ainvoke({"session_id": str(session_id)})

        async with session_factory() as db:
            session = await db.get(Session, session_id)
            assert session.status == "completed"

        types = await _event_types(session_factory, session_id)
        for required in (
            "agent.started", "slice.started", "slice.built", "slice.verified",
            "git.committed", "ai.feedback_recorded",
        ):
            assert required in types, f"missing lifecycle event: {required} (got {sorted(types)})"
    finally:
        await _cleanup(session_factory, session_id)
