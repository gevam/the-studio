"""Linkage tests for run_design_agent — the §4 key mechanism.

When the design agent revises in response to friction, the open DesignFriction
rows must be UPDATEd to status='resolved' and linked to the new revision via
resolved_by_revision_id. The LLM is mocked; this is about the DB linkage, not
model output. Runs against the live test DB; skipped if unreachable.

NOTE (contract ambiguity — surfaced per CR): resolution is keyed on the friction
IDs *passed into* the agent, not on what the LLM actually addressed. So today all
passed friction is marked resolved on revision ("resolution-on-revision"), and
*partial* resolution is not representable. Whether resolution should instead be
confirmed by re-verification ("resolution-on-reverify") is a tracked Sprint 2
decision; see CLAUDE.md. These tests pin the *current* behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from studio.agents.design import DesignAgentInput, run_design_agent
from studio.ai.llm_client import StructuredResponse
from studio.ai.prompt_loader import PromptTemplate
from studio.db.models import DesignFriction, DesignRevision, Session
from studio.design.schema import LivingDesign


def _mock_llm():
    llm = AsyncMock()
    llm.complete_structured = AsyncMock(
        return_value=StructuredResponse(
            parsed=LivingDesign(modules=[{"name": "cli", "responsibility": "entry point"}]),
            tokens_in=10, tokens_out=5, cost_usd=0.001, model="m", latency_ms=10,
        )
    )
    return llm


def _mock_loader():
    loader = MagicMock()
    loader.load.return_value = PromptTemplate(content="p {{x}}", hash="h", path="/x")
    loader.render.return_value = "rendered"
    return loader


async def _seed(db, n: int) -> tuple[Session, list[DesignFriction]]:
    session = Session(name="link-test", status="running")
    db.add(session)
    await db.flush()
    friction = [
        DesignFriction(
            session_id=session.id, status="open", severity="high",
            category="complexity", description=f"friction {i}",
            code_location=f"f{i}.py:1", friction_score=7.0,
        )
        for i in range(n)
    ]
    db.add_all(friction)
    await db.flush()
    return session, friction


@pytest.mark.asyncio
async def test_friction_resolved_and_linked_to_revision(session_factory, tmp_path):
    async with session_factory() as db:
        try:
            session, friction = await _seed(db, 2)
            items = [
                {"id": str(f.id), "severity": f.severity, "category": f.category,
                 "description": f.description, "code_location": f.code_location,
                 "friction_score": 7.0}
                for f in friction
            ]
            inp = DesignAgentInput(
                session_id=session.id, design_digest="d", trigger="friction",
                requirements=["req"], friction_items=items, iteration=1,
                project_name="t", project_path=str(tmp_path), prev_version=1,
            )

            await run_design_agent(inp, db, _mock_llm(), _mock_loader())

            revs = (
                await db.execute(
                    select(DesignRevision).where(DesignRevision.session_id == session.id)
                )
            ).scalars().all()
            assert len(revs) == 1
            new_rev_id = revs[0].id

            for f in friction:
                await db.refresh(f)
                assert f.status == "resolved"
                assert f.resolved_by_revision_id == new_rev_id
                assert f.resolved_at is not None
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_all_passed_friction_resolved_even_if_llm_addresses_subset(session_factory, tmp_path):
    # Current contract: every friction ID handed to the agent is resolved on
    # revision, regardless of whether the revised design actually addressed it.
    # Partial resolution is therefore not representable today (see module docstring).
    async with session_factory() as db:
        try:
            session, friction = await _seed(db, 3)
            items = [
                {"id": str(f.id), "severity": f.severity, "category": f.category,
                 "description": f.description, "code_location": f.code_location,
                 "friction_score": 7.0}
                for f in friction
            ]
            inp = DesignAgentInput(
                session_id=session.id, design_digest="d", trigger="friction",
                requirements=["req"], friction_items=items, iteration=2,
                project_name="t", project_path=str(tmp_path), prev_version=2,
            )

            await run_design_agent(inp, db, _mock_llm(), _mock_loader())

            resolved = 0
            for f in friction:
                await db.refresh(f)
                resolved += f.status == "resolved"
            assert resolved == 3  # all, not a subset
        finally:
            await db.rollback()
