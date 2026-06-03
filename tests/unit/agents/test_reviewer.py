"""Tests for the Reviewer agent (§4.4). Live DB; skipped if unreachable."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from studio.agents.reviewer import (
    ReviewerInput,
    ReviewerOutput,
    RubricScore,
    run_reviewer,
)
from studio.ai.llm_client import StructuredResponse
from studio.ai.prompt_loader import PromptTemplate
from studio.db.models import EventLog, ReviewerRecord, Session


def _mock_llm(output: ReviewerOutput, model: str = "claude-opus-4-5"):
    llm = AsyncMock()
    llm.complete_structured = AsyncMock(
        return_value=StructuredResponse(
            parsed=output, tokens_in=10, tokens_out=5, cost_usd=0.002,
            model=model, latency_ms=10,
        )
    )
    return llm


def _mock_loader():
    loader = MagicMock()
    loader.load.return_value = PromptTemplate(content="p {{x}}", hash="h", path="/x")
    loader.render.return_value = "rendered"
    return loader


def test_pass_decision_from_threshold():
    assert ReviewerOutput(overall_score=8.0).passed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("score,expected_pass", [(9.0, True), (5.0, False)])
async def test_reviewer_persists_record_and_emits(session_factory, score, expected_pass):
    async with session_factory() as db:
        try:
            session = Session(name="rev-test", status="running")
            db.add(session)
            await db.flush()

            output = ReviewerOutput(
                rubric_scores=[RubricScore(criterion="security", score=score, evidence="x.py:1")],
                overall_score=score, issues=[] if expected_pass else ["fix authz"],
            )
            result = await run_reviewer(
                ReviewerInput(
                    session_id=session.id, design_digest="d", design_version=1,
                    project_name="todo", slice_name="s", coverage_pct=90, tests_run=5,
                ),
                db, _mock_llm(output), _mock_loader(),
            )
            assert result.output.passed is expected_pass
            assert result.model_used == "claude-opus-4-5"  # different model from Sonnet agents

            records = (await db.execute(
                select(ReviewerRecord).where(ReviewerRecord.session_id == session.id)
            )).scalars().all()
            assert len(records) == 1 and records[0].passed is expected_pass

            types = set((await db.execute(
                select(EventLog.event_type).where(EventLog.session_id == session.id)
            )).scalars().all())
            assert "reviewer.evaluated" in types
        finally:
            await db.rollback()
