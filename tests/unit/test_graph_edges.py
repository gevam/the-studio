"""Tests for graph routing edges."""

import pytest
from studio.graph.edges import build_friction_router, skeleton_verify_router
from studio.graph.state import GraphState


def _state(**kwargs) -> GraphState:
    base: GraphState = {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "iteration": 0,
        "skeleton_verified": False,
        "pending_friction_ids": [],
        "config": {},
    }
    base.update(kwargs)  # type: ignore[typeddict-item]
    return base


class TestBuildFrictionRouter:
    def test_with_friction_goes_to_design_agent(self):
        state = _state(pending_friction_ids=["id-1", "id-2"])
        assert build_friction_router(state) == "design_agent"

    def test_without_friction_goes_to_verify(self):
        state = _state(pending_friction_ids=[])
        assert build_friction_router(state) == "skeleton_verify"

    def test_empty_list_goes_to_verify(self):
        state = _state()
        assert build_friction_router(state) == "skeleton_verify"


class TestSkeletonVerifyRouter:
    def test_verified_goes_to_complete(self):
        state = _state(skeleton_verified=True)
        assert skeleton_verify_router(state) == "complete"

    def test_not_verified_under_max_goes_to_design(self):
        state = _state(skeleton_verified=False, iteration=2, config={"max_design_iterations": 5})
        assert skeleton_verify_router(state) == "design_agent"

    def test_not_verified_at_max_goes_to_complete(self):
        state = _state(skeleton_verified=False, iteration=5, config={"max_design_iterations": 5})
        assert skeleton_verify_router(state) == "complete"

    def test_default_max_is_5(self):
        state = _state(skeleton_verified=False, iteration=4, config={})
        assert skeleton_verify_router(state) == "design_agent"

        state2 = _state(skeleton_verified=False, iteration=5, config={})
        assert skeleton_verify_router(state2) == "complete"
