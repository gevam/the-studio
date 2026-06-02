"""Tests for the UX/Customer agent (§4.2). Live DB; skipped if unreachable."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from studio.agents.ux import (
    ExperienceMetric,
    UXAgentInput,
    UXReview,
    run_ux_agent,
)
from studio.ai.llm_client import StructuredResponse
from studio.ai.prompt_loader import PromptTemplate
from studio.db.models import Session


def test_ux_review_score_bounds():
    review = UXReview(experience_score=8.5, journey_complete=True)
    assert review.experience_score == 8.5
    with pytest.raises(ValueError):
        UXReview(experience_score=99)  # out of 0–10 bound


def _mock_llm(review: UXReview):
    llm = AsyncMock()
    llm.complete_structured = AsyncMock(
        return_value=StructuredResponse(
            parsed=review, tokens_in=10, tokens_out=5, cost_usd=0.001,
            model="m", latency_ms=10,
        )
    )
    return llm


def _mock_loader():
    loader = MagicMock()
    loader.load.return_value = PromptTemplate(content="p {{x}}", hash="h", path="/x")
    loader.render.return_value = "rendered"
    return loader


@pytest.mark.asyncio
async def test_design_review_emits_lifecycle_and_returns_metric(session_factory):
    async with session_factory() as db:
        try:
            session = Session(name="ux-test", status="running")
            db.add(session)
            await db.flush()

            review = UXReview(
                experience_score=7.0,
                needs_design_revision=True,
                revision_suggestions=["add a --help summary"],
                experience_metric=ExperienceMetric(name="≤3 steps", target="add→list→done"),
            )
            out = await run_ux_agent(
                UXAgentInput(
                    session_id=session.id, design_digest="d", context="design_review",
                    project_name="todo", requirements=["add todos"],
                ),
                db, _mock_llm(review), _mock_loader(),
            )
            assert out.review.needs_design_revision is True
            assert out.review.experience_metric.name == "≤3 steps"

            from sqlalchemy import select

            from studio.db.models import EventLog
            types = set(
                (await db.execute(
                    select(EventLog.event_type).where(EventLog.session_id == session.id)
                )).scalars().all()
            )
            assert {"agent.started", "agent.completed"} <= types
        finally:
            await db.rollback()
