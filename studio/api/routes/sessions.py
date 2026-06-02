"""Session human-gate endpoints: approve / reject (§2.5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from studio.db.models import HumanDecision
from studio.db.session import get_db
from studio.events.emitter import emit_event

router = APIRouter(prefix="/api/sessions", tags=["human-gate"])


class GateDecision(BaseModel):
    feedback: str | None = None
    gate_type: str | None = None  # disambiguate when both gates could be pending


async def _resolve_gate(
    session_id: uuid.UUID, action: str, body: GateDecision, db: AsyncSession,
) -> dict:
    query = (
        select(HumanDecision)
        .where(HumanDecision.session_id == session_id)
        .where(HumanDecision.action == "pending")
    )
    if body.gate_type:
        query = query.where(HumanDecision.gate_type == body.gate_type)
    gate = await db.scalar(query.order_by(HumanDecision.created_at.desc()).limit(1))
    if gate is None:
        raise HTTPException(status_code=404, detail="No pending human gate for this session")

    gate.action = action
    gate.feedback = body.feedback
    gate.decided_at = datetime.now(UTC)
    await db.flush()
    await emit_event(
        db, session_id, "human.decision",
        data={"gate_type": gate.gate_type, "action": action, "has_feedback": bool(body.feedback)},
        agent="human",
    )
    await db.commit()
    return {"session_id": str(session_id), "gate_type": gate.gate_type, "action": action}


@router.post("/{session_id}/approve")
async def approve(
    session_id: uuid.UUID, body: GateDecision | None = None, db: AsyncSession = Depends(get_db),  # noqa: B008 — FastAPI dependency pattern
) -> dict:
    """Approve the session's pending human gate (records the decision + event)."""
    return await _resolve_gate(session_id, "approve", body or GateDecision(), db)


@router.post("/{session_id}/reject")
async def reject(
    session_id: uuid.UUID, body: GateDecision | None = None, db: AsyncSession = Depends(get_db),  # noqa: B008 — FastAPI dependency pattern
) -> dict:
    """Reject the session's pending human gate (records the decision + event)."""
    return await _resolve_gate(session_id, "reject", body or GateDecision(), db)
