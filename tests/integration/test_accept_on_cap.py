"""slice.accepted_under_cap: a force-accepted slice is distinguishable from a
genuinely converged one — in the event log and on the slices row (CR finding 3).

Live DB; skipped if unreachable.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

from studio.db.models import EventLog, Session, Slice
from studio.graph.nodes.feature_nodes import slice_done_node


async def _make_slice(session_factory, sid, slice_id):
    async with session_factory() as db:
        db.add(Session(id=sid, name="cap", status="running", config={}))
        await db.flush()
        db.add(Slice(
            id=slice_id, session_id=sid, name="s", slice_type="feature",
            status="verifying", order_index=1, design_version=0,
        ))
        await db.commit()


async def _cleanup(session_factory, sid):
    async with session_factory() as db:
        for tbl in ("event_log", "slices"):
            await db.execute(text(f"DELETE FROM {tbl} WHERE session_id=:s"), {"s": sid})  # noqa: S608
        await db.execute(text("DELETE FROM sessions WHERE id=:s"), {"s": sid})
        await db.commit()


@pytest.mark.asyncio
async def test_exhausted_budget_emits_and_persists_accept_on_cap(session_factory):
    sid, slice_id = uuid.uuid4(), uuid.uuid4()
    await _make_slice(session_factory, sid, slice_id)
    try:
        async with session_factory() as db:
            await slice_done_node(
                {"session_id": str(sid), "current_slice_id": str(slice_id),
                 "slice_rework_budget": 5, "slice_rework_used": 5},  # exhausted
                db=db,
            )
            await db.commit()
        async with session_factory() as db:
            row = await db.get(Slice, slice_id)
            assert row.status == "done"
            assert row.accepted_under_cap is True and row.rework_used == 5
            types = {t for (t,) in (await db.execute(
                select(EventLog.event_type).where(EventLog.session_id == sid))).all()}
        assert "slice.accepted_under_cap" in types
    finally:
        await _cleanup(session_factory, sid)


@pytest.mark.asyncio
async def test_converged_slice_does_neither(session_factory):
    sid, slice_id = uuid.uuid4(), uuid.uuid4()
    await _make_slice(session_factory, sid, slice_id)
    try:
        async with session_factory() as db:
            await slice_done_node(
                {"session_id": str(sid), "current_slice_id": str(slice_id),
                 "slice_rework_budget": 5, "slice_rework_used": 2},  # converged
                db=db,
            )
            await db.commit()
        async with session_factory() as db:
            row = await db.get(Slice, slice_id)
            assert row.accepted_under_cap is False and row.rework_used == 2
            types = {t for (t,) in (await db.execute(
                select(EventLog.event_type).where(EventLog.session_id == sid))).all()}
        assert "slice.accepted_under_cap" not in types
    finally:
        await _cleanup(session_factory, sid)
