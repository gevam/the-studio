"""Event type definitions and schema validation."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# All valid event types (§6.2 + §7.2)
VALID_EVENT_TYPES: frozenset[str] = frozenset(
    [
        # Agent lifecycle
        "agent.started",
        "agent.completed",
        "agent.llm_call",
        "agent.llm_response",
        "agent.token_stream",
        # Design
        "design.revised",
        "design_friction.reported",
        # Skeleton
        "skeleton.validated",
        # Slices
        "slice.started",
        "slice.built",
        "slice.verified",
        # Verification
        "verification.result",
        # Reviewer
        "reviewer.evaluated",
        # Human
        "human.checkpoint",
        "human.decision",
        # External
        "requirement.changed",
        "jira.synced",
        "git.committed",
        # Session
        "session.created",
        "session.completed",
        "session.error",
        "session.budget_warning",
        # AI-native
        "ai.feedback_recorded",
        "ai.suggestion_created",
    ]
)

# Required data fields per event type (subset of §7.2)
MANDATORY_FIELDS: dict[str, set[str]] = {
    "agent.started": {"agent", "loop", "iteration"},
    "agent.completed": {"agent", "loop", "iteration", "duration_ms", "tokens_used"},
    "agent.llm_call": {"agent", "model", "prompt_hash", "tokens_in"},
    "agent.llm_response": {"agent", "model", "tokens_out", "latency_ms", "cost_usd"},
    "design.revised": {"version", "reason", "caused_by", "sections_changed"},
    "design_friction.reported": {
        "severity",
        "category",
        "description",
        "friction_score",
        "slice_id",
    },
    "skeleton.validated": {"passed", "duration_ms"},
    "slice.started": {"slice_id", "slice_name", "slice_type"},
    "slice.built": {"slice_id", "files_changed", "tests_written", "friction_count"},
    "slice.verified": {"slice_id", "passed", "coverage", "complexity"},
    "verification.result": {"build_passed", "test_passed", "lint_passed", "duration_ms"},
    "reviewer.evaluated": {"overall_score", "passed", "issues_count", "model_used"},
    "human.checkpoint": {"gate_type", "expires_at"},
    "human.decision": {"gate_type", "action", "has_feedback"},
    "requirement.changed": {"requirement_id", "change_type"},
    "jira.synced": {"jira_key", "sync_type"},
    "git.committed": {"commit_hash", "files_changed"},
    "session.created": {"session_name"},
    "session.completed": {"total_duration_ms", "total_cost_usd", "total_tokens"},
    "session.error": {"error_type", "error_message"},
    "ai.feedback_recorded": {"agent", "quality_signal"},
    "ai.suggestion_created": {"agent", "suggestion_type"},
}


class EventLogEntry(BaseModel):
    """DB row projection for event_log."""

    id: int | None = None
    session_id: UUID
    seq: int
    event_type: str
    agent: str | None = None
    loop: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    span_id: str | None = None
    duration_ms: int | None = None
    created_at: datetime | None = None


class WSEvent(BaseModel):
    """WebSocket event envelope (§6.2)."""

    session_id: str
    seq: int
    event_type: str
    agent: str | None = None
    loop: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    span_id: str | None = None
    timestamp: str
