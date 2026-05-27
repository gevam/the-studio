#!/usr/bin/env python3
"""Sprint 1 benchmark: run todo-cli through Studio and baseline, compare results."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from studio.benchmark.harness import (
    BENCHMARK_PROJECTS,
    compare,
    run_baseline_benchmark,
    run_studio_benchmark,
)
from studio.config import settings
from studio.observability.logging import configure_logging


async def main() -> None:
    configure_logging("info")

    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)

    # Sprint 1: only todo-cli (trivial complexity)
    project = next(p for p in BENCHMARK_PROJECTS if p.name == "todo-cli")

    print(f"\n{'='*60}")
    print(f"Sprint 1 Benchmark: {project.name}")
    print(f"{'='*60}\n")

    print("[1/2] Running baseline (plain Claude Code)...")
    baseline = await run_baseline_benchmark(project, output_dir)
    print(f"      done: ${baseline.total_cost_usd:.4f}, {baseline.duration_seconds:.1f}s")
    if baseline.error:
        print(f"      ERROR: {baseline.error}")

    print("[2/2] Running Studio...")
    studio = await run_studio_benchmark(
        project, output_dir, db_url=settings.database_url
    )
    print(f"      done: ${studio.total_cost_usd:.4f}, {studio.duration_seconds:.1f}s")
    if studio.error:
        print(f"      ERROR: {studio.error}")

    comparison = compare(baseline, studio)
    print("\n" + comparison.summary())

    # Write results markdown
    results_path = Path(__file__).parent / "sprint-1-results.md"
    results_path.write_text(_format_results(comparison))
    print(f"\nResults written to {results_path}")


def _format_results(c) -> str:
    b = c.baseline
    s = c.studio
    return f"""# Sprint 1 Benchmark Results

**Project:** {c.project}
**Date:** {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}

## Summary

| Metric | Baseline (plain Claude) | Studio |
|--------|------------------------|--------|
| Duration | {b.duration_seconds:.1f}s | {s.duration_seconds:.1f}s |
| Cost | ${b.total_cost_usd:.4f} | ${s.total_cost_usd:.4f} |
| Test coverage | {b.test_coverage:.1f}% | {s.test_coverage:.1f}% |
| Cyclomatic complexity | {b.cyclomatic_complexity:.1f} | {s.cyclomatic_complexity:.1f} |
| Coupling score | {b.coupling_score:.1f} | {s.coupling_score:.1f} |
| Duplication % | {b.duplication_pct:.1f}% | {s.duplication_pct:.1f}% |
| Friction items found | {b.friction_items_found} | {s.friction_items_found} |
| Friction items resolved | {b.friction_items_resolved} | {s.friction_items_resolved} |
| Design revisions | {b.design_revisions} | {s.design_revisions} |

## Studio wins
{chr(10).join(f"- {w}" for w in c.studio_wins) or "none"}

## Baseline wins
{chr(10).join(f"- {w}" for w in c.baseline_wins) or "none"}

## Errors

Baseline: {b.error or "none"}
Studio: {s.error or "none"}
"""


if __name__ == "__main__":
    asyncio.run(main())
