"""Design Agent — creates and revises the Living Design artifact."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

import structlog

from studio.ai.llm_client import LLMClient, LLMResponse
from studio.ai.prompt_loader import PromptLoader
from studio.design.revision import create_revision_record, generate_digest
from studio.design.schema import LivingDesign

logger = structlog.get_logger(__name__)


@dataclass
class DesignAgentInput:
    session_id: uuid.UUID
    design_digest: str
    trigger: str  # "initial" | "friction" | "skeleton_fail"
    requirements: list[str]
    friction_items: list[dict] = field(default_factory=list)  # serialized FrictionReport list
    iteration: int = 0
    budget_remaining: dict = field(default_factory=dict)  # {tokens_remaining, cost_remaining_usd}
    project_name: str = "untitled"
    project_path: str = "/project"
    prev_version: int = 0


@dataclass
class DesignAgentOutput:
    design: LivingDesign
    digest: str
    revision_reason: str
    sections_changed: list[str]
    tokens_used: int
    cost_usd: float


async def run_design_agent(
    input: DesignAgentInput,
    db,  # AsyncSession
    llm: LLMClient,
    prompt_loader: PromptLoader,
) -> DesignAgentOutput:
    """Run the design agent: create initial design or revise based on friction."""

    from studio.db.models import DesignFriction, DesignRevision
    from studio.events.emitter import emit_event
    from studio.observability.metrics import design_revisions_total

    # Design agent always uses the Anthropic SDK so that assistant prefill
    # works correctly and there is no prose preamble before the JSON.
    design_llm = LLMClient(provider="anthropic")

    # 1. Load system prompt
    system_tpl = prompt_loader.load("design_agent", "system")

    # 2. Choose task prompt
    if input.trigger == "initial":
        task_tpl = prompt_loader.load("design_agent", "initial_design")
        requirements_str = "\n".join(f"- {r}" for r in input.requirements)
        user_content = prompt_loader.render(
            task_tpl.content,
            requirements=requirements_str,
            project_name=input.project_name,
            iteration=str(input.iteration),
        )
        revision_reason = "Initial design"
    else:
        task_tpl = prompt_loader.load("design_agent", "friction_revision")
        requirements_str = "\n".join(f"- {r}" for r in input.requirements)
        friction_str = json.dumps(input.friction_items, indent=2)
        user_content = prompt_loader.render(
            task_tpl.content,
            requirements=requirements_str,
            project_name=input.project_name,
            iteration=str(input.iteration),
            design_digest=input.design_digest,
            friction_items=friction_str,
            trigger=input.trigger,
        )
        revision_reason = f"Design revised due to {input.trigger} (iteration {input.iteration})"

    prompt_hash = task_tpl.hash

    # 3. Call LLM
    response: LLMResponse = await design_llm.complete(
        agent="design_agent",
        system_prompt=system_tpl.content,
        user_content=user_content,
        model="claude-sonnet-4-6",
        max_tokens=8192,
        temperature=0.0,
        prompt_hash=prompt_hash,
        session_id=input.session_id,
        db=db,
        prefill="{",
    )

    # 4. Parse JSON response → LivingDesign
    design = _parse_design(response.content)

    # Track accumulated usage across initial call and optional retry
    tokens_used = response.tokens_in + response.tokens_out
    cost_usd = response.cost_usd

    # 5. If parse fails, retry once
    if design is None:
        retry_content = (
            "Your response was not valid JSON. "
            "Return ONLY raw JSON matching the LivingDesign schema. "
            "No markdown fences, no explanation — raw JSON only.\n\n"
            f"Previous response (first 500 chars):\n{response.content[:500]}"
        )
        retry_response: LLMResponse = await design_llm.complete(
            agent="design_agent",
            system_prompt=system_tpl.content,
            user_content=retry_content,
            model="claude-sonnet-4-6",
            max_tokens=8192,
            temperature=0.0,
            prompt_hash=prompt_hash,
            session_id=input.session_id,
            db=db,
            prefill="{",
        )
        tokens_used += retry_response.tokens_in + retry_response.tokens_out
        cost_usd += retry_response.cost_usd
        design = _parse_design(retry_response.content)

        if design is None:
            logger.error("design_agent_parse_failed", content_preview=response.content[:200])
            # Fall back to empty design
            design = LivingDesign(
                version=input.prev_version + 1,
                open_questions=["Design parsing failed — LLM returned invalid JSON"],
                known_friction=["Could not parse LLM output"],
            )

    # 6. Set version
    new_version = input.prev_version + 1
    design = design.model_copy(update={"version": new_version})
    design = design.compute_and_set_hash()

    # 7. Determine sections changed
    sections_changed = [s.id for s in design.sections]

    # 8. Write DesignRevision row to DB
    revision_record = create_revision_record(
        session_id=input.session_id,
        new_version=new_version,
        design=design,
        reason=revision_reason,
        caused_by_agent="design_agent",
    )
    db_revision = DesignRevision(**revision_record)
    db.add(db_revision)
    await db.flush()

    # 9. If triggered by friction: update DesignFriction rows status='resolved'
    if input.trigger in ("friction", "skeleton_fail") and input.friction_items:
        from sqlalchemy import select, update as sa_update

        friction_ids = [
            item.get("id") for item in input.friction_items
            if item.get("id")
        ]
        if friction_ids:
            friction_uuids = []
            for fid in friction_ids:
                try:
                    friction_uuids.append(uuid.UUID(str(fid)))
                except (ValueError, TypeError):
                    pass

            if friction_uuids:
                # Fetch and update each friction row
                from sqlalchemy import update as sa_update_stmt

                await db.execute(
                    sa_update_stmt(DesignFriction)
                    .where(DesignFriction.id.in_(friction_uuids))
                    .where(DesignFriction.session_id == input.session_id)
                    .values(
                        status="resolved",
                        resolved_by_revision_id=db_revision.id,
                        resolved_at=datetime.now(UTC),
                    )
                )

    # 10. Emit design.revised event
    await emit_event(
        db,
        input.session_id,
        "design.revised",
        data={
            "version": new_version,
            "reason": revision_reason,
            "caused_by": input.trigger,
            "sections_changed": sections_changed,
        },
        agent="design_agent",
    )

    # 11. Increment metric
    design_revisions_total.labels(caused_by=input.trigger).inc()

    # 12. Store design JSON to project file
    designs_dir = Path(input.project_path) / "designs"
    designs_dir.mkdir(parents=True, exist_ok=True)
    design_file = designs_dir / f"v{new_version}.json"
    design_file.write_text(design.model_dump_json(indent=2), encoding="utf-8")
    logger.info(
        "design_stored",
        path=str(design_file),
        version=new_version,
    )

    digest = generate_digest(design)

    return DesignAgentOutput(
        design=design,
        digest=digest,
        revision_reason=revision_reason,
        sections_changed=sections_changed,
        tokens_used=tokens_used,
        cost_usd=cost_usd,
    )


def _parse_design(content: str) -> Optional[LivingDesign]:
    """Attempt to parse LLM output as LivingDesign. Returns None on failure.

    Handles:
    1. Direct LivingDesign JSON
    2. Friction revision wrapper: {"revised_design": {...}, ...}
    3. Markdown-fenced JSON (```json ... ```)
    4. JSON embedded after prose preamble (scan for first '{')
    """
    text = content.strip()

    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end]).strip()

    # Try every '{' position as a potential JSON start (handles prose preamble
    # and prefill-prepended '{' that doesn't belong to the actual JSON object)
    idx = 0
    while True:
        brace_idx = text.find("{", idx)
        if brace_idx == -1:
            break
        candidate = text[brace_idx:]
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            idx = brace_idx + 1
            continue
        # JSON parsed — this is our candidate object. Unwrap and validate.
        if isinstance(data, dict) and "revised_design" in data:
            data = data["revised_design"]
        try:
            return LivingDesign(**data)
        except Exception as exc:
            logger.warning("design_parse_schema_error", error=str(exc)[:200])
            return None

    logger.warning("design_parse_failed", error="no valid JSON object found in response")
    return None
