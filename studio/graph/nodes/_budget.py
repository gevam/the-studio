"""Shared hard-stop handling for unrecoverable failures inside graph nodes.

Covers budget exhaustion (BudgetExceeded) and structured-output failures
(StructuredOutputError). Both mark the session errored, emit session.error, and
return an ``error`` delta so the routers short-circuit to the complete node — a
clean stop instead of an uncaught exception crashing compiled.ainvoke().
"""

from __future__ import annotations

import uuid

import structlog

logger = structlog.get_logger(__name__)


async def abort_session(
    db, session_id: uuid.UUID, exc: Exception, *, node: str, error_type: str,
) -> dict:
    """Mark the session errored, emit session.error, and return an error delta."""
    from studio.db.models import Session
    from studio.events.emitter import emit_event

    session = await db.get(Session, session_id)
    if session is not None:
        session.status = "error"
        await db.flush()

    await emit_event(
        db, session_id, "session.error",
        data={"error_type": error_type, "error_message": str(exc)},
        agent="orchestrator",
    )
    logger.warning("session_abort", node=node, error_type=error_type,
                   session_id=str(session_id), error=str(exc)[:200])
    return {"current_node": node, "error": str(exc)}


async def abort_on_agent_failure(db, session_id: uuid.UUID, exc: Exception, *, node: str) -> dict:
    """Classify a BudgetExceeded / StructuredOutputError and abort the session."""
    from studio.ai.budget import BudgetExceeded

    error_type = "budget_exceeded" if isinstance(exc, BudgetExceeded) else "structured_output_error"
    return await abort_session(db, session_id, exc, node=node, error_type=error_type)
