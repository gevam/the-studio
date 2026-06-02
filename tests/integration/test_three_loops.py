"""Deterministic proof that all three loops fire in a single session (DoD).

Scripts the agents so each loop triggers exactly once:
- Design⇄UX: the UX design review asks for a revision on its first pass.
- Design⇄Build: the first feature build emits complexity friction → design revises.
- Build⇄Verify: the first feature verify fails → build retries.

Live DB; skipped if unreachable.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select, text

from studio.agents.reviewer import ReviewerOutput, RubricScore
from studio.agents.slice_planner import PlannedSlice, SlicePlan
from studio.agents.ux import ExperienceMetric, UXReview
from studio.ai.llm_client import LLMClient, LLMResponse, StructuredResponse
from studio.ai.prompt_loader import PromptTemplate
from studio.db.models import DesignRevision, EventLog, Requirement, Session
from studio.design.schema import LivingDesign
from studio.graph.builder import build_sprint2_graph

_SIMPLE = "def f():\n    return 1\n"


def _client():
    counters = {"ux": 0}

    async def _structured(messages, *, system, schema, **_):
        if schema is LivingDesign:
            parsed = LivingDesign(modules=[{"name": "core", "responsibility": "r"}])
        elif schema is UXReview:
            counters["ux"] += 1
            parsed = UXReview(  # first design review asks for a revision → Design⇄UX loop
                experience_score=9.0,
                needs_design_revision=(counters["ux"] == 1),
                experience_metric=ExperienceMetric(name="≤2 calls"),
            )
        elif schema is SlicePlan:
            parsed = SlicePlan(
                slices=[PlannedSlice(name="shorten", requirement_titles=["Shorten URL"])])
        elif schema is ReviewerOutput:
            parsed = ReviewerOutput(
                rubric_scores=[RubricScore(criterion="security", score=9, evidence="x.py:1")],
                overall_score=9.0, passed=True)
        else:  # pragma: no cover
            raise AssertionError(schema)
        return StructuredResponse(parsed=parsed, tokens_in=10, tokens_out=5,
                                  cost_usd=0.001, model="m", latency_ms=5)

    client = LLMClient(provider="claude_cli")
    client._provider = MagicMock()
    client._provider.complete = AsyncMock(return_value=LLMResponse(
        content="{}", tokens_in=2, tokens_out=1, cost_usd=0.0, model="m", latency_ms=1))
    client._provider.complete_structured = AsyncMock(side_effect=_structured)
    return client


def _loader():
    loader = MagicMock()
    loader.load.return_value = PromptTemplate(content="p", hash="h", path="/x")
    loader.render.return_value = "rendered"
    return loader


async def _cleanup(session_factory, sid):
    async with session_factory() as db:
        for tbl in ("event_log", "ai_feedback", "verification_results", "design_friction",
                    "design_revisions", "reviewer_records", "slices", "requirements",
                    "human_decisions"):
            await db.execute(text(f"DELETE FROM {tbl} WHERE session_id=:s"), {"s": sid})  # noqa: S608
        await db.execute(text("DELETE FROM sessions WHERE id=:s"), {"s": sid})
        await db.commit()


@pytest.mark.asyncio
async def test_all_three_loops_fire_in_one_session(session_factory, tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@e"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=project, check=True)  # noqa: S603,S607

    builds = {"n": 0}

    class _FakeCodingAgent:
        def __init__(self, *a, **k):
            pass

        async def run(self, prompt, path, *, timeout_seconds=300):
            builds["n"] += 1
            (Path(path) / "mod.py").write_text(_SIMPLE)
            return ("built", 10, 0.001)

    monkeypatch.setattr("studio.agents.build.ClaudeCodeAgent", _FakeCodingAgent)

    # Deterministically drive the Design⇄Build loop: the first feature build reports
    # complexity friction; subsequent analyses are clean.
    from studio.friction.contract import CodeQualityMetrics, FrictionReport
    analyses = {"n": 0}

    def _fake_analyze(path):
        analyses["n"] += 1
        metrics = CodeQualityMetrics(coverage_pct=85.0, tests_count=4, tests_passing=4)
        if analyses["n"] == 2:  # call #1 = skeleton, #2 = first feature build
            return metrics, [FrictionReport(
                severity="high", category="complexity", description="too complex",
                code_location="mod.py:1", friction_score=7.0, suggested_design_change="split it")]
        return metrics, []

    monkeypatch.setattr("studio.agents.build.analyze_project", _fake_analyze)

    from studio.verification.runner import VerificationResult

    verifies = {"n": 0}

    async def _verify(**kwargs):
        # Calls: #1 skeleton (pass), #2 first feature verify (fail → retry), #3+ pass.
        verifies["n"] += 1
        passed = verifies["n"] != 2
        return VerificationResult(
            passed=passed, build_passed=passed, test_passed=passed, lint_passed=True,
            coverage_pct=85.0, tests_run=4, tests_passed=4, tests_failed=0,
            build_output="", test_output="", lint_output="", duration_ms=2, check_results=[])

    monkeypatch.setattr("studio.verification.runner.run_verification", _verify)

    sid = uuid.uuid4()
    async with session_factory() as db:
        db.add(Session(id=sid, name="loops", status="created",
                       config={"project_path": str(project), "stack": "python",
                               "auto_approve_gates": True, "max_design_ux_loops": 3,
                               "max_design_iterations": 5}))
        await db.flush()
        db.add(Requirement(session_id=sid, title="Shorten URL", priority="high", status="active"))
        await db.commit()

    try:
        graph = build_sprint2_graph(
            db_factory=session_factory, llm=_client(), prompt_loader=_loader())
        await graph.ainvoke({"session_id": str(sid)}, {"recursion_limit": 80})

        async with session_factory() as db:
            session = await db.get(Session, sid)
            assert session.status == "completed"
            revisions = await db.scalar(
                select(func.count()).select_from(DesignRevision)
                .where(DesignRevision.session_id == sid))
            seq_events = (await db.execute(
                select(EventLog.event_type).where(EventLog.session_id == sid)
                .order_by(EventLog.seq))).scalars().all()

        # Design⇄UX loop: a UX-driven revision happened before the skeleton.
        assert revisions >= 3  # initial + UX revision + friction revision (at least)
        # Design⇄Build loop: the build emitted friction that drove a revision.
        assert "design_friction.reported" in seq_events
        # Build⇄Verify loop: extra builds/verifies from the friction + retry cycles.
        assert builds["n"] >= 4  # skeleton + feature + friction-rebuild + verify-retry
        assert verifies["n"] >= 3
        assert "session.completed" in seq_events
    finally:
        await _cleanup(session_factory, sid)
