"""Human gate: interrupt → resume, auto-approve, and REST endpoints.

Live DB; skipped if unreachable.
"""

from __future__ import annotations

import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from sqlalchemy import select, text

from studio.db.models import EventLog, HumanDecision, Session
from studio.graph.nodes.human_gate import make_human_gate_node
from studio.graph.state import GraphState


def _gate_graph(session_factory, *, checkpointer):
    """Tiny graph: START → human_gate_design → END, with its own DB session per node."""
    gate = make_human_gate_node("design")

    async def node(state: GraphState) -> dict:
        async with session_factory() as db:
            result = await gate(state, db=db)
            await db.commit()
            return result

    g = StateGraph(GraphState)
    g.add_node("human_gate_design", node)
    g.add_edge(START, "human_gate_design")
    g.add_edge("human_gate_design", END)
    return g.compile(checkpointer=checkpointer)


async def _make_session(session_factory, **config) -> uuid.UUID:
    sid = uuid.uuid4()
    async with session_factory() as db:
        db.add(Session(id=sid, name="gate-test", status="running", config=config))
        await db.commit()
    return sid


async def _cleanup(session_factory, sid) -> None:
    async with session_factory() as db:
        for tbl in ("event_log", "human_decisions", "sessions"):
            col = "id" if tbl == "sessions" else "session_id"
            await db.execute(text(f"DELETE FROM {tbl} WHERE {col} = :s"), {"s": sid})  # noqa: S608
        await db.commit()


async def _event_types(session_factory, sid) -> set[str]:
    async with session_factory() as db:
        return set((await db.execute(
            select(EventLog.event_type).where(EventLog.session_id == sid)
        )).scalars().all())


@pytest.mark.asyncio
async def test_gate_interrupts_then_resumes(session_factory):
    sid = await _make_session(session_factory)
    try:
        graph = _gate_graph(session_factory, checkpointer=MemorySaver())
        cfg = {"configurable": {"thread_id": str(sid)}}

        # First invoke: the gate pauses (interrupt) — checkpoint durably emitted.
        result = await graph.ainvoke({"session_id": str(sid)}, cfg)
        assert "__interrupt__" in result
        assert "human.checkpoint" in await _event_types(session_factory, sid)
        async with session_factory() as db:
            gate = await db.scalar(select(HumanDecision).where(HumanDecision.session_id == sid))
            assert gate.action == "pending"

        # Resume with an approval — graph continues and records the decision.
        final = await graph.ainvoke(Command(resume={"action": "approve"}), cfg)
        assert final["human_gate_action"] == "approve"
        assert "human.decision" in await _event_types(session_factory, sid)
        async with session_factory() as db:
            gate = await db.scalar(select(HumanDecision).where(HumanDecision.session_id == sid))
            assert gate.action == "approve" and gate.decided_at is not None
    finally:
        await _cleanup(session_factory, sid)


@pytest.mark.asyncio
async def test_gate_auto_approves_without_interrupt(session_factory):
    sid = await _make_session(session_factory, auto_approve_gates=True)
    try:
        graph = _gate_graph(session_factory, checkpointer=MemorySaver())
        # init_session normally loads session.config into state; supply it here.
        result = await graph.ainvoke(
            {"session_id": str(sid), "config": {"auto_approve_gates": True}},
            {"configurable": {"thread_id": str(sid)}},
        )
        assert "__interrupt__" not in result
        assert result["human_gate_action"] == "approve"
        types = await _event_types(session_factory, sid)
        assert {"human.checkpoint", "human.decision"} <= types
    finally:
        await _cleanup(session_factory, sid)


@pytest.mark.asyncio
async def test_reject_endpoint_records_decision(session_factory):
    # Call the endpoint handler directly (TestClient spins a second event loop that
    # conflicts with the loop-bound asyncpg pool). This exercises the same logic.
    from datetime import UTC, datetime, timedelta

    from studio.api.routes.sessions import GateDecision, reject

    sid = await _make_session(session_factory)
    async with session_factory() as db:
        db.add(HumanDecision(
            session_id=sid, gate_type="design", action="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ))
        await db.commit()
    try:
        async with session_factory() as db:
            result = await reject(sid, GateDecision(feedback="needs work"), db)
        assert result["action"] == "reject"
        async with session_factory() as db:
            gate = await db.scalar(select(HumanDecision).where(HumanDecision.session_id == sid))
            assert gate.action == "reject" and gate.feedback == "needs work"
        assert "human.decision" in await _event_types(session_factory, sid)
    finally:
        await _cleanup(session_factory, sid)
