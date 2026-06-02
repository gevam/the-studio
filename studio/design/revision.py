"""Design versioning, hashing, and diffing."""

import difflib
import hashlib
import uuid
from typing import Optional

from studio.design.schema import LivingDesign


def compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def generate_digest(design: LivingDesign) -> str:
    """Generate ≤500-token summary of current design state."""
    modules = ", ".join(m.name for m in design.modules) or "none"
    entities = ", ".join(e.name for e in design.data_model) or "none"
    flows = ", ".join(f.name for f in design.ux_flows) or "none"
    metric = design.experience_metric.get("name", "TBD")

    return (
        f"Design v{design.version} | "
        f"Modules: {modules} | "
        f"Data: {entities} | "
        f"Flows: {flows} | "
        f"Metric: {metric} | "
        f"ADRs: {len(design.architecture_decisions)} | "
        f"Open friction: {len(design.known_friction)} | "
        f"Open questions: {len(design.open_questions)}"
    )


def create_revision_record(
    session_id: uuid.UUID,
    new_version: int,
    design: LivingDesign,
    reason: str,
    caused_by_agent: str,
    caused_by_friction_id: Optional[uuid.UUID] = None,
) -> dict:
    """Return a dict ready to insert into design_revisions table."""
    content_str = design.model_dump_json()
    content_hash = compute_hash(content_str)
    digest = generate_digest(design)

    section_index = [
        {"id": s.id, "title": s.title, "hash": s.content_hash}
        for s in design.sections
    ]

    return {
        "session_id": session_id,
        "version": new_version,
        "content_hash": content_hash,
        "content_key": f"designs/{session_id}/v{new_version}.json",
        "digest": digest,
        "section_index": section_index,
        "reason": reason,
        "caused_by_agent": caused_by_agent,
        "caused_by_friction_id": caused_by_friction_id,
    }


def diff_designs(old: LivingDesign, new: LivingDesign) -> dict:
    """Compute structured diff between two design versions."""
    old_json = old.model_dump_json(indent=2)
    new_json = new.model_dump_json(indent=2)

    unified = list(difflib.unified_diff(
        old_json.splitlines(),
        new_json.splitlines(),
        fromfile=f"v{old.version}",
        tofile=f"v{new.version}",
        lineterm="",
    ))

    old_sections = {s.id: s for s in old.sections}
    new_sections = {s.id: s for s in new.sections}

    changed = [
        sid for sid in new_sections
        if sid in old_sections and old_sections[sid].content_hash != new_sections[sid].content_hash
    ]
    added = [sid for sid in new_sections if sid not in old_sections]
    removed = [sid for sid in old_sections if sid not in new_sections]

    old_adr_ids = {d.id for d in old.architecture_decisions}
    decisions_added = [d.id for d in new.architecture_decisions if d.id not in old_adr_ids]

    return {
        "from_version": old.version,
        "to_version": new.version,
        "unified_diff": "\n".join(unified),
        "sections_changed": changed,
        "sections_added": added,
        "sections_removed": removed,
        "decisions_added": decisions_added,
    }
