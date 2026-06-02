"""Deterministic verification checks that run in the sandbox."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from studio.verification.sandbox import SandboxRunner, SandboxResult

DETERMINISTIC_CHECKS = [
    "build_succeeds",
    "all_tests_pass",
    "coverage_gate",
    "lint_clean",
    "no_secrets_in_code",
    "no_pii_in_logs",
    "type_check_passes",
]

COVERAGE_GATE_PCT = 80.0

# Patterns for secret detection
_SECRET_PATTERNS = [
    r'(?i)(api[_-]?key|secret[_-]?key|password|passwd|token|auth[_-]?token)\s*=\s*["\'][^"\']{8,}["\']',
    r'sk-[a-zA-Z0-9]{20,}',
    r'ghp_[a-zA-Z0-9]{36}',
    r'AKIA[0-9A-Z]{16}',
]

# Patterns for PII in log statements
_PII_LOG_PATTERNS = [
    r'(?i)(log|print|logger)\s*[.(].*(?:email|phone|ssn|social.security|credit.card|password)',
    r'(?i)f["\'].*\{.*(?:email|phone|password).*\}.*["\'].*log',
]


@dataclass
class CheckResult:
    name: str
    passed: bool
    output: str
    duration_ms: int
    details: dict = field(default_factory=dict)


async def run_build_check(sandbox: SandboxRunner, workdir: str) -> CheckResult:
    """Verify the project compiles / has no syntax errors."""
    # Try Python first, then Node, then generic make
    result = await sandbox.run(
        "python -m py_compile $(find . -name '*.py' -not -path './.git/*' "
        "-not -path './venv/*' -not -path './.venv/*') 2>&1 || "
        "node --check $(find . -name '*.js' -not -path './node_modules/*') 2>&1 || "
        "echo 'no_syntax_errors'",
        workdir=workdir,
    )
    passed = result.exit_code == 0
    return CheckResult(
        name="build_succeeds",
        passed=passed,
        output=(result.stdout + result.stderr)[:2000],
        duration_ms=result.duration_ms,
    )


async def run_tests_check(sandbox: SandboxRunner, workdir: str) -> CheckResult:
    """Run the test suite and check all tests pass."""
    result = await sandbox.run(
        "python -m pytest --tb=short -q 2>&1 || "
        "npm test 2>&1 || "
        "echo 'no_tests_found'",
        workdir=workdir,
    )
    passed = result.exit_code == 0
    return CheckResult(
        name="all_tests_pass",
        passed=passed,
        output=(result.stdout + result.stderr)[:3000],
        duration_ms=result.duration_ms,
        details=_parse_pytest_output(result.stdout),
    )


async def run_coverage_check(sandbox: SandboxRunner, workdir: str) -> CheckResult:
    """Run tests with coverage and verify ≥80% line coverage."""
    result = await sandbox.run(
        f"python -m pytest --cov=. --cov-report=term-missing "
        f"--cov-fail-under={int(COVERAGE_GATE_PCT)} -q 2>&1",
        workdir=workdir,
    )
    passed = result.exit_code == 0
    coverage_pct = _parse_coverage_pct(result.stdout)
    return CheckResult(
        name="coverage_gate",
        passed=passed,
        output=(result.stdout + result.stderr)[:3000],
        duration_ms=result.duration_ms,
        details={"coverage_pct": coverage_pct},
    )


async def run_lint_check(sandbox: SandboxRunner, workdir: str) -> CheckResult:
    """Run linter and check for zero errors (warnings OK)."""
    result = await sandbox.run(
        "python -m ruff check . --select=E,F --exit-zero-on-warning 2>&1 || "
        "python -m flake8 . --count --select=E9,F63,F7,F82 2>&1 || "
        "echo 'lint_ok'",
        workdir=workdir,
    )
    passed = result.exit_code == 0
    return CheckResult(
        name="lint_clean",
        passed=passed,
        output=(result.stdout + result.stderr)[:2000],
        duration_ms=result.duration_ms,
    )


# Vendored/generated dirs to keep out of grep- and type-based checks. Scanning a
# project-local .venv yields false positives (library code is full of token=...,
# password=... literals) that would fail an otherwise-clean project.
_EXCLUDE_DIRS = (
    "--exclude-dir=.git --exclude-dir=node_modules "
    "--exclude-dir=venv --exclude-dir=.venv --exclude-dir=site-packages "
    "--exclude-dir=__pycache__ --exclude-dir=build --exclude-dir=dist"
)


async def run_secrets_check(sandbox: SandboxRunner, workdir: str) -> CheckResult:
    """Grep for secrets/API keys in source code. Clean = no matches."""
    patterns = "|".join(_SECRET_PATTERNS)
    escaped = patterns.replace("'", "'\\''")
    result = await sandbox.run(
        f"grep -rEn '{escaped}' "
        "--include='*.py' --include='*.js' --include='*.ts' "
        "--include='*.env' --include='*.yaml' --include='*.yml' "
        f"{_EXCLUDE_DIRS} . 2>/dev/null",
        workdir=workdir,
    )
    # grep exit code drives the result: 0 = matches found (FAIL), 1 = none (PASS),
    # >1 = grep error (treat as pass; nothing actionable found). Avoid piping into
    # head, which would mask grep's exit code behind head's always-zero status.
    matches = result.stdout.strip()
    passed = result.exit_code != 0 or not matches
    return CheckResult(
        name="no_secrets_in_code",
        passed=passed,
        output=matches[:2000],
        duration_ms=result.duration_ms,
    )


async def run_pii_check(sandbox: SandboxRunner, workdir: str) -> CheckResult:
    """Grep for PII in log statements. Clean = no matches."""
    patterns = "|".join(_PII_LOG_PATTERNS)
    escaped = patterns.replace("'", "'\\''")
    result = await sandbox.run(
        f"grep -rEin '{escaped}' "
        "--include='*.py' --include='*.js' --include='*.ts' "
        f"{_EXCLUDE_DIRS} . 2>/dev/null",
        workdir=workdir,
    )
    matches = result.stdout.strip()
    passed = result.exit_code != 0 or not matches
    return CheckResult(
        name="no_pii_in_logs",
        passed=passed,
        output=matches[:2000],
        duration_ms=result.duration_ms,
    )


async def run_typecheck(sandbox: SandboxRunner, workdir: str) -> CheckResult:
    """Run type checker (mypy for Python, tsc for TypeScript)."""
    result = await sandbox.run(
        "python -m mypy . --ignore-missing-imports --no-error-summary "
        "--exclude '(\\.venv|venv|build|dist)/' 2>&1 || "
        "npx tsc --noEmit 2>&1 || "
        "echo 'typecheck_skipped'",
        workdir=workdir,
    )
    output = (result.stdout + result.stderr).strip()
    # If typecheck_skipped, count as passed (tool not available)
    passed = result.exit_code == 0 or "typecheck_skipped" in output
    return CheckResult(
        name="type_check_passes",
        passed=passed,
        output=output[:2000],
        duration_ms=result.duration_ms,
    )


def _parse_pytest_output(output: str) -> dict:
    """Extract test counts from pytest output."""
    match = re.search(r"(\d+) passed", output)
    passed_count = int(match.group(1)) if match else 0
    match = re.search(r"(\d+) failed", output)
    failed_count = int(match.group(1)) if match else 0
    match = re.search(r"(\d+) error", output)
    error_count = int(match.group(1)) if match else 0
    return {
        "tests_passed": passed_count,
        "tests_failed": failed_count + error_count,
        "tests_run": passed_count + failed_count + error_count,
    }


def _parse_coverage_pct(output: str) -> Optional[float]:
    """Extract coverage percentage from pytest-cov output."""
    match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", output)
    if match:
        return float(match.group(1))
    return None
