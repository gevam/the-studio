#!/usr/bin/env python3
"""Sprint 2 benchmark: run url-shortener through the full Studio graph + baseline."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402

from studio.benchmark.harness import (  # noqa: E402
    BENCHMARK_PROJECTS,
    compare,
    run_baseline_benchmark,
    run_studio_benchmark,
)
from studio.config import settings  # noqa: E402
from studio.observability.logging import configure_logging  # noqa: E402

LOOP_PROOF_EVENTS = (
    "agent.started", "design.revised", "design_friction.reported", "skeleton.validated",
    "human.checkpoint", "human.decision", "slice.started", "slice.built", "slice.verified",
    "verification.result", "reviewer.evaluated", "session.completed",
)


async def _latest_session_proof() -> str:
    """Return an event_log excerpt for the most recent session (DoD proof)."""
    from studio.db.models import EventLog, Session
    from studio.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        sid = await db.scalar(select(Session.id).order_by(Session.created_at.desc()).limit(1))
        rows = (await db.execute(
            select(EventLog.seq, EventLog.event_type)
            .where(EventLog.session_id == sid).order_by(EventLog.seq)
        )).all()
    lines = [f"session_id = {sid}", "", "seq | event_type", "--- | ----------"]
    lines += [f"{seq:>3} | {etype}" for seq, etype in rows]
    return "\n".join(lines)


async def main() -> None:
    configure_logging("info")
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    project = next(p for p in BENCHMARK_PROJECTS if p.name == "url-shortener")

    print(f"\n{'='*60}\nSprint 2 Benchmark: {project.name}\n{'='*60}\n")

    print("[1/2] Running baseline (plain Claude Code)...")
    baseline = await run_baseline_benchmark(project, output_dir)
    print(f"      done: ${baseline.total_cost_usd:.4f}, {baseline.duration_seconds:.1f}s")

    print("[2/2] Running Studio (full Sprint 2 graph)...")
    studio = await run_studio_benchmark(project, output_dir, db_url=settings.database_url, sprint=2)
    print(f"      done: ${studio.total_cost_usd:.4f}, {studio.duration_seconds:.1f}s")
    if studio.error:
        print(f"      ERROR: {studio.error}")

    comparison = compare(baseline, studio)
    print("\n" + comparison.summary())

    proof = await _latest_session_proof()
    results_path = Path(__file__).parent / "sprint-2-results.md"
    results_path.write_text(_format_results(comparison, proof))
    print(f"\nResults written to {results_path}")


def _format_results(c, proof: str) -> str:
    b, s = c.baseline, c.studio
    return f"""# Sprint 2 Benchmark Results

**Project:** {c.project}
**Date:** {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}

## Summary

| Metric | Baseline (plain Claude) | Studio |
|--------|------------------------|--------|
| Duration | {b.duration_seconds:.1f}s | {s.duration_seconds:.1f}s |
| Cost | ${b.total_cost_usd:.4f} | ${s.total_cost_usd:.4f} |
| Test coverage | {b.test_coverage:.1f}% | {s.test_coverage:.1f}% |
| Cyclomatic complexity | {b.cyclomatic_complexity:.1f} | {s.cyclomatic_complexity:.1f} |
| Duplication % | {b.duplication_pct:.1f}% | {s.duplication_pct:.1f}% |
| Friction items found | {b.friction_items_found} | {s.friction_items_found} |
| Friction items resolved | {b.friction_items_resolved} | {s.friction_items_resolved} |
| Design revisions | {b.design_revisions} | {s.design_revisions} |

## Studio wins
{chr(10).join(f"- {w}" for w in c.studio_wins) or "none"}

## Errors
Studio: {s.error or "none"}

## Event log (DoD proof — three loops + both human gates)

```
{proof}
```
"""


if __name__ == "__main__":
    asyncio.run(main())
