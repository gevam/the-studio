"""UX/Customer Agent (§4.2) — the user's voice over design and built slices."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import structlog
from pydantic import BaseModel, Field

from studio.ai.llm_client import LLMClient
from studio.ai.prompt_loader import PromptLoader

logger = structlog.get_logger(__name__)


class UXIssue(BaseModel):
    severity: str  # "low" | "medium" | "high" | "critical"
    description: str
    suggestion: str = ""
    category: str = "flow"  # flow | consistency | accessibility | error_state | i18n


class ExperienceMetric(BaseModel):
    name: str
    target: str = ""
    rationale: str = ""


class UXReview(BaseModel):
    """Structured output of the UX agent (§4.2)."""

    experience_score: float = Field(ge=0, le=10)
    issues: list[UXIssue] = []
    journey_complete: bool = True
    simplicity_assessment: str = ""
    needs_design_revision: bool = False
    revision_suggestions: list[str] = []
    experience_metric: ExperienceMetric | None = None


@dataclass
class UXAgentInput:
    session_id: uuid.UUID
    design_digest: str
    context: str  # "design_review" | "slice_review"
    project_name: str
    requirements: list[str] = field(default_factory=list)
    prior_issues: list[dict] = field(default_factory=list)
    experience_metric: dict | None = None
    slice_name: str = ""
    slice_description: str = ""
    slice_artifacts: list[str] = field(default_factory=list)
    iteration: int = 0


@dataclass
class UXAgentOutput:
    review: UXReview
    tokens_used: int
    cost_usd: float


async def run_ux_agent(
    input: UXAgentInput,
    db,  # AsyncSession
    llm: LLMClient,
    prompt_loader: PromptLoader,
) -> UXAgentOutput:
    """Run the UX agent in design-review or slice-review mode (structured output)."""
    from studio.events.emitter import emit_event

    loop = "design_ux" if input.context == "design_review" else "build_verify"
    await emit_event(
        db, input.session_id, "agent.started",
        data={"agent": "ux_agent", "loop": loop, "iteration": input.iteration},
        agent="ux_agent",
    )

    system_tpl = prompt_loader.load("ux_agent", "system")
    prior = "\n".join(
        f"- [{i.get('severity')}] {i.get('description')}" for i in input.prior_issues
    ) or "none"

    if input.context == "design_review":
        task_tpl = prompt_loader.load("ux_agent", "design_review")
        user_content = prompt_loader.render(
            task_tpl.content,
            project_name=input.project_name,
            design_digest=input.design_digest,
            requirements="\n".join(f"- {r}" for r in input.requirements) or "none",
            prior_issues=prior,
        )
    else:
        task_tpl = prompt_loader.load("ux_agent", "slice_review")
        metric = input.experience_metric or {}
        user_content = prompt_loader.render(
            task_tpl.content,
            project_name=input.project_name,
            design_digest=input.design_digest,
            experience_metric=f"{metric.get('name', 'TBD')}: {metric.get('target', '')}",
            slice_name=input.slice_name,
            slice_description=input.slice_description,
            slice_artifacts="\n".join(f"- {a}" for a in input.slice_artifacts) or "none",
            prior_issues=prior,
        )

    result = await llm.complete_structured(
        agent="ux_agent",
        system_prompt=system_tpl.content,
        user_content=user_content,
        schema=UXReview,
        max_tokens=4096,
        temperature=0.0,
        prompt_hash=task_tpl.hash,
        session_id=input.session_id,
        db=db,
    )
    review: UXReview = result.parsed
    tokens_used = result.tokens_in + result.tokens_out

    await emit_event(
        db, input.session_id, "agent.completed",
        data={
            "agent": "ux_agent", "loop": loop, "iteration": input.iteration,
            "duration_ms": result.latency_ms, "tokens_used": tokens_used,
            "experience_score": review.experience_score,
            "issues": len(review.issues),
            "needs_design_revision": review.needs_design_revision,
        },
        agent="ux_agent",
    )
    logger.info(
        "ux_agent_complete", session_id=str(input.session_id), context=input.context,
        score=review.experience_score, issues=len(review.issues),
        needs_revision=review.needs_design_revision,
    )
    return UXAgentOutput(review=review, tokens_used=tokens_used, cost_usd=result.cost_usd)
