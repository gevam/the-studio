"""design_agent node: wraps run_design_agent(), loads requirements from DB."""

from __future__ import annotations

import uuid

import structlog

from studio.graph.state import GraphState

logger = structlog.get_logger(__name__)


async def design_agent_node(state: GraphState, *, db, llm, prompt_loader, **_) -> dict:
    """Run the Design Agent and update state with new design digest."""
    from studio.agents.design import DesignAgentInput, run_design_agent
    from studio.db.models import DesignFriction, Requirement, Session

    session_id = uuid.UUID(state["session_id"])

    # Load requirements from DB
    from sqlalchemy import select
    req_result = await db.execute(
        select(Requirement)
        .where(Requirement.session_id == session_id)
        .where(Requirement.status == "active")
        .order_by(Requirement.created_at)
    )
    requirements = [r.title for r in req_result.scalars()]

    # Load session for project info
    session = await db.get(Session, session_id)
    project_name = session.name if session else "untitled"
    config = session.config or {} if session else {}
    project_path = config.get("project_path", "/tmp/studio-projects/" + str(session_id))

    # Load pending friction items if this is a revision
    trigger = state.get("current_loop", "design_build")
    pending_friction_ids = state.get("pending_friction_ids", [])
    friction_items: list[dict] = []

    if pending_friction_ids:
        trigger = "friction"
        friction_uuids = []
        for fid in pending_friction_ids:
            try:
                friction_uuids.append(uuid.UUID(fid))
            except ValueError:
                pass

        if friction_uuids:
            friction_result = await db.execute(
                select(DesignFriction)
                .where(DesignFriction.id.in_(friction_uuids))
            )
            for row in friction_result.scalars():
                friction_items.append({
                    "id": str(row.id),
                    "severity": row.severity,
                    "category": row.category,
                    "description": row.description,
                    "code_location": row.code_location or "",
                    "friction_score": float(row.friction_score or 0),
                })
    elif not state.get("design_digest"):
        trigger = "initial"

    agent_input = DesignAgentInput(
        session_id=session_id,
        design_digest=state.get("design_digest", ""),
        trigger=trigger,
        requirements=requirements,
        friction_items=friction_items,
        iteration=state.get("iteration", 0),
        budget_remaining={
            "tokens_remaining": state.get("token_budget", 500_000) - state.get("tokens_used", 0),
            "cost_remaining_usd": state.get("cost_budget", 50.0) - state.get("cost_usd", 0.0),
        },
        project_name=project_name,
        project_path=project_path,
        prev_version=state.get("design_version", 0),
    )

    output = await run_design_agent(agent_input, db, llm, prompt_loader)

    # Update session node pointer
    if session:
        session.current_node = "design_agent"
        session.tokens_used = (session.tokens_used or 0) + output.tokens_used
        session.cost_usd = float(session.cost_usd or 0) + output.cost_usd
        await db.flush()

    logger.info(
        "design_agent_node_complete",
        session_id=str(session_id),
        design_version=output.design.version,
        tokens_used=output.tokens_used,
    )

    return {
        "current_node": "design_agent",
        "design_digest": output.digest,
        "design_version": output.design.version,
        "design_section_ids": [s.id for s in output.design.sections],
        "pending_friction_ids": [],  # cleared — design has addressed them
        "tokens_used": state.get("tokens_used", 0) + output.tokens_used,
        "cost_usd": state.get("cost_usd", 0.0) + output.cost_usd,
        "iteration": state.get("iteration", 0) + 1,
    }
