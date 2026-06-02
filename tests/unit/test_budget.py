"""Unit tests for BudgetEnforcer thresholds and the BudgetExceeded hard stop.

Regression: BudgetEnforcer was exported but never called — a retry loop had no
circuit breaker. These pin the threshold semantics it enforces (§9.4).
"""

from __future__ import annotations

from studio.ai.budget import BudgetEnforcer, BudgetExceeded


def test_under_budget_is_ok():
    enf = BudgetEnforcer()
    assert enf.check(tokens_used=100, token_budget=1000, cost_usd=1.0, cost_budget=50.0) is True


def test_warning_threshold_still_ok():
    # 80% tokens — warns (logged) but does not stop.
    enf = BudgetEnforcer()
    assert enf.check(tokens_used=800, token_budget=1000, cost_usd=0.0, cost_budget=50.0) is True


def test_tokens_exhausted_stops():
    enf = BudgetEnforcer()
    assert enf.check(tokens_used=1000, token_budget=1000, cost_usd=0.0, cost_budget=50.0) is False
    assert enf.check(tokens_used=1500, token_budget=1000, cost_usd=0.0, cost_budget=50.0) is False


def test_cost_exhausted_stops_independently():
    # Tokens fine, cost over → still a hard stop.
    enf = BudgetEnforcer()
    assert enf.check(tokens_used=0, token_budget=1000, cost_usd=50.0, cost_budget=50.0) is False


def test_budget_exceeded_is_runtime_error():
    assert issubclass(BudgetExceeded, RuntimeError)
