"""Shared hard-stop handling for budget exhaustion inside graph nodes."""

from __future__ import annotations

import uuid

import structlog

logger = structlog.get_logger(__name__)


async def abort_on_budget(db, session_id: uuid.UUID, exc: Exception, *, node: str) -> dict:
    """Mark the session errored and emit session.error after a BudgetExceeded.

    Returns a state delta carrying ``error`` so the routers short-circuit to the
    complete node — a clean stop with no half-written agent output (the budget
    check fires before the LLM call, so nothing was produced this iteration).
    """
    from studio.db.models import Session
    from studio.events.emitter import emit_event

    session = await db.get(Session, session_id)
    if session is not None:
        session.status = "error"
        await db.flush()

    await emit_event(
        db,
        session_id,
        "session.error",
        data={"error_type": "budget_exceeded", "error_message": str(exc)},
        agent="orchestrator",
    )
    logger.warning("budget_abort", node=node, session_id=str(session_id), error=str(exc))
    return {"current_node": node, "error": str(exc)}
