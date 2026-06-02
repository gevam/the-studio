"""Full Sprint 2 graph: end-to-end happy path. Live DB; skipped if unreachable."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select, text

from studio.agents.reviewer import ReviewerOutput, RubricScore
from studio.agents.slice_planner import PlannedSlice, SlicePlan
from studio.agents.ux import ExperienceMetric, UXReview
from studio.ai.llm_client import LLMResponse, StructuredResponse
from studio.ai.prompt_loader import PromptTemplate
from studio.db.models import EventLog, Requirement, Session
from studio.design.schema import LivingDesign
from studio.graph.builder import build_sprint2_graph


def _smart_client():
    """Real LLMClient with a stubbed provider that returns the right schema per agent."""
    from studio.ai.llm_client import LLMClient

    async def _structured(messages, *, system, schema, **_):
        if schema is LivingDesign:
            parsed = LivingDesign(modules=[{"name": "core", "responsibility": "r"}])
        elif schema is UXReview:
            parsed = UXReview(experience_score=9.0, needs_design_revision=False,
                              experience_metric=ExperienceMetric(name="≤2 calls"))
        elif schema is SlicePlan:
            parsed = SlicePlan(
                slices=[PlannedSlice(name="shorten", requirement_titles=["Shorten URL"])])
        elif schema is ReviewerOutput:
            parsed = ReviewerOutput(
                rubric_scores=[RubricScore(criterion="security", score=9, evidence="x.py:1")],
                overall_score=9.0, passed=True,
            )
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected schema {schema}")
        return StructuredResponse(parsed=parsed, tokens_in=10, tokens_out=5,
                                  cost_usd=0.001, model="m", latency_ms=5)

    client = LLMClient(provider="claude_cli")
    client._provider = MagicMock()
    client._provider.complete = AsyncMock(return_value=LLMResponse(
        content="{}", tokens_in=5, tokens_out=2, cost_usd=0.0001, model="m", latency_ms=5))
    client._provider.complete_structured = AsyncMock(side_effect=_structured)
    return client


def _mock_loader():
    loader = MagicMock()
    loader.load.return_value = PromptTemplate(content="p {{x}}", hash="h", path="/x")
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
async def test_full_graph_reaches_complete_through_both_gates(
    session_factory, tmp_path, monkeypatch,
):
    project = tmp_path / "proj"
    project.mkdir()
    git = "git"
    for args in (["init", "-q"], ["config", "user.email", "t@e"], ["config", "user.name", "t"]):
        subprocess.run([git, *args], cwd=project, check=True)  # noqa: S603

    class _FakeCodingAgent:
        def __init__(self, *a, **k):
            pass

        async def run(self, prompt, path, *, timeout_seconds=300):
            (Path(path) / "app.py").write_text("def f():\n    return 1\n")
            return ("built", 10, 0.001)

    monkeypatch.setattr("studio.agents.build.ClaudeCodeAgent", _FakeCodingAgent)

    from studio.verification.runner import VerificationResult

    async def _verify_pass(**kwargs):
        return VerificationResult(
            passed=True, build_passed=True, test_passed=True, lint_passed=True,
            coverage_pct=88.0, tests_run=4, tests_passed=4, tests_failed=0,
            build_output="", test_output="", lint_output="", duration_ms=3, check_results=[],
        )

    monkeypatch.setattr("studio.verification.runner.run_verification", _verify_pass)

    sid = uuid.uuid4()
    async with session_factory() as db:
        db.add(Session(id=sid, name="url-shortener", status="created",
                       config={"project_path": str(project), "stack": "python",
                               "auto_approve_gates": True, "max_design_iterations": 3}))
        await db.flush()
        db.add(Requirement(session_id=sid, title="Shorten URL", priority="high", status="active"))
        await db.commit()

    try:
        graph = build_sprint2_graph(db_factory=session_factory, llm=_smart_client(),
                                    prompt_loader=_mock_loader())
        await graph.ainvoke({"session_id": str(sid)}, {"recursion_limit": 60})

        async with session_factory() as db:
            session = await db.get(Session, sid)
            assert session.status == "completed"
            types = set((await db.execute(
                select(EventLog.event_type).where(EventLog.session_id == sid)
            )).scalars().all())

        # Both human gates fired, and the per-slice review/reviewer ran.
        assert types >= {
            "human.checkpoint", "human.decision", "reviewer.evaluated",
            "slice.started", "slice.built", "slice.verified", "session.completed",
        }
        # Gate fired twice (design + ship).
        async with session_factory() as db:
            from studio.db.models import HumanDecision
            gates = (await db.execute(
                select(HumanDecision.gate_type).where(HumanDecision.session_id == sid)
            )).scalars().all()
        assert set(gates) == {"design", "ship"}
    finally:
        await _cleanup(session_factory, sid)
