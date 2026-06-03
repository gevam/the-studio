"""Unit tests for the Sprint 2 routers (§2.3) — unified per-slice rework budget."""

from __future__ import annotations

from studio.graph.edges import (
    design_agent_router,
    design_ux_router,
    feature_friction_router,
    reviewer_router,
    slice_done_router,
    ux_review_router,
    verify_router,
)


def _state(used: int, budget: int = 3, **extra) -> dict:
    return {"slice_rework_budget": budget, "slice_rework_used": used, **extra}


def test_design_agent_router_is_phase_aware():
    assert design_agent_router({"phase": "design"}) == "ux_agent"
    assert design_agent_router({"phase": "build"}) == "build_agent"
    assert design_agent_router({"phase": "build", "error": "x"}) == "complete"


def test_every_rework_loop_shares_one_budget():
    # Under budget → rework; at/over budget → accept-on-cap and move forward.
    assert design_ux_router(_state(1, design_ux_needs_revision=True)) == "design_agent"
    assert design_ux_router(_state(3, design_ux_needs_revision=True)) == "skeleton_build"

    assert feature_friction_router(_state(1, pending_friction_ids=["f"])) == "design_agent"
    assert feature_friction_router(_state(3, pending_friction_ids=["f"])) == "verify"

    assert ux_review_router(_state(1, ux_issues_found=True)) == "design_agent"
    assert ux_review_router(_state(3, ux_issues_found=True)) == "reviewer"

    assert reviewer_router(_state(1, reviewer_rejected=True)) == "build_agent"
    assert reviewer_router(_state(3, reviewer_rejected=True)) == "slice_done"


def test_verify_fail_accepts_on_cap_instead_of_looping_to_design():
    # CR #1 regression: the old verify_retries<3→design path was unbounded. The
    # shared budget now retries build while budget remains, then accepts forward.
    assert verify_router(_state(0, verification_passed=False)) == "build_agent"
    assert verify_router(_state(2, verification_passed=False)) == "build_agent"
    assert verify_router(_state(3, verification_passed=False)) == "ux_review"  # not design!
    assert verify_router(_state(0, verification_passed=True)) == "ux_review"


def test_no_signal_proceeds_forward():
    assert design_ux_router(_state(0, design_ux_needs_revision=False)) == "skeleton_build"
    assert feature_friction_router(_state(0, pending_friction_ids=[])) == "verify"
    assert ux_review_router(_state(0, ux_issues_found=False)) == "reviewer"
    assert reviewer_router(_state(0, reviewer_rejected=False)) == "slice_done"


def test_budget_falls_back_to_config_when_state_unset():
    # No slice_rework_budget in state → read from config.
    s = {"config": {"slice_rework_budget": 2}, "slice_rework_used": 2,
         "ux_issues_found": True}
    assert ux_review_router(s) == "reviewer"  # used(2) >= budget(2) → forward


def test_slice_done_and_error_routing():
    assert slice_done_router({"remaining_slice_ids": ["x"]}) == "slice_plan"
    assert slice_done_router({"remaining_slice_ids": []}) == "human_gate_ship"
    for router in (design_ux_router, feature_friction_router, verify_router,
                   ux_review_router, reviewer_router, slice_done_router):
        assert router({"error": "boom"}) == "complete"
