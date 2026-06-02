"""Unit tests for benchmark report coverage resolution.

Regression: the Studio Test coverage column was filled from analyze_project (a
static estimate that never runs the suite, so it reads 0.0%), even when the
skeleton verified at e.g. 86%. The report must prefer the real verified coverage
from verification_results, falling back to the estimate only when absent.
"""

from __future__ import annotations

from decimal import Decimal

from studio.benchmark.harness import _resolve_coverage


def test_verified_coverage_wins_over_static_estimate():
    # Two competing sources: verified=86% (DB), static=0.0% (analyze_project).
    verified_from_db = 86.0
    static_from_analyze_project = 0.0
    assert _resolve_coverage(verified_from_db, static_from_analyze_project) == 86.0


def test_verified_coverage_handles_numeric_decimal():
    # verification_results.test_coverage is NUMERIC -> Decimal from the driver.
    assert _resolve_coverage(Decimal("86.00"), 0.0) == 86.0


def test_falls_back_to_static_estimate_when_no_verification_row():
    assert _resolve_coverage(None, 42.5) == 42.5


def test_falls_back_to_zero_when_neither_source_has_data():
    assert _resolve_coverage(None, 0.0) == 0.0
