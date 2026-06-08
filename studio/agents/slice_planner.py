"""Slice planner (§12 step 8): plan feature slices from requirements + design.

Includes a scope-creep detector that drops planned slices which cite no known
requirement, enforcing requirement→slice traceability.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

import structlog
from pydantic import BaseModel

from studio.ai.llm_client import LLMClient
from studio.ai.prompt_loader import PromptLoader

logger = structlog.get_logger(__name__)


class PlannedSlice(BaseModel):
    name: str
    description: str = ""
    requirement_titles: list[str] = []
    rationale: str = ""


class SlicePlan(BaseModel):
    """Structured output of the slice planner."""

    slices: list[PlannedSlice] = []


@dataclass
class SlicePlanInput:
    session_id: uuid.UUID
    design_digest: str
    project_name: str
    requirements: list[str] = field(default_factory=list)
    iteration: int = 0


@dataclass
class SlicePlanResult:
    slice_ids: list[str]
    dropped: list[str]
    tokens_used: int
    cost_usd: float


def _tokens(text: str) -> set[str]:
    """Significant lowercase word tokens (len ≥ 3) of a title."""
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3}


def _fuzzy_matches(text: str, req_lower: list[str], req_tokens: list[set[str]]) -> bool:
    """Case-insensitive substring (either direction) or shared-token match."""
    t = text.strip().lower()
    if not t:
        return False
    toks = _tokens(t)
    for rl, rt in zip(req_lower, req_tokens, strict=False):
        if t in rl or rl in t or (toks & rt):
            return True
    return False


def detect_scope_creep(
    slices: list[PlannedSlice], requirement_titles: list[str]
) -> tuple[list[PlannedSlice], list[str], bool]:
    """Split planned slices into (in_scope, dropped_names, used_fallback).

    A slice is in scope when its name or any cited requirement_title fuzzily
    matches a real requirement (substring or shared significant token) — LLMs
    paraphrase titles, so exact matching dropped legitimate slices (CR #5). If
    fuzzy matching would drop *everything*, we keep all slices and signal a
    fallback (never silently ship an empty MVP).
    """
    req_lower = [t.strip().lower() for t in requirement_titles]
    req_tokens = [_tokens(t) for t in requirement_titles]

    in_scope: list[PlannedSlice] = []
    dropped: list[str] = []
    for s in slices:
        candidates = [s.name, *s.requirement_titles]
        if any(_fuzzy_matches(c, req_lower, req_tokens) for c in candidates):
            in_scope.append(s)
        else:
            dropped.append(s.name)

    if slices and not in_scope:
        return slices, [], True  # fuzzy match too strict — keep all, flag fallback
    return in_scope, dropped, False


async def plan_slices(
    input: SlicePlanInput,
    db,  # AsyncSession
    llm: LLMClient,
    prompt_loader: PromptLoader,
    *,
    skeleton_order: int = 1,
) -> SlicePlanResult:
    """Plan feature slices, drop scope creep, and persist Slice rows (planned)."""
    from studio.db.models import Slice
    from studio.events.emitter import emit_event

    await emit_event(
        db, input.session_id, "agent.started",
        data={"agent": "slice_planner", "loop": "design_build", "iteration": input.iteration},
        agent="slice_planner",
    )

    system_tpl = prompt_loader.load("slice_planner", "system")
    plan_tpl = prompt_loader.load("slice_planner", "plan")
    user_content = prompt_loader.render(
        plan_tpl.content,
        project_name=input.project_name,
        design_digest=input.design_digest,
        requirements="\n".join(f"- {r}" for r in input.requirements) or "none",
    )

    result = await llm.complete_structured(
        agent="slice_planner",
        system_prompt=system_tpl.content,
        user_content=user_content,
        schema=SlicePlan,
        max_tokens=4096,
        temperature=0.0,
        prompt_hash=plan_tpl.hash,
        session_id=input.session_id,
        db=db,
    )
    plan: SlicePlan = result.parsed
    in_scope, dropped, used_fallback = detect_scope_creep(plan.slices, input.requirements)
    if dropped:
        logger.warning("scope_creep_dropped", session_id=str(input.session_id), slices=dropped)
    if used_fallback:
        # Fuzzy match would have dropped every slice — keep them all rather than ship
        # an empty MVP, and flag that traceability is uncertain for this plan.
        logger.warning("scope_creep_fuzzy_fallback", session_id=str(input.session_id),
                       slices=[s.name for s in plan.slices])
        await emit_event(
            db, input.session_id, "requirement.changed",
            data={"requirement_id": "*", "change_type": "scope_fuzzy_fallback",
                  "fuzzy_fallback": True, "slices_kept": len(plan.slices)},
            agent="slice_planner",
        )

    slice_ids: list[str] = []
    for i, s in enumerate(in_scope):
        row = Slice(
            session_id=input.session_id, name=s.name, description=s.description,
            slice_type="feature", status="planned", order_index=skeleton_order + i,
            design_version=0,
        )
        db.add(row)
        await db.flush()
        slice_ids.append(str(row.id))

    await emit_event(
        db, input.session_id, "agent.completed",
        data={
            "agent": "slice_planner", "loop": "design_build", "iteration": input.iteration,
            "duration_ms": result.latency_ms, "tokens_used": result.tokens_in + result.tokens_out,
            "slices_planned": len(slice_ids), "scope_creep_dropped": len(dropped),
        },
        agent="slice_planner",
    )
    logger.info("slice_plan_complete", session_id=str(input.session_id),
                planned=len(slice_ids), dropped=len(dropped))
    return SlicePlanResult(
        slice_ids=slice_ids, dropped=dropped,
        tokens_used=result.tokens_in + result.tokens_out, cost_usd=result.cost_usd,
    )
