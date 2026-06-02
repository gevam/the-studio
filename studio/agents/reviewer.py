"""Reviewer Agent (§4.4) — rubric-anchored review on a different model family.

Runs only after the §4.6 deterministic checks pass (enforced by graph wiring) and
uses native structured output. Routes via the provider registry to a different model
from the other agents (openai/gpt-4o by default; claude-opus fallback offline).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import structlog
from pydantic import BaseModel, Field

from studio.ai.llm_client import LLMClient
from studio.ai.prompt_loader import PromptLoader

logger = structlog.get_logger(__name__)

# overall_score >= this passes the review (§4.4).
PASS_THRESHOLD = 7.0


class RubricScore(BaseModel):
    criterion: str
    score: float = Field(ge=0, le=10)
    finding: str = ""
    evidence: str = ""
    severity: str = "info"  # "info" | "warning" | "error"


class ReviewerOutput(BaseModel):
    """Structured reviewer verdict (§4.4)."""

    rubric_scores: list[RubricScore] = []
    overall_score: float = Field(ge=0, le=10)
    passed: bool = True
    issues: list[str] = []


@dataclass
class ReviewerInput:
    session_id: uuid.UUID
    design_digest: str
    design_version: int
    project_name: str
    slice_id: uuid.UUID | None = None
    slice_name: str = ""
    slice_description: str = ""
    code_artifacts: list[str] = field(default_factory=list)
    coverage_pct: float = 0.0
    tests_run: int = 0
    iteration: int = 0


@dataclass
class ReviewerResult:
    output: ReviewerOutput
    model_used: str
    tokens_used: int
    cost_usd: float


async def run_reviewer(
    input: ReviewerInput,
    db,  # AsyncSession
    llm: LLMClient,
    prompt_loader: PromptLoader,
) -> ReviewerResult:
    """Run the Reviewer, persist a ReviewerRecord, emit reviewer.evaluated."""
    from studio.db.models import ReviewerRecord
    from studio.events.emitter import emit_event

    await emit_event(
        db, input.session_id, "agent.started",
        data={"agent": "reviewer", "loop": "build_verify", "iteration": input.iteration},
        agent="reviewer",
    )

    system_tpl = prompt_loader.load("reviewer", "system")
    review_tpl = prompt_loader.load("reviewer", "review")
    user_content = prompt_loader.render(
        review_tpl.content,
        project_name=input.project_name,
        design_digest=input.design_digest,
        slice_name=input.slice_name,
        slice_description=input.slice_description,
        coverage_pct=f"{input.coverage_pct:.0f}",
        tests_run=str(input.tests_run),
        code_artifacts="\n".join(f"- {a}" for a in input.code_artifacts) or "none",
    )

    result = await llm.complete_structured(
        agent="reviewer",
        system_prompt=system_tpl.content,
        user_content=user_content,
        schema=ReviewerOutput,
        max_tokens=4096,
        temperature=0.0,
        prompt_hash=review_tpl.hash,
        session_id=input.session_id,
        db=db,
    )
    output: ReviewerOutput = result.parsed
    # Trust the rubric's overall_score against the threshold for the pass decision.
    passed = output.overall_score >= PASS_THRESHOLD
    output.passed = passed
    tokens_used = result.tokens_in + result.tokens_out

    db.add(ReviewerRecord(
        session_id=input.session_id,
        slice_id=input.slice_id,
        design_version=input.design_version,
        rubric_scores=[s.model_dump() for s in output.rubric_scores],
        overall_score=output.overall_score,
        passed=passed,
        issues=output.issues,
        model_used=result.model,
        prompt_hash=review_tpl.hash,
    ))
    await db.flush()

    await emit_event(
        db, input.session_id, "reviewer.evaluated",
        data={
            "overall_score": output.overall_score, "passed": passed,
            "issues_count": len(output.issues), "model_used": result.model,
        },
        agent="reviewer",
    )
    await emit_event(
        db, input.session_id, "agent.completed",
        data={
            "agent": "reviewer", "loop": "build_verify", "iteration": input.iteration,
            "duration_ms": result.latency_ms, "tokens_used": tokens_used,
        },
        agent="reviewer",
    )
    logger.info(
        "reviewer_complete", session_id=str(input.session_id),
        overall_score=output.overall_score, passed=passed, model=result.model,
    )
    return ReviewerResult(
        output=output, model_used=result.model, tokens_used=tokens_used, cost_usd=result.cost_usd,
    )
