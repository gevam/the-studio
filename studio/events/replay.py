"""Event replay: query event_log by session_id and seq range."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from studio.db.models import EventLog
from studio.events.schemas import EventLogEntry


async def replay_events(
    db: AsyncSession,
    session_id: uuid.UUID,
    since_seq: int = 0,
    limit: int = 1000,
) -> list[EventLogEntry]:
    """Return events for a session with seq > since_seq, ordered by seq."""
    result = await db.execute(
        select(EventLog)
        .where(EventLog.session_id == session_id)
        .where(EventLog.seq > since_seq)
        .order_by(EventLog.seq)
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        EventLogEntry(
            id=row.id,
            session_id=row.session_id,
            seq=row.seq,
            event_type=row.event_type,
            agent=row.agent,
            loop=row.loop,
            data=row.data,
            trace_id=row.trace_id,
            span_id=row.span_id,
            duration_ms=row.duration_ms,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def get_last_seq(db: AsyncSession, session_id: uuid.UUID) -> int:
    """Return the highest seq for the session, or 0 if no events."""
    result = await db.execute(
        select(EventLog.seq)
        .where(EventLog.session_id == session_id)
        .order_by(EventLog.seq.desc())
        .limit(1)
    )
    seq = result.scalar_one_or_none()
    return seq if seq is not None else 0
