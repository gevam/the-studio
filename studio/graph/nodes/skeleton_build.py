"""skeleton_build node: creates Slice record and runs BuildAgent."""

from __future__ import annotations

import uuid
from pathlib import Path

import structlog

from studio.graph.state import GraphState

logger = structlog.get_logger(__name__)

# Slice quality columns are NUMERIC(5, 2): |value| < 1000. Clamp before persisting
# so a runaway metric degrades the recorded number instead of crashing the graph.
_METRIC_MAX = 999.99


def _clamp_metric(value: float | None) -> float | None:
    if value is None:
        return None
    return max(-_METRIC_MAX, min(round(float(value), 2), _METRIC_MAX))


async def skeleton_build_node(state: GraphState, *, db, llm, prompt_loader, **_) -> dict:
    """Run the Build Agent to build the walking skeleton."""
    from studio.agents.build import BuildAgentInput, run_build_agent
    from studio.db.models import Session, Slice

    session_id = uuid.UUID(state["session_id"])

    session = await db.get(Session, session_id)
    config = session.config or {} if session else {}
    project_name = session.name if session else "untitled"
    project_path = config.get(
        "project_path", "/tmp/studio-projects/" + str(session_id)
    )
    stack = config.get("stack", "python")

    # Ensure project directory exists
    Path(project_path).mkdir(parents=True, exist_ok=True)

    # Create or reuse skeleton Slice record
    from sqlalchemy import select
    existing = await db.execute(
        select(Slice)
        .where(Slice.session_id == session_id)
        .where(Slice.slice_type == "skeleton")
        .limit(1)
    )
    slice_row = existing.scalar_one_or_none()

    if slice_row is None:
        slice_row = Slice(
            session_id=session_id,
            name="walking-skeleton",
            description="Thin vertical slice proving architecture end-to-end",
            slice_type="skeleton",
            status="building",
            order_index=0,
            design_version=state.get("design_version", 1),
        )
        db.add(slice_row)
        await db.flush()
    else:
        slice_row.status = "building"
        await db.flush()

    from studio.events.emitter import emit_event

    await emit_event(
        db,
        session_id,
        "slice.started",
        data={
            "slice_id": str(slice_row.id),
            "slice_name": slice_row.name,
            "slice_type": slice_row.slice_type,
        },
        agent="orchestrator",
    )

    agent_input = BuildAgentInput(
        session_id=session_id,
        design_digest=state.get("design_digest", ""),
        slice_name="walking-skeleton",
        slice_description="Build a thin vertical slice: entry point → logic → data → persistence",
        slice_type="skeleton",
        project_name=project_name,
        project_path=project_path,
        stack=stack,
        iteration=state.get("iteration", 0),
        budget_remaining={
            "tokens_remaining": state.get("token_budget", 500_000) - state.get("tokens_used", 0),
            "cost_remaining_usd": state.get("cost_budget", 50.0) - state.get("cost_usd", 0.0),
        },
    )

    from studio.ai.budget import BudgetExceeded
    from studio.graph.nodes._budget import abort_on_budget

    try:
        output = await run_build_agent(agent_input, db, llm, prompt_loader)
    except BudgetExceeded as exc:
        return await abort_on_budget(db, session_id, exc, node="skeleton_build")

    # Update slice with quality metrics
    slice_row.status = "done"
    if output.metrics:
        slice_row.test_coverage = _clamp_metric(output.metrics.coverage_pct)
        slice_row.cyclomatic_complexity = _clamp_metric(output.metrics.max_cyclomatic_complexity)
        slice_row.coupling_score = _clamp_metric(output.metrics.coupling_score)
        slice_row.duplication_pct = _clamp_metric(output.metrics.duplication_pct)
    await db.flush()

    # Update session
    if session:
        session.current_node = "skeleton_build"
        session.tokens_used = (session.tokens_used or 0) + output.tokens_used
        session.cost_usd = float(session.cost_usd or 0) + output.cost_usd
        await db.flush()

    # Collect friction IDs that were just persisted to DB
    from studio.db.models import DesignFriction
    friction_result = await db.execute(
        select(DesignFriction.id)
        .where(DesignFriction.session_id == session_id)
        .where(DesignFriction.status == "open")
    )
    pending_friction_ids = [str(fid) for fid in friction_result.scalars()]

    await emit_event(
        db,
        session_id,
        "slice.built",
        data={
            "slice_id": str(slice_row.id),
            "files_changed": len(output.files_changed),
            "tests_written": len(output.tests_written),
            "friction_count": len(output.friction_items),
        },
        agent="build_agent",
    )

    logger.info(
        "skeleton_build_complete",
        session_id=str(session_id),
        files_changed=len(output.files_changed),
        friction_items=len(output.friction_items),
        pending_friction=len(pending_friction_ids),
    )

    return {
        "current_node": "skeleton_build",
        "pending_friction_ids": pending_friction_ids,
        "tokens_used": state.get("tokens_used", 0) + output.tokens_used,
        "cost_usd": state.get("cost_usd", 0.0) + output.cost_usd,
        "current_slice_id": str(slice_row.id),
    }
