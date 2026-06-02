"""Sprint 2 nodes: Design⇄UX loop, feature build/verify/ux-review/reviewer, slice plan.

Thin wrappers that run the agents (§4.2/§4.4), reuse the Sprint 1 build/verify
machinery for feature slices, and set the §2.4 routing flags the edges consume.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select

from studio.graph.state import GraphState

logger = structlog.get_logger(__name__)


async def _load_session(db, session_id):
    from studio.db.models import Session
    return await db.get(Session, session_id)


async def _requirements(db, session_id) -> list[str]:
    from studio.db.models import Requirement
    rows = await db.execute(
        select(Requirement).where(Requirement.session_id == session_id)
        .where(Requirement.status == "active").order_by(Requirement.created_at)
    )
    return [r.title for r in rows.scalars()]


async def ux_agent_node(state: GraphState, *, db, llm, prompt_loader, **_) -> dict:
    """UX design review (§4.2): defines the experience metric, flags design issues."""
    from studio.agents.ux import UXAgentInput, run_ux_agent

    session_id = uuid.UUID(state["session_id"])
    session = await _load_session(db, session_id)
    config = (session.config or {}) if session else {}

    out = await run_ux_agent(
        UXAgentInput(
            session_id=session_id,
            design_digest=state.get("design_digest", ""),
            context="design_review",
            project_name=session.name if session else "untitled",
            requirements=await _requirements(db, session_id),
            iteration=state.get("design_ux_iterations", 0),
        ),
        db, llm, prompt_loader,
    )
    review = out.review
    metric = review.experience_metric.model_dump() if review.experience_metric else {}
    if session is not None and metric:
        session.config = {**config, "experience_metric": metric}
        await db.flush()

    return {
        "current_node": "ux_agent",
        "design_ux_needs_revision": review.needs_design_revision,
        "experience_metric": metric or state.get("experience_metric", {}),
        "tokens_used": state.get("tokens_used", 0) + out.tokens_used,
        "cost_usd": state.get("cost_usd", 0.0) + out.cost_usd,
    }


async def design_ux_gate_node(state: GraphState, *, db, **_) -> dict:
    """Convergence checkpoint for the Design⇄UX loop — counts iterations (§2.2)."""
    return {
        "current_node": "design_ux_gate",
        "design_ux_iterations": state.get("design_ux_iterations", 0) + 1,
    }


async def slice_plan_node(state: GraphState, *, db, llm, prompt_loader, **_) -> dict:
    """Plan feature slices on first entry; thereafter pop the next planned slice."""
    from studio.agents.slice_planner import SlicePlanInput, plan_slices
    from studio.db.models import Slice

    session_id = uuid.UUID(state["session_id"])
    remaining = list(state.get("remaining_slice_ids", []) or [])

    if not remaining and not state.get("slices_planned"):
        session = await _load_session(db, session_id)
        result = await plan_slices(
            SlicePlanInput(
                session_id=session_id,
                design_digest=state.get("design_digest", ""),
                project_name=session.name if session else "untitled",
                requirements=await _requirements(db, session_id),
                iteration=state.get("iteration", 0),
            ),
            db, llm, prompt_loader,
        )
        remaining = result.slice_ids

    current = remaining.pop(0) if remaining else None
    if current:
        slice_row = await db.get(Slice, uuid.UUID(current))
        if slice_row:
            slice_row.status = "building"
            await db.flush()
    return {
        "current_node": "slice_plan",
        "slices_planned": True,
        "current_slice_id": current,
        "remaining_slice_ids": remaining,
    }


async def build_agent_node(state: GraphState, *, db, llm, prompt_loader, **_) -> dict:
    """Build the current feature slice via the coding agent (TDD); collect friction."""
    from studio.agents.build import BuildAgentInput, run_build_agent
    from studio.ai.budget import BudgetExceeded
    from studio.db.models import DesignFriction, Slice
    from studio.graph.nodes._budget import abort_on_budget

    session_id = uuid.UUID(state["session_id"])
    session = await _load_session(db, session_id)
    config = (session.config or {}) if session else {}
    project_path = config.get("project_path", f"/tmp/studio-projects/{session_id}")  # noqa: S108

    slice_id = state.get("current_slice_id")
    slice_row = await db.get(Slice, uuid.UUID(slice_id)) if slice_id else None
    slice_name = slice_row.name if slice_row else "feature-slice"
    slice_desc = slice_row.description if slice_row else ""

    agent_input = BuildAgentInput(
        session_id=session_id, design_digest=state.get("design_digest", ""),
        slice_name=slice_name, slice_description=slice_desc, slice_type="feature",
        project_name=session.name if session else "untitled", project_path=project_path,
        stack=config.get("stack", "python"), iteration=state.get("build_iterations", 0),
    )
    try:
        output = await run_build_agent(agent_input, db, llm, prompt_loader)
    except BudgetExceeded as exc:
        return await abort_on_budget(db, session_id, exc, node="build_agent")

    if slice_row and output.metrics:
        from studio.graph.nodes.skeleton_build import _clamp_metric
        slice_row.test_coverage = _clamp_metric(output.metrics.coverage_pct)
        slice_row.cyclomatic_complexity = _clamp_metric(output.metrics.max_cyclomatic_complexity)
        slice_row.coupling_score = _clamp_metric(output.metrics.coupling_score)
        slice_row.duplication_pct = _clamp_metric(output.metrics.duplication_pct)
        slice_row.status = "verifying"
        await db.flush()

    pending = [str(fid) for fid in (await db.execute(
        select(DesignFriction.id).where(DesignFriction.session_id == session_id)
        .where(DesignFriction.status == "open")
    )).scalars()]

    return {
        "current_node": "build_agent",
        "pending_friction_ids": pending,
        "build_iterations": state.get("build_iterations", 0) + 1,
        "tokens_used": state.get("tokens_used", 0) + output.tokens_used,
        "cost_usd": state.get("cost_usd", 0.0) + output.cost_usd,
    }


async def verify_node(state: GraphState, *, db, **_) -> dict:
    """Run the 7 deterministic checks on the current build; count retries on failure."""
    from studio.db.models import Session
    from studio.verification.runner import run_verification

    session_id = uuid.UUID(state["session_id"])
    session = await db.get(Session, session_id)
    config = (session.config or {}) if session else {}
    project_path = config.get("project_path", f"/tmp/studio-projects/{session_id}")  # noqa: S108
    slice_id = state.get("current_slice_id")

    result = await run_verification(
        session_id=session_id,
        slice_id=uuid.UUID(slice_id) if slice_id else None,
        project_path=project_path, db=db,
        workdir=config.get("sandbox_workdir", "/project"),
    )
    delta = {"current_node": "verify", "verification_passed": result.passed}
    if not result.passed:
        delta["verify_retries"] = state.get("verify_retries", 0) + 1
    else:
        delta["verify_retries"] = 0
    return delta


async def ux_review_node(state: GraphState, *, db, llm, prompt_loader, **_) -> dict:
    """UX review of the built slice against the experience metric (§4.2)."""
    from studio.agents.ux import UXAgentInput, run_ux_agent
    from studio.db.models import Slice

    session_id = uuid.UUID(state["session_id"])
    session = await _load_session(db, session_id)
    slice_id = state.get("current_slice_id")
    slice_row = await db.get(Slice, uuid.UUID(slice_id)) if slice_id else None

    out = await run_ux_agent(
        UXAgentInput(
            session_id=session_id, design_digest=state.get("design_digest", ""),
            context="slice_review", project_name=session.name if session else "untitled",
            experience_metric=state.get("experience_metric", {}),
            slice_name=slice_row.name if slice_row else "slice",
            slice_description=slice_row.description if slice_row else "",
            iteration=state.get("iteration", 0),
        ),
        db, llm, prompt_loader,
    )
    return {
        "current_node": "ux_review",
        "ux_issues_found": out.review.needs_design_revision,
        "tokens_used": state.get("tokens_used", 0) + out.tokens_used,
        "cost_usd": state.get("cost_usd", 0.0) + out.cost_usd,
    }


async def reviewer_node(state: GraphState, *, db, llm, prompt_loader, **_) -> dict:
    """Reviewer (§4.4) — runs after deterministic checks pass; different model."""
    from studio.agents.reviewer import ReviewerInput, run_reviewer
    from studio.db.models import Slice, VerificationResult

    session_id = uuid.UUID(state["session_id"])
    session = await _load_session(db, session_id)
    slice_id = state.get("current_slice_id")
    slice_row = await db.get(Slice, uuid.UUID(slice_id)) if slice_id else None

    vr = await db.scalar(
        select(VerificationResult).where(VerificationResult.session_id == session_id)
        .where(VerificationResult.passed.is_(True))
        .order_by(VerificationResult.created_at.desc()).limit(1)
    )
    result = await run_reviewer(
        ReviewerInput(
            session_id=session_id, design_digest=state.get("design_digest", ""),
            design_version=state.get("design_version", 1),
            project_name=session.name if session else "untitled",
            slice_id=uuid.UUID(slice_id) if slice_id else None,
            slice_name=slice_row.name if slice_row else "slice",
            slice_description=slice_row.description if slice_row else "",
            coverage_pct=float(vr.test_coverage) if vr and vr.test_coverage else 0.0,
            tests_run=vr.tests_run if vr else 0,
            iteration=state.get("iteration", 0),
        ),
        db, llm, prompt_loader,
    )
    return {
        "current_node": "reviewer",
        "reviewer_rejected": not result.output.passed,
        "tokens_used": state.get("tokens_used", 0) + result.tokens_used,
        "cost_usd": state.get("cost_usd", 0.0) + result.cost_usd,
    }


async def slice_done_node(state: GraphState, *, db, **_) -> dict:
    """Mark the current slice done; the router checks for remaining slices (§2.3)."""
    from studio.db.models import Slice

    slice_id = state.get("current_slice_id")
    if slice_id:
        slice_row = await db.get(Slice, uuid.UUID(slice_id))
        if slice_row:
            slice_row.status = "done"
            await db.flush()
    return {
        "current_node": "slice_done",
        "current_slice_id": None,
        # reset per-slice retry counters for the next slice
        "verify_retries": 0,
    }
