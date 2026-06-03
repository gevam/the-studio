"""A structured-output failure must mark the session errored, not crash/hang (CR #2).

Live DB; skipped if unreachable.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select, text

from studio.ai.llm_client import StructuredOutputError
from studio.ai.prompt_loader import PromptTemplate
from studio.db.models import EventLog, Requirement, Session
from studio.graph.nodes.design_agent import design_agent_node


def _failing_llm():
    llm = AsyncMock()
    # Simulate LLMClient having retried and still failing.
    llm.complete_structured = AsyncMock(side_effect=StructuredOutputError("no valid JSON"))
    return llm


def _loader():
    loader = MagicMock()
    loader.load.return_value = PromptTemplate(content="p", hash="h", path="/x")
    loader.render.return_value = "rendered"
    return loader


@pytest.mark.asyncio
async def test_design_structured_failure_marks_session_error(session_factory):
    sid = uuid.uuid4()
    async with session_factory() as db:
        db.add(Session(id=sid, name="sx", status="running", config={}))
        await db.flush()
        db.add(Requirement(session_id=sid, title="do x", priority="high", status="active"))
        await db.commit()
    try:
        async with session_factory() as db:
            delta = await design_agent_node(
                {"session_id": str(sid)}, db=db, llm=_failing_llm(), prompt_loader=_loader(),
            )
            await db.commit()

        # Node returned an error delta (routers will short-circuit to complete)…
        assert delta.get("error")
        # …and the session is errored with a session.error event (not silently running).
        async with session_factory() as db:
            session = await db.get(Session, sid)
            assert session.status == "error"
            events = (await db.execute(
                select(EventLog.event_type, EventLog.data).where(EventLog.session_id == sid)
            )).all()
        types = {e[0] for e in events}
        assert "session.error" in types
        err = next(d for t, d in events if t == "session.error")
        assert err["error_type"] == "structured_output_error"
    finally:
        async with session_factory() as db:
            for tbl in ("event_log", "ai_feedback", "design_revisions", "requirements"):
                await db.execute(text(f"DELETE FROM {tbl} WHERE session_id=:s"), {"s": sid})  # noqa: S608
            await db.execute(text("DELETE FROM sessions WHERE id=:s"), {"s": sid})
            await db.commit()
