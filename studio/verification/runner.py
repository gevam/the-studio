"""Verification runner: orchestrates all checks and persists results."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional

import structlog

from studio.verification.checks import (
    CheckResult,
    run_build_check,
    run_coverage_check,
    run_lint_check,
    run_pii_check,
    run_secrets_check,
    run_tests_check,
    run_typecheck,
)
from studio.verification.sandbox import SandboxRunner

logger = structlog.get_logger(__name__)


@dataclass
class VerificationResult:
    passed: bool
    build_passed: bool
    test_passed: bool
    lint_passed: bool
    coverage_pct: Optional[float]
    tests_run: int
    tests_passed: int
    tests_failed: int
    build_output: str
    test_output: str
    lint_output: str
    duration_ms: int
    check_results: list[CheckResult]

    @property
    def failure_summary(self) -> str:
        failed = [c.name for c in self.check_results if not c.passed]
        return f"Failed checks: {', '.join(failed)}" if failed else "All checks passed"


async def run_verification(
    session_id: uuid.UUID,
    slice_id: Optional[uuid.UUID],
    project_path: str,
    db,  # AsyncSession
    *,
    sandbox: Optional[SandboxRunner] = None,
    workdir: str = "/project",
) -> VerificationResult:
    """Run all deterministic checks and persist to DB."""

    from studio.db.models import VerificationResult as VerificationResultModel
    from studio.events.emitter import emit_event
    from studio.observability.metrics import verification_failures_total

    if sandbox is None:
        sandbox = SandboxRunner()

    start = time.monotonic()

    # Check sandbox is alive
    if not await sandbox.is_alive():
        logger.warning("sandbox_not_running", container=sandbox._container)
        result = _make_failed_result("Sandbox container not running", start)
        await _persist_result(db, session_id, slice_id, result)
        await emit_event(
            db,
            session_id,
            "verification.result",
            data={"passed": False, "reason": "sandbox_unavailable"},
            agent="verification",
        )
        return result

    # Run checks sequentially
    check_results: list[CheckResult] = []

    build_result = await run_build_check(sandbox, workdir)
    check_results.append(build_result)

    test_result = await run_tests_check(sandbox, workdir)
    check_results.append(test_result)

    coverage_result = await run_coverage_check(sandbox, workdir)
    check_results.append(coverage_result)

    lint_result = await run_lint_check(sandbox, workdir)
    check_results.append(lint_result)

    secrets_result = await run_secrets_check(sandbox, workdir)
    check_results.append(secrets_result)

    pii_result = await run_pii_check(sandbox, workdir)
    check_results.append(pii_result)

    type_result = await run_typecheck(sandbox, workdir)
    check_results.append(type_result)

    duration_ms = int((time.monotonic() - start) * 1000)

    # Aggregate
    all_passed = all(c.passed for c in check_results)
    test_details = test_result.details

    result = VerificationResult(
        passed=all_passed,
        build_passed=build_result.passed,
        test_passed=test_result.passed,
        lint_passed=lint_result.passed,
        coverage_pct=coverage_result.details.get("coverage_pct"),
        tests_run=test_details.get("tests_run", 0),
        tests_passed=test_details.get("tests_passed", 0),
        tests_failed=test_details.get("tests_failed", 0),
        build_output=build_result.output,
        test_output=test_result.output,
        lint_output=lint_result.output,
        duration_ms=duration_ms,
        check_results=check_results,
    )

    # Persist to DB
    await _persist_result(db, session_id, slice_id, result)

    # Emit event
    await emit_event(
        db,
        session_id,
        "verification.result",
        data={
            "passed": result.passed,
            "build_passed": result.build_passed,
            "test_passed": result.test_passed,
            "lint_passed": result.lint_passed,
            "coverage_pct": result.coverage_pct,
            "tests_run": result.tests_run,
            "duration_ms": duration_ms,
        },
        agent="verification",
    )

    # Emit metrics for failures
    for check in check_results:
        if not check.passed:
            verification_failures_total.labels(check=check.name).inc()

    logger.info(
        "verification_complete",
        session_id=str(session_id),
        passed=result.passed,
        duration_ms=duration_ms,
        failures=[c.name for c in check_results if not c.passed],
    )

    return result


async def _persist_result(
    db,
    session_id: uuid.UUID,
    slice_id: Optional[uuid.UUID],
    result: VerificationResult,
) -> None:
    from studio.db.models import VerificationResult as VRModel

    row = VRModel(
        session_id=session_id,
        slice_id=slice_id,
        verification_type="all",
        passed=result.passed,
        build_passed=result.build_passed,
        test_passed=result.test_passed,
        lint_passed=result.lint_passed,
        build_output=result.build_output[:4000],
        test_output=result.test_output[:4000],
        lint_output=result.lint_output[:4000],
        test_coverage=result.coverage_pct,
        tests_run=result.tests_run,
        tests_passed=result.tests_passed,
        tests_failed=result.tests_failed,
        duration_ms=result.duration_ms,
    )
    db.add(row)
    await db.flush()


def _make_failed_result(reason: str, start: float) -> VerificationResult:
    duration_ms = int((time.monotonic() - start) * 1000)
    return VerificationResult(
        passed=False,
        build_passed=False,
        test_passed=False,
        lint_passed=False,
        coverage_pct=None,
        tests_run=0,
        tests_passed=0,
        tests_failed=0,
        build_output=reason,
        test_output="",
        lint_output="",
        duration_ms=duration_ms,
        check_results=[],
    )
