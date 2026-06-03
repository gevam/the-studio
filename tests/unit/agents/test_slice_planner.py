"""Tests for the slice planner + scope-creep detector (§12 step 8)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from studio.agents.slice_planner import (
    PlannedSlice,
    SlicePlan,
    SlicePlanInput,
    detect_scope_creep,
    plan_slices,
)
from studio.ai.llm_client import StructuredResponse
from studio.ai.prompt_loader import PromptTemplate
from studio.db.models import Session, Slice


def test_scope_creep_drops_unjustified_slices():
    slices = [
        PlannedSlice(name="shorten", requirement_titles=["Shorten URL"]),
        PlannedSlice(name="analytics-dashboard", requirement_titles=["Fancy charts"]),
        PlannedSlice(name="redirect", requirement_titles=["redirect"]),  # case-insensitive
    ]
    in_scope, dropped, fallback = detect_scope_creep(slices, ["Shorten URL", "Redirect"])
    assert {s.name for s in in_scope} == {"shorten", "redirect"}
    assert dropped == ["analytics-dashboard"]
    assert fallback is False


def test_scope_creep_keeps_paraphrased_slices():
    # CR #5: the LLM paraphrases requirement titles; fuzzy match must retain them.
    slices = [
        PlannedSlice(name="URL shortening endpoint", requirement_titles=["shorten a url"]),
        PlannedSlice(name="redirect service", requirement_titles=["302 redirect to target"]),
    ]
    in_scope, dropped, fallback = detect_scope_creep(slices, ["Shorten URL", "Redirect"])
    assert {s.name for s in in_scope} == {"URL shortening endpoint", "redirect service"}
    assert dropped == [] and fallback is False


def test_scope_creep_fallback_keeps_all_when_nothing_matches():
    # If fuzzy match would drop everything, keep all + signal fallback (never empty MVP).
    slices = [PlannedSlice(name="totally unrelated", requirement_titles=["xyzzy"])]
    in_scope, dropped, fallback = detect_scope_creep(slices, ["Shorten URL"])
    assert in_scope == slices and dropped == [] and fallback is True


@pytest.mark.asyncio
async def test_plan_slices_persists_only_in_scope(session_factory):
    async with session_factory() as db:
        try:
            session = Session(name="plan-test", status="running")
            db.add(session)
            await db.flush()

            plan = SlicePlan(slices=[
                PlannedSlice(name="shorten", requirement_titles=["Shorten URL"]),
                PlannedSlice(name="creep", requirement_titles=["unrelated"]),
            ])
            llm = AsyncMock()
            llm.complete_structured = AsyncMock(return_value=StructuredResponse(
                parsed=plan, tokens_in=10, tokens_out=5, cost_usd=0.001, model="m", latency_ms=10,
            ))
            loader = MagicMock()
            loader.load.return_value = PromptTemplate(content="p", hash="h", path="/x")
            loader.render.return_value = "rendered"

            result = await plan_slices(
                SlicePlanInput(
                    session_id=session.id, design_digest="d", project_name="url",
                    requirements=["Shorten URL", "Redirect"],
                ),
                db, llm, loader,
            )
            assert len(result.slice_ids) == 1  # creep dropped
            assert result.dropped == ["creep"]

            rows = (await db.execute(
                select(Slice).where(Slice.session_id == session.id, Slice.slice_type == "feature")
            )).scalars().all()
            assert len(rows) == 1 and rows[0].name == "shorten"
        finally:
            await db.rollback()
