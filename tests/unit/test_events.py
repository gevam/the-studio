"""Tests for studio.events.emitter and studio.events.replay."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_valid_event_types_not_empty():
    """VALID_EVENT_TYPES contains all mandatory event types from §7.2."""
    from studio.events.schemas import VALID_EVENT_TYPES

    assert len(VALID_EVENT_TYPES) > 20
    assert "session.created" in VALID_EVENT_TYPES
    assert "agent.started" in VALID_EVENT_TYPES
    assert "design_friction.reported" in VALID_EVENT_TYPES
    assert "human.checkpoint" in VALID_EVENT_TYPES


def test_event_log_entry_schema():
    """EventLogEntry validates and serialises correctly."""
    from studio.events.schemas import EventLogEntry

    entry = EventLogEntry(
        session_id=uuid.uuid4(),
        seq=1,
        event_type="session.created",
        data={"session_name": "test-session"},
    )
    assert entry.seq == 1
    assert entry.event_type == "session.created"
    assert entry.data["session_name"] == "test-session"
    assert entry.agent is None


def test_ws_event_schema():
    """WSEvent validates correctly."""
    from studio.events.schemas import WSEvent

    event = WSEvent(
        session_id=str(uuid.uuid4()),
        seq=5,
        event_type="agent.started",
        agent="design",
        loop="design_ux",
        data={"iteration": 1},
        timestamp="2026-05-27T12:00:00Z",
    )
    assert event.seq == 5
    assert event.agent == "design"


@pytest.mark.asyncio
async def test_emit_event_calls_db_and_broadcasts():
    """emit_event inserts a row and calls registered WebSocket callbacks."""
    from studio.events import emitter as emitter_mod
    from studio.events.emitter import emit_event

    session_id = uuid.uuid4()

    # Mock the DB session
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one.return_value = 1
    mock_db.execute.return_value = scalar_result
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    # Register a callback to verify broadcasting
    received: list[dict] = []

    async def cb(sid: str, event: dict) -> None:
        received.append(event)

    emitter_mod.register_ws_callback(cb)
    try:
        row = await emit_event(mock_db, session_id, "session.created", {"session_name": "x"})
        assert mock_db.add.called
        assert mock_db.flush.called
        assert len(received) == 1
        assert received[0]["event_type"] == "session.created"
    finally:
        emitter_mod.unregister_ws_callback(cb)


@pytest.mark.asyncio
async def test_replay_events_queries_by_seq():
    """replay_events executes a query filtered by since_seq."""
    from studio.events.replay import replay_events

    session_id = uuid.uuid4()
    mock_db = AsyncMock()

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    mock_db.execute = AsyncMock(return_value=result_mock)

    events = await replay_events(mock_db, session_id, since_seq=10)
    assert events == []
    mock_db.execute.assert_called_once()
