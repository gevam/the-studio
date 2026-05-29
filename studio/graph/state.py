"""LangGraph state — thin projection from DB, never holds full artifacts."""

from typing import Optional
from typing_extensions import TypedDict
import uuid


class GraphState(TypedDict, total=False):
    """Thin state projection. All heavy data lives in Postgres."""

    # Identity
    session_id: str  # UUID as string for serialization
    session_version: int

    # Design (digest only — ≤500 tokens)
    design_digest: str
    design_version: int
    design_section_ids: list[str]

    # Loop counters
    current_loop: str   # "design_build" | "build_verify"
    current_node: str
    iteration: int
    design_ux_iterations: int
    build_iterations: int
    verify_retries: int

    # Routing flags
    skeleton_verified: bool
    pending_friction_ids: list[str]  # UUIDs as strings
    verification_passed: bool
    remaining_slice_ids: list[str]
    current_slice_id: Optional[str]

    # Budget
    tokens_used: int
    cost_usd: float
    token_budget: int
    cost_budget: float

    # Human gate (Sprint 2+)
    awaiting_human: bool
    human_gate_type: Optional[str]

    # Config
    config: dict

    # Observability
    trace_id: Optional[str]
    span_id: Optional[str]

    # Error
    error: Optional[str]
