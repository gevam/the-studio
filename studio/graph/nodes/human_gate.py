"""Human gate node (§2.5): hard approval gate via LangGraph interrupt.

Used for both the design-approval and ship-approval gates. Emits human.checkpoint
on entry and human.decision on resolution. In interactive runs it pauses the graph
with interrupt() and resumes on a Command(resume={"action", "feedback"}); benchmark
runs set config["auto_approve_gates"] to proceed without a human.

interrupt() re-executes the node from the top on resume, so the pre-interrupt side
effects (gate row + checkpoint event) are guarded to fire exactly once per gate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from langgraph.types import interrupt
from sqlalchemy import select

from studio.graph.state import GraphState

logger = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT_HOURS = 24


def _diff_summary(state: GraphState, gate_type: str) -> dict:
    if gate_type == "design":
        return {
            "design_version": state.get("design_version", 0),
            "sections": len(state.get("design_section_ids", []) or []),
        }
    return {
        "slices_done": len(state.get("remaining_slice_ids", []) or []) == 0,
        "iterations": state.get("iteration", 0),
    }


def make_human_gate_node(gate_type: str):
    """Build a human-gate node bound to a gate type ("design" | "ship")."""

    async def human_gate_node(state: GraphState, *, db, **_) -> dict:
        from studio.db.models import HumanDecision
        from studio.events.emitter import emit_event

        session_id = uuid.UUID(state["session_id"])
        config = state.get("config") or {}

        # Idempotent entry: reuse an existing pending gate (set on the first pass,
        # found again when interrupt() re-runs the node on resume).
        gate = await db.scalar(
            select(HumanDecision)
            .where(HumanDecision.session_id == session_id)
            .where(HumanDecision.gate_type == gate_type)
            .where(HumanDecision.action == "pending")
            .order_by(HumanDecision.created_at.desc())
            .limit(1)
        )
        if gate is None:
            expires_at = datetime.now(UTC) + timedelta(
                hours=config.get("human_gate_timeout_hours", _DEFAULT_TIMEOUT_HOURS)
            )
            diff = _diff_summary(state, gate_type)
            gate = HumanDecision(
                session_id=session_id, gate_type=gate_type, action="pending",
                diff_snapshot=diff, expires_at=expires_at,
            )
            db.add(gate)
            await db.flush()
            await emit_event(
                db, session_id, "human.checkpoint",
                data={"gate_type": gate_type, "expires_at": expires_at.isoformat(),
                      "diff_summary": diff},
                agent="orchestrator",
            )
            # Commit the checkpoint durably *before* interrupt() raises, so the gate
            # is observable while the graph is paused (and the resume re-run finds it).
            await db.commit()

        # Resolve the decision: auto-approve (benchmark) or pause for a human.
        if config.get("auto_approve_gates"):
            decision = {"action": "approve", "feedback": ""}
        else:
            decision = interrupt({
                "gate_type": gate_type,
                "expires_at": gate.expires_at.isoformat(),
                "diff_summary": gate.diff_snapshot,
            }) or {}

        action = decision.get("action", "approve")
        feedback = decision.get("feedback", "") or ""
        gate.action = action
        gate.feedback = feedback or None
        gate.decided_at = datetime.now(UTC)
        await db.flush()

        await emit_event(
            db, session_id, "human.decision",
            data={"gate_type": gate_type, "action": action, "has_feedback": bool(feedback)},
            agent="human",
        )
        logger.info("human_gate_resolved", session_id=str(session_id),
                    gate_type=gate_type, action=action)

        return {
            "current_node": f"human_gate_{gate_type}",
            "awaiting_human": False,
            "human_gate_type": gate_type,
            "human_gate_action": action,
        }

    human_gate_node.__name__ = f"human_gate_{gate_type}"
    return human_gate_node
