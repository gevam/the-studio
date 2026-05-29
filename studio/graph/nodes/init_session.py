"""init_session node: marks session running, emits session.created."""

from __future__ import annotations

import uuid

import structlog

from studio.graph.state import GraphState

logger = structlog.get_logger(__name__)


async def init_session_node(state: GraphState, *, db, **_) -> dict:
    """Mark session as running and emit session.created event."""
    from studio.db.models import Session
    from studio.events.emitter import emit_event

    session_id = uuid.UUID(state["session_id"])

    session = await db.get(Session, session_id)
    if session is None:
        logger.error("init_session_not_found", session_id=str(session_id))
        return {"error": f"Session {session_id} not found", "current_node": "init_session"}

    session.status = "running"
    session.current_node = "init_session"
    session.current_loop = "design_build"
    await db.flush()

    await emit_event(
        db,
        session_id,
        "session.created",
        data={
            "session_id": str(session_id),
            "session_name": session.name,
            "token_budget": session.token_budget,
            "cost_budget": float(session.cost_budget),
        },
        agent="orchestrator",
    )

    logger.info("init_session_complete", session_id=str(session_id))

    return {
        "current_node": "init_session",
        "current_loop": "design_build",
        "iteration": 0,
        "skeleton_verified": False,
        "pending_friction_ids": [],
        "tokens_used": session.tokens_used,
        "cost_usd": float(session.cost_usd),
        "token_budget": session.token_budget,
        "cost_budget": float(session.cost_budget),
        "config": session.config or {},
    }
