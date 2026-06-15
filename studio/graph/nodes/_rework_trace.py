"""Rework-loop instrumentation (DIAGNOSTIC — observability only, no behavior change).

Emits a `rework.attempt` event (and a structlog line) on each rework iteration so
the cap-hitting behaviour can be analysed post-run. Gated on config["rework_trace"];
off by default. Touches no router, cap, or counter — it only records.

Throwaway by default (branch diag/cap-investigation). Promote into Sprint 2 proper
only if the §7.5 dashboards want per-attempt rejection history.
"""

from __future__ import annotations

import uuid

import structlog

logger = structlog.get_logger(__name__)


def _enabled(state) -> bool:
    return bool((state.get("config") or {}).get("rework_trace"))


async def trace_rework(
    db, session_id: uuid.UUID, state, *, loop_type: str, slice_id, slice_name: str, details: dict,
) -> None:
    """Record one rework iteration if tracing is enabled (no-op otherwise)."""
    if not _enabled(state):
        return
    from studio.events.emitter import emit_event

    budget = state.get("slice_rework_budget") or (state.get("config") or {}).get(
        "slice_rework_budget", 8
    )
    data = {
        "loop_type": loop_type,
        "slice_id": str(slice_id) if slice_id else None,
        "slice_name": slice_name,
        "attempt": state.get("slice_rework_used", 0),  # reworks already spent this slice
        "budget": budget,
        **details,
    }
    await emit_event(db, session_id, "rework.attempt", data=data, agent="diagnostic")
    logger.debug("rework.attempt", **{k: v for k, v in data.items() if k != "issues"},
                 issues_count=len(details.get("issues", []) or []))
