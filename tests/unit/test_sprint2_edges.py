"""Unit tests for the Sprint 2 routers (§2.3) — steps 4 & 5 logic."""

from __future__ import annotations

from studio.graph.edges import (
    design_agent_router,
    design_ux_router,
    reviewer_router,
    slice_done_router,
    ux_review_router,
    verify_router,
)


def test_design_agent_router_is_phase_aware():
    assert design_agent_router({"phase": "design"}) == "ux_agent"
    assert design_agent_router({"phase": "build"}) == "build_agent"
    assert design_agent_router({"phase": "build", "error": "x"}) == "complete"


def test_design_ux_loop_respects_limit():
    # needs revision + under limit → loop back to design
    s = {"design_ux_needs_revision": True, "design_ux_iterations": 1,
         "config": {"max_design_ux_loops": 3}}
    assert design_ux_router(s) == "design_agent"
    # at the limit → converge to skeleton
    s["design_ux_iterations"] = 3
    assert design_ux_router(s) == "skeleton_build"
    # no revision needed → proceed
    assert design_ux_router({"design_ux_needs_revision": False}) == "skeleton_build"


def test_verify_router_retries_build_then_design():
    fail = {"verification_passed": False}
    assert verify_router({**fail, "verify_retries": 0}) == "build_agent"
    assert verify_router({**fail, "verify_retries": 2}) == "build_agent"
    assert verify_router({**fail, "verify_retries": 3}) == "design_agent"  # exhausted
    assert verify_router({"verification_passed": True}) == "ux_review"


def test_ux_review_and_reviewer_and_slice_done_routers():
    assert ux_review_router({"ux_issues_found": True}) == "design_agent"
    assert ux_review_router({"ux_issues_found": False}) == "reviewer"
    assert reviewer_router({"reviewer_rejected": True}) == "build_agent"
    assert reviewer_router({"reviewer_rejected": False}) == "slice_done"
    assert slice_done_router({"remaining_slice_ids": ["x"]}) == "slice_plan"
    assert slice_done_router({"remaining_slice_ids": []}) == "human_gate_ship"
