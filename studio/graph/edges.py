"""Conditional routing functions for the LangGraph StateGraph."""

from studio.graph.state import GraphState


def skeleton_verify_router(state: GraphState) -> str:
    """After skeleton verification: failed → design_agent, passed → complete."""
    if state.get("error"):
        return "complete"  # hard stop (e.g. budget exceeded)

    max_iterations = (state.get("config") or {}).get("max_design_iterations", 5)
    iteration = state.get("iteration", 0)

    if not state.get("skeleton_verified", False):
        if iteration >= max_iterations:
            return "complete"  # give up, mark error
        return "design_agent"

    return "complete"


def build_friction_router(state: GraphState) -> str:
    """After skeleton build: friction pending → design_agent, clean → skeleton_verify."""
    if state.get("error"):
        return "complete"  # hard stop (e.g. budget exceeded)

    max_iterations = (state.get("config") or {}).get("max_design_iterations", 5)
    pending = state.get("pending_friction_ids", [])
    if pending and state.get("iteration", 0) < max_iterations:
        return "design_agent"
    return "skeleton_verify"


def design_to_build_router(state: GraphState) -> str:
    """After the design agent: hard stop on error, else proceed to build."""
    if state.get("error"):
        return "complete"
    return "skeleton_build"


# ── Sprint 2 routers (§2.3) ─────────────────────────────────────────────────
# Every router short-circuits to "complete" on a hard error (e.g. budget). The
# design_agent return edge is phase-aware: in the design phase it re-enters the
# Design⇄UX loop, in the build phase it returns to the feature build.

def _max_design_ux(state: GraphState) -> int:
    return (state.get("config") or {}).get("max_design_ux_loops", 3)


def design_agent_router(state: GraphState) -> str:
    """After design_agent: UX loop (design phase) or back to build (build phase)."""
    if state.get("error"):
        return "complete"
    return "build_agent" if state.get("phase") == "build" else "ux_agent"


def design_ux_router(state: GraphState) -> str:
    """After the Design⇄UX gate: loop back to design, or proceed to the skeleton."""
    if state.get("error"):
        return "complete"
    needs = state.get("design_ux_needs_revision")
    if needs and state.get("design_ux_iterations", 0) < _max_design_ux(state):
        return "design_agent"
    return "skeleton_build"


def skeleton_friction_router(state: GraphState) -> str:
    """After skeleton build: design friction → design, else verify the skeleton."""
    if state.get("error"):
        return "complete"
    max_it = (state.get("config") or {}).get("max_design_iterations", 5)
    if state.get("pending_friction_ids") and state.get("iteration", 0) < max_it:
        return "design_agent"
    return "skeleton_verify"


def skeleton_verify_gate_router(state: GraphState) -> str:
    """After skeleton verify: pass → design approval gate, fail → design (or give up)."""
    if state.get("error"):
        return "complete"
    max_it = (state.get("config") or {}).get("max_design_iterations", 5)
    if not state.get("skeleton_verified", False):
        return "complete" if state.get("iteration", 0) >= max_it else "design_agent"
    return "human_gate_design"


def human_gate_design_router(state: GraphState) -> str:
    """After the design gate: approve → plan slices, reject → revise design."""
    if state.get("error"):
        return "complete"
    return "design_agent" if state.get("human_gate_action") == "reject" else "slice_plan"


def feature_friction_router(state: GraphState) -> str:
    """After a feature build: design friction → design, else verify the slice."""
    if state.get("error"):
        return "complete"
    return "design_agent" if state.get("pending_friction_ids") else "verify"


def verify_router(state: GraphState) -> str:
    """After verify: pass → UX review; fail → Build (retry, max 3) then Design (§2.3)."""
    if state.get("error"):
        return "complete"
    if not state.get("verification_passed", False):
        return "build_agent" if state.get("verify_retries", 0) < 3 else "design_agent"
    return "ux_review"


def ux_review_router(state: GraphState) -> str:
    if state.get("error"):
        return "complete"
    return "design_agent" if state.get("ux_issues_found") else "reviewer"


def reviewer_router(state: GraphState) -> str:
    if state.get("error"):
        return "complete"
    return "build_agent" if state.get("reviewer_rejected") else "slice_done"


def slice_done_router(state: GraphState) -> str:
    if state.get("error"):
        return "complete"
    return "slice_plan" if state.get("remaining_slice_ids") else "human_gate_ship"
