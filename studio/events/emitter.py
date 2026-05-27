"""Event emitter: appends to event_log with monotonic seq per session."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from studio.db.models import EventLog
from studio.events.schemas import VALID_EVENT_TYPES

logger = structlog.get_logger(__name__)

# WebSocket broadcast callbacks registered by the API layer
_ws_callbacks: list[Callable] = []


def register_ws_callback(cb: Callable) -> None:
    """Register a function to call after each event is emitted."""
    _ws_callbacks.append(cb)


def unregister_ws_callback(cb: Callable) -> None:
    _ws_callbacks.remove(cb)


async def emit_event(
    db: AsyncSession,
    session_id: uuid.UUID,
    event_type: str,
    data: dict[str, Any] | None = None,
    *,
    agent: str | None = None,
    loop: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    duration_ms: int | None = None,
) -> EventLog:
    """Append an event to event_log with the next monotonic seq for this session.

    Returns the persisted EventLog row. The seq is generated atomically inside
    the calling transaction using SELECT … FOR UPDATE to prevent races.
    """
    if event_type not in VALID_EVENT_TYPES:
        logger.warning("unknown_event_type", event_type=event_type)

    # Lock the session row to serialize seq generation, then compute MAX.
    # FOR UPDATE on an aggregate is not allowed in PostgreSQL, so we hold
    # the session row lock instead and compute the aggregate separately.
    lock_result = await db.execute(
        text("SELECT id FROM sessions WHERE id = :sid FOR UPDATE"),
        {"sid": session_id},
    )
    if lock_result.scalar_one_or_none() is None:
        raise ValueError(f"Session {session_id} not found — cannot emit event")
    result = await db.execute(
        text(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq "
            "FROM event_log "
            "WHERE session_id = :sid"
        ),
        {"sid": session_id},
    )
    next_seq: int = result.scalar_one()

    row = EventLog(
        session_id=session_id,
        seq=next_seq,
        event_type=event_type,
        agent=agent,
        loop=loop,
        data=data or {},
        trace_id=trace_id,
        span_id=span_id,
        duration_ms=duration_ms,
    )
    db.add(row)
    await db.flush()  # assign id, created_at without committing

    logger.info(
        "event_emitted",
        session_id=str(session_id),
        seq=next_seq,
        event_type=event_type,
        agent=agent,
    )

    # Broadcast to WebSocket listeners (best-effort, non-blocking)
    event_dict = {
        "session_id": str(session_id),
        "seq": next_seq,
        "event_type": event_type,
        "agent": agent,
        "loop": loop,
        "data": data or {},
        "trace_id": trace_id,
        "span_id": span_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    for cb in _ws_callbacks:
        try:
            await cb(str(session_id), event_dict)
        except Exception:
            logger.exception("ws_broadcast_error", event_type=event_type)

    return row
