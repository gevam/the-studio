"""LangGraph state — thin projection from DB, never holds full artifacts."""


from typing_extensions import TypedDict


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
    current_slice_id: str | None

    # Sprint 2 routing flags (§2.4)
    phase: str  # "design" (pre-skeleton-approval) | "build" (feature slices)
    slices_planned: bool
    design_ux_needs_revision: bool
    ux_issues_found: bool
    reviewer_rejected: bool
    human_gate_action: str | None  # "approve" | "reject"
    experience_metric: dict

    # Budget
    tokens_used: int
    cost_usd: float
    token_budget: int
    cost_budget: float

    # Human gate (Sprint 2+)
    awaiting_human: bool
    human_gate_type: str | None

    # Config
    config: dict

    # Observability
    trace_id: str | None
    span_id: str | None

    # Error
    error: str | None
