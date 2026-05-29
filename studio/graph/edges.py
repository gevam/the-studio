"""Conditional routing functions for the LangGraph StateGraph."""

from studio.graph.state import GraphState


def skeleton_verify_router(state: GraphState) -> str:
    """After skeleton verification: failed → design_agent, passed → complete."""
    max_iterations = (state.get("config") or {}).get("max_design_iterations", 5)
    iteration = state.get("iteration", 0)

    if not state.get("skeleton_verified", False):
        if iteration >= max_iterations:
            return "complete"  # give up, mark error
        return "design_agent"

    return "complete"


def build_friction_router(state: GraphState) -> str:
    """After skeleton build: friction pending → design_agent, clean → skeleton_verify."""
    max_iterations = (state.get("config") or {}).get("max_design_iterations", 5)
    pending = state.get("pending_friction_ids", [])
    if pending and state.get("iteration", 0) < max_iterations:
        return "design_agent"
    return "skeleton_verify"
