"""State projection: assembles GraphState from DB tables."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from studio.graph.state import GraphState


class SessionNotFound(Exception):
    def __init__(self, session_id: uuid.UUID) -> None:
        super().__init__(f"Session {session_id} not found")
        self.session_id = session_id


async def project_state(session_id: uuid.UUID, db: AsyncSession) -> GraphState:
    """Build the thin GraphState from normalized DB tables."""
    from studio.db.models import DesignFriction, DesignRevision, Session, Slice

    session = await db.get(Session, session_id)
    if session is None:
        raise SessionNotFound(session_id)

    # Latest design revision (digest + section_index)
    latest_design_result = await db.execute(
        select(DesignRevision)
        .where(DesignRevision.session_id == session_id)
        .order_by(DesignRevision.version.desc())
        .limit(1)
    )
    design = latest_design_result.scalar_one_or_none()

    # Open friction item IDs
    friction_result = await db.execute(
        select(DesignFriction.id)
        .where(DesignFriction.session_id == session_id)
        .where(DesignFriction.status == "open")
    )
    pending_friction_ids = [str(fid) for fid in friction_result.scalars()]

    # Remaining slices (planned or building)
    remaining_result = await db.execute(
        select(Slice.id)
        .where(Slice.session_id == session_id)
        .where(Slice.status.in_(["planned", "building"]))
        .order_by(Slice.order_index)
    )
    remaining_slice_ids = [str(sid) for sid in remaining_result.scalars()]

    return GraphState(
        session_id=str(session_id),
        session_version=session.version,
        design_digest=design.digest if design else "",
        design_version=design.version if design else 0,
        design_section_ids=[
            s.get("id", "") for s in (design.section_index if design else [])
        ],
        current_loop=session.current_loop or "design_build",
        current_node=session.current_node or "",
        iteration=session.iteration,
        tokens_used=session.tokens_used,
        cost_usd=float(session.cost_usd),
        token_budget=session.token_budget,
        cost_budget=float(session.cost_budget),
        pending_friction_ids=pending_friction_ids,
        remaining_slice_ids=remaining_slice_ids,
        skeleton_verified=False,
        verification_passed=False,
        awaiting_human=False,
        config=session.config or {},
        trace_id=session.trace_id,
    )
