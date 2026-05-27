"""Contract tests: event schema validation (§10.2 contract-tests job).

These tests verify that the event schema is correct and that all mandatory
fields defined in §7.2 are present in MANDATORY_FIELDS.
"""

import uuid
from datetime import UTC, datetime

import pytest


def test_all_mandatory_event_types_are_valid():
    """Every event type in MANDATORY_FIELDS is also in VALID_EVENT_TYPES."""
    from studio.events.schemas import MANDATORY_FIELDS, VALID_EVENT_TYPES

    for event_type in MANDATORY_FIELDS:
        assert event_type in VALID_EVENT_TYPES, (
            f"Event type '{event_type}' is in MANDATORY_FIELDS but not in VALID_EVENT_TYPES"
        )


def test_agent_started_mandatory_fields():
    """agent.started event has agent, loop, iteration in mandatory fields."""
    from studio.events.schemas import MANDATORY_FIELDS

    required = MANDATORY_FIELDS["agent.started"]
    assert "agent" in required
    assert "loop" in required
    assert "iteration" in required


def test_design_friction_mandatory_fields():
    """design_friction.reported has all required friction fields."""
    from studio.events.schemas import MANDATORY_FIELDS

    required = MANDATORY_FIELDS["design_friction.reported"]
    assert "severity" in required
    assert "category" in required
    assert "description" in required
    assert "friction_score" in required


def test_event_log_entry_round_trips():
    """EventLogEntry serialises and deserialises cleanly."""
    from studio.events.schemas import EventLogEntry

    session_id = uuid.uuid4()
    now = datetime.now(UTC)
    entry = EventLogEntry(
        id=42,
        session_id=session_id,
        seq=7,
        event_type="design.revised",
        agent="design",
        loop="design_ux",
        data={"version": 2, "reason": "ux_feedback", "sections_changed": ["modules"]},
        trace_id="trace-abc",
        span_id="span-xyz",
        duration_ms=1200,
        created_at=now,
    )

    dumped = entry.model_dump()
    reloaded = EventLogEntry(**dumped)

    assert reloaded.seq == 7
    assert reloaded.event_type == "design.revised"
    assert reloaded.data["version"] == 2
    assert reloaded.agent == "design"
    assert reloaded.duration_ms == 1200


def test_ws_event_has_required_envelope_fields():
    """WSEvent has all fields from the §6.2 envelope spec."""
    from studio.events.schemas import WSEvent

    event = WSEvent(
        session_id=str(uuid.uuid4()),
        seq=1,
        event_type="session.created",
        data={"session_name": "test"},
        timestamp=datetime.now(UTC).isoformat(),
    )

    # All envelope fields from §6.2
    assert hasattr(event, "session_id")
    assert hasattr(event, "seq")
    assert hasattr(event, "event_type")
    assert hasattr(event, "agent")
    assert hasattr(event, "loop")
    assert hasattr(event, "data")
    assert hasattr(event, "trace_id")
    assert hasattr(event, "span_id")
    assert hasattr(event, "timestamp")


def test_session_budget_warning_in_valid_types():
    """session.budget_warning is a valid event type (§9.4)."""
    from studio.events.schemas import VALID_EVENT_TYPES

    assert "session.budget_warning" in VALID_EVENT_TYPES


@pytest.mark.parametrize(
    "event_type",
    [
        "agent.started",
        "agent.completed",
        "design.revised",
        "design_friction.reported",
        "slice.started",
        "slice.verified",
        "verification.result",
        "human.checkpoint",
        "human.decision",
        "session.created",
        "session.completed",
        "session.error",
    ],
)
def test_core_event_types_present(event_type: str):
    """All core event types from §7.2 are in VALID_EVENT_TYPES."""
    from studio.events.schemas import VALID_EVENT_TYPES

    assert event_type in VALID_EVENT_TYPES
