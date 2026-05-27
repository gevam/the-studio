"""Benchmark harness: runs todo-cli through Studio vs. plain Claude Code."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class BenchmarkProject:
    name: str
    description: str
    requirements: list[str]
    complexity: str  # "trivial" | "simple" | "moderate"
    expected_modules: int
    expected_tests: int


BENCHMARK_PROJECTS = [
    BenchmarkProject(
        name="todo-cli",
        description="CLI todo app with persistence",
        requirements=[
            "Add/remove/list todos",
            "Persist to file",
            "Mark complete",
        ],
        complexity="trivial",
        expected_modules=3,
        expected_tests=10,
    ),
    BenchmarkProject(
        name="url-shortener",
        description="URL shortener HTTP API",
        requirements=[
            "Shorten URL",
            "Redirect",
            "Click stats",
            "Rate limiting",
        ],
        complexity="simple",
        expected_modules=5,
        expected_tests=20,
    ),
]


@dataclass
class BenchmarkResult:
    project: str
    approach: str  # "baseline" | "studio"
    duration_seconds: float
    total_cost_usd: float
    total_tokens: int
    test_coverage: float
    cyclomatic_complexity: float
    coupling_score: float
    duplication_pct: float
    tests_count: int
    tests_passing: int
    lint_issues: int
    friction_items_found: int
    friction_items_resolved: int
    design_revisions: int
    experience_score: Optional[float] = None
    error: Optional[str] = None


@dataclass
class Comparison:
    project: str
    baseline: BenchmarkResult
    studio: BenchmarkResult
    studio_wins: list[str] = field(default_factory=list)
    baseline_wins: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"=== Benchmark: {self.project} ===",
            f"Duration:   baseline={self.baseline.duration_seconds:.1f}s  "
            f"studio={self.studio.duration_seconds:.1f}s",
            f"Cost:       baseline=${self.baseline.total_cost_usd:.4f}  "
            f"studio=${self.studio.total_cost_usd:.4f}",
            f"Coverage:   baseline={self.baseline.test_coverage:.1f}%  "
            f"studio={self.studio.test_coverage:.1f}%",
            f"Complexity: baseline={self.baseline.cyclomatic_complexity:.1f}  "
            f"studio={self.studio.cyclomatic_complexity:.1f}",
            f"Design revisions (studio): {self.studio.design_revisions}",
            f"Friction resolved (studio): {self.studio.friction_items_resolved}",
            f"Studio wins: {', '.join(self.studio_wins) or 'none'}",
            f"Baseline wins: {', '.join(self.baseline_wins) or 'none'}",
        ]
        return "\n".join(lines)


async def run_baseline_benchmark(
    project: BenchmarkProject,
    output_dir: Path,
) -> BenchmarkResult:
    """Run project through plain Claude Code with a well-crafted prompt."""
    from studio.agents.build import ClaudeCodeAgent

    agent = ClaudeCodeAgent()
    project_path = output_dir / "baseline" / project.name
    project_path.mkdir(parents=True, exist_ok=True)

    prompt = (
        f"Build a {project.description}. Requirements:\n"
        + "\n".join(f"- {r}" for r in project.requirements)
        + "\n\nUse TDD: write tests first. Aim for >80% coverage. "
        "Clean code, well-structured, no magic numbers."
    )

    start = time.monotonic()
    try:
        output, tokens, cost = await agent.run(
            prompt, str(project_path), timeout_seconds=600
        )
        error = None
    except Exception as exc:
        output, tokens, cost = str(exc), 0, 0.0
        error = str(exc)

    duration = time.monotonic() - start

    # Analyze quality
    from studio.friction.detector import analyze_project
    metrics, friction = analyze_project(project_path)

    return BenchmarkResult(
        project=project.name,
        approach="baseline",
        duration_seconds=duration,
        total_cost_usd=cost,
        total_tokens=tokens,
        test_coverage=metrics.coverage_pct,
        cyclomatic_complexity=metrics.max_cyclomatic_complexity,
        coupling_score=metrics.coupling_score,
        duplication_pct=metrics.duplication_pct,
        tests_count=metrics.tests_count,
        tests_passing=metrics.tests_passing,
        lint_issues=0,
        friction_items_found=len(friction),
        friction_items_resolved=0,
        design_revisions=0,
        error=error,
    )


async def run_studio_benchmark(
    project: BenchmarkProject,
    output_dir: Path,
    db_url: str,
) -> BenchmarkResult:
    """Run project through The Studio."""
    from studio.ai.llm_client import LLMClient
    from studio.ai.prompt_loader import PromptLoader
    from studio.db.session import AsyncSessionLocal
    from studio.graph.builder import build_sprint1_graph

    project_path = output_dir / "studio" / project.name
    project_path.mkdir(parents=True, exist_ok=True)

    llm = LLMClient(provider="auto")
    prompt_loader = PromptLoader()

    # Create session in DB
    from studio.db.models import Requirement
    from studio.db.models import Session as SessionModel
    session_id = uuid.uuid4()

    async with AsyncSessionLocal() as db:
        session_row = SessionModel(
            id=session_id,
            name=project.name,
            status="created",
            config={
                "project_path": str(project_path),
                "stack": "python",
                "max_design_iterations": 3,
            },
        )
        db.add(session_row)
        await db.flush()  # persist session before FK-constrained requirements
        for req in project.requirements:
            db.add(Requirement(
                session_id=session_id,
                title=req,
                priority="high",
            ))
        await db.commit()

    compiled = build_sprint1_graph(
        db_factory=AsyncSessionLocal,
        llm=llm,
        prompt_loader=prompt_loader,
    )

    start = time.monotonic()
    try:
        from studio.db.projection import project_state
        async with AsyncSessionLocal() as db:
            initial_state = await project_state(session_id, db)

        final_state = await compiled.ainvoke(initial_state)
        error = final_state.get("error")
    except Exception as exc:
        final_state = {}
        error = str(exc)
        logger.error("studio_benchmark_error", project=project.name, error=str(exc))

    duration = time.monotonic() - start

    # Pull metrics from DB
    from sqlalchemy import select, func
    from studio.db.models import DesignFriction, DesignRevision
    async with AsyncSessionLocal() as db:
        rev_count = await db.scalar(
            select(func.count()).select_from(DesignRevision)
            .where(DesignRevision.session_id == session_id)
        )
        friction_found = await db.scalar(
            select(func.count()).select_from(DesignFriction)
            .where(DesignFriction.session_id == session_id)
        )
        friction_resolved = await db.scalar(
            select(func.count()).select_from(DesignFriction)
            .where(DesignFriction.session_id == session_id)
            .where(DesignFriction.status == "resolved")
        )

    from studio.friction.detector import analyze_project
    metrics, _ = analyze_project(project_path)

    return BenchmarkResult(
        project=project.name,
        approach="studio",
        duration_seconds=duration,
        total_cost_usd=final_state.get("cost_usd", 0.0),
        total_tokens=final_state.get("tokens_used", 0),
        test_coverage=metrics.coverage_pct,
        cyclomatic_complexity=metrics.max_cyclomatic_complexity,
        coupling_score=metrics.coupling_score,
        duplication_pct=metrics.duplication_pct,
        tests_count=metrics.tests_count,
        tests_passing=metrics.tests_passing,
        lint_issues=0,
        friction_items_found=friction_found or 0,
        friction_items_resolved=friction_resolved or 0,
        design_revisions=rev_count or 0,
        error=error,
    )


def compare(baseline: BenchmarkResult, studio: BenchmarkResult) -> Comparison:
    """Compare results. Studio must beat baseline on quality metrics."""
    studio_wins = []
    baseline_wins = []

    if studio.test_coverage > baseline.test_coverage:
        studio_wins.append("coverage")
    elif baseline.test_coverage > studio.test_coverage:
        baseline_wins.append("coverage")

    if studio.cyclomatic_complexity < baseline.cyclomatic_complexity:
        studio_wins.append("complexity")
    elif baseline.cyclomatic_complexity < studio.cyclomatic_complexity:
        baseline_wins.append("complexity")

    if studio.coupling_score < baseline.coupling_score:
        studio_wins.append("coupling")
    elif baseline.coupling_score < studio.coupling_score:
        baseline_wins.append("coupling")

    if studio.duplication_pct < baseline.duplication_pct:
        studio_wins.append("duplication")
    elif baseline.duplication_pct < studio.duplication_pct:
        baseline_wins.append("duplication")

    # Studio gets credit for friction loop
    if studio.design_revisions > 0:
        studio_wins.append("design_feedback_loop")

    return Comparison(
        project=baseline.project,
        baseline=baseline,
        studio=studio,
        studio_wins=studio_wins,
        baseline_wins=baseline_wins,
    )
