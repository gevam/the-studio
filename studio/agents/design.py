"""Design Agent — creates and revises the Living Design artifact."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import structlog

from studio.ai.llm_client import LLMClient
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

    # 0. Agent lifecycle start (§7.2)
    await emit_event(
        db,
        input.session_id,
        "agent.started",
        data={"agent": "design_agent", "loop": "design_build", "iteration": input.iteration},
        agent="design_agent",
    )

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

    # 3. Structured completion → schema-validated LivingDesign (no prompt-and-parse).
    result = await llm.complete_structured(
        agent="design_agent",
        system_prompt=system_tpl.content,
        user_content=user_content,
        schema=LivingDesign,
        max_tokens=8192,
        temperature=0.0,
        prompt_hash=prompt_hash,
        session_id=input.session_id,
        db=db,
    )
    design: LivingDesign = result.parsed
    tokens_used = result.tokens_in + result.tokens_out
    cost_usd = result.cost_usd

    # 4. Set version
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
