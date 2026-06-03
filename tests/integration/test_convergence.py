"""Adversarial convergence: even if every agent always complains, the capped
loops must still drive the session to `complete`. Live DB; skipped if unreachable.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from studio.agents.reviewer import ReviewerOutput, RubricScore
from studio.agents.slice_planner import PlannedSlice, SlicePlan
from studio.agents.ux import ExperienceMetric, UXReview
from studio.ai.llm_client import LLMClient, LLMResponse, StructuredResponse
from studio.ai.prompt_loader import PromptTemplate
from studio.db.models import Requirement, Session
from studio.design.schema import LivingDesign
from studio.graph.builder import build_sprint2_graph


def _adversarial_client():
    async def _structured(messages, *, system, schema, **_):
        if schema is LivingDesign:
            p = LivingDesign(modules=[{"name": "c", "responsibility": "r"}])
        elif schema is UXReview:  # ALWAYS wants a revision
            p = UXReview(experience_score=4.0, needs_design_revision=True,
                         experience_metric=ExperienceMetric(name="m"))
        elif schema is SlicePlan:
            p = SlicePlan(slices=[PlannedSlice(name="s1", requirement_titles=["Req A"])])
        else:  # Reviewer ALWAYS rejects
            p = ReviewerOutput(rubric_scores=[RubricScore(criterion="x", score=2, evidence="e")],
                               overall_score=2.0, passed=False)
        return StructuredResponse(parsed=p, tokens_in=5, tokens_out=2, cost_usd=0.0,
                                  model="m", latency_ms=1)

    c = LLMClient(provider="claude_cli")
    c._provider = MagicMock()
    c._provider.complete = AsyncMock(return_value=LLMResponse(
        content="{}", tokens_in=1, tokens_out=1, cost_usd=0.0, model="m", latency_ms=1))
    c._provider.complete_structured = AsyncMock(side_effect=_structured)
    return c


def _loader():
    loader = MagicMock()
    loader.load.return_value = PromptTemplate(content="p", hash="h", path="/x")
    loader.render.return_value = "r"
    return loader


@pytest.mark.asyncio
async def test_session_converges_despite_always_complaining_agents(
    session_factory, tmp_path, monkeypatch,
):
    project = tmp_path / "proj"
    project.mkdir()
    for a in (["init", "-q"], ["config", "user.email", "t@e"], ["config", "user.name", "t"]):
        subprocess.run(["git", *a], cwd=project, check=True)  # noqa: S603,S607

    class _FakeCodingAgent:
        def __init__(self, *a, **k):
            pass

        async def run(self, prompt, path, *, timeout_seconds=300):
            (Path(path) / "mod.py").write_text("def f():\n    return 1\n")
            return ("built", 5, 0.0)

    monkeypatch.setattr("studio.agents.build.ClaudeCodeAgent", _FakeCodingAgent)

    from studio.friction.contract import CodeQualityMetrics, FrictionReport

    def _always_friction(path):  # build always reports friction
        return CodeQualityMetrics(coverage_pct=85.0), [FrictionReport(
            severity="high", category="complexity", description="c",
            code_location="m.py:1", friction_score=7.0, suggested_design_change="x")]

    monkeypatch.setattr("studio.agents.build.analyze_project", _always_friction)

    from studio.verification.runner import VerificationResult

    async def _verify_pass(**kwargs):
        return VerificationResult(
            passed=True, build_passed=True, test_passed=True, lint_passed=True,
            coverage_pct=85.0, tests_run=3, tests_passed=3, tests_failed=0,
            build_output="", test_output="", lint_output="", duration_ms=1, check_results=[])

    monkeypatch.setattr("studio.verification.runner.run_verification", _verify_pass)

    sid = uuid.uuid4()
    async with session_factory() as db:
        db.add(Session(id=sid, name="adv", status="created",
                       config={"project_path": str(project), "stack": "python",
                               "auto_approve_gates": True, "max_design_ux_loops": 1,
                               "max_design_iterations": 2, "max_feature_build_attempts": 2,
                               "max_ux_review_loops": 2, "max_reviewer_loops": 2}))
        await db.flush()
        db.add(Requirement(session_id=sid, title="Req A", priority="high", status="active"))
        await db.commit()

    try:
        graph = build_sprint2_graph(
            db_factory=session_factory, llm=_adversarial_client(), prompt_loader=_loader())
        # Bounded recursion: if the caps work, we finish well under this.
        await graph.ainvoke({"session_id": str(sid)}, {"recursion_limit": 200})
        async with session_factory() as db:
            session = await db.get(Session, sid)
            assert session.status == "completed"  # converged despite every agent complaining
    finally:
        async with session_factory() as db:
            for tbl in ("event_log", "ai_feedback", "verification_results", "design_friction",
                        "design_revisions", "reviewer_records", "slices", "requirements",
                        "human_decisions"):
                await db.execute(text(f"DELETE FROM {tbl} WHERE session_id=:s"), {"s": sid})  # noqa: S608
            await db.execute(text("DELETE FROM sessions WHERE id=:s"), {"s": sid})
            await db.commit()
