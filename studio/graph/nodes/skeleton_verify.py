"""skeleton_verify node: runs verification and sets skeleton_verified flag."""

from __future__ import annotations

import uuid
from typing import Optional

import structlog

from studio.graph.state import GraphState

logger = structlog.get_logger(__name__)


async def skeleton_verify_node(state: GraphState, *, db, **_) -> dict:
    """Run deterministic checks on the built skeleton."""
    from studio.db.models import Session
    from studio.events.emitter import emit_event
    from studio.verification.runner import run_verification

    session_id = uuid.UUID(state["session_id"])

    session = await db.get(Session, session_id)
    config = session.config or {} if session else {}
    project_path = config.get("project_path", "/tmp/studio-projects/" + str(session_id))
    workdir = config.get("sandbox_workdir", "/project")

    slice_id: Optional[uuid.UUID] = None
    current_slice_id = state.get("current_slice_id")
    if current_slice_id:
        try:
            slice_id = uuid.UUID(current_slice_id)
        except ValueError:
            pass

    result = await run_verification(
        session_id=session_id,
        slice_id=slice_id,
        project_path=project_path,
        db=db,
        workdir=workdir,
    )

    # Update session
    if session:
        session.current_node = "skeleton_verify"
        await db.flush()

    if result.passed:
        await emit_event(
            db,
            session_id,
            "skeleton.validated",
            data={
                "passed": True,
                "coverage_pct": result.coverage_pct,
                "tests_run": result.tests_run,
                "duration_ms": result.duration_ms,
            },
            agent="verification",
        )
    else:
        logger.warning(
            "skeleton_verify_failed",
            session_id=str(session_id),
            failures=[c.name for c in result.check_results if not c.passed],
        )

    logger.info(
        "skeleton_verify_complete",
        session_id=str(session_id),
        passed=result.passed,
        duration_ms=result.duration_ms,
    )

    return {
        "current_node": "skeleton_verify",
        "skeleton_verified": result.passed,
        "verification_passed": result.passed,
    }
