"""complete node: marks session completed or errored, emits session.completed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog

from studio.graph.state import GraphState

logger = structlog.get_logger(__name__)


async def complete_node(state: GraphState, *, db, **_) -> dict:
    """Finalize the session: update status and emit session.completed."""
    from studio.db.models import Session
    from studio.events.emitter import emit_event

    session_id = uuid.UUID(state["session_id"])

    session = await db.get(Session, session_id)
    if session is None:
        logger.error("complete_session_not_found", session_id=str(session_id))
        return {"current_node": "complete"}

    error = state.get("error")
    skeleton_verified = state.get("skeleton_verified", False)

    if error:
        session.status = "error"
    elif skeleton_verified:
        session.status = "completed"
    else:
        # Reached max iterations without success
        session.status = "error"
        error = "Max iterations reached without verified skeleton"

    session.current_node = "complete"
    session.completed_at = datetime.now(UTC)
    session.tokens_used = state.get("tokens_used", session.tokens_used)
    session.cost_usd = state.get("cost_usd", float(session.cost_usd))
    await db.flush()

    await emit_event(
        db,
        session_id,
        "session.completed",
        data={
            "status": session.status,
            "skeleton_verified": skeleton_verified,
            "iterations": state.get("iteration", 0),
            "total_tokens": session.tokens_used,
            "total_cost_usd": float(session.cost_usd),
            "total_duration_ms": 0,  # wall time not tracked at session level
            "error": error,
        },
        agent="orchestrator",
    )

    logger.info(
        "session_complete",
        session_id=str(session_id),
        status=session.status,
        skeleton_verified=skeleton_verified,
        iterations=state.get("iteration", 0),
        cost_usd=float(session.cost_usd),
    )

    return {"current_node": "complete", "error": error}
