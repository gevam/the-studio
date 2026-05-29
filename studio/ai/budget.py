"""Budget enforcement for LLM sessions."""

from __future__ import annotations

import logging
import uuid
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class BudgetEnforcer:
    """Check token and cost budgets; emit warnings at 80%, hard-stop at 100%."""

    WARNING_THRESHOLD = 0.80

    def check(
        self,
        tokens_used: int,
        token_budget: int,
        cost_usd: float,
        cost_budget: float,
    ) -> bool:
        """Return True if it is OK to continue (budget not exhausted).

        Emits a synchronous log warning at 80%. Returns False when budget exceeded.
        """
        token_pct = tokens_used / max(token_budget, 1)
        cost_pct = cost_usd / max(cost_budget, 0.001)

        if token_pct >= 1.0 or cost_pct >= 1.0:
            logger.warning(
                "session_budget_exceeded",
                tokens_used=tokens_used,
                token_budget=token_budget,
                cost_usd=cost_usd,
                cost_budget=cost_budget,
            )
            return False

        if token_pct >= self.WARNING_THRESHOLD or cost_pct >= self.WARNING_THRESHOLD:
            logger.warning(
                "session_budget_warning",
                token_pct=round(token_pct * 100, 1),
                cost_pct=round(cost_pct * 100, 1),
                tokens_used=tokens_used,
                token_budget=token_budget,
                cost_usd=cost_usd,
                cost_budget=cost_budget,
            )

        return True

    async def check_and_emit(
        self,
        tokens_used: int,
        token_budget: int,
        cost_usd: float,
        cost_budget: float,
        *,
        session_id: uuid.UUID,
        db,  # AsyncSession
    ) -> bool:
        """Same as check() but also emits session.budget_warning event via DB."""
        ok = self.check(tokens_used, token_budget, cost_usd, cost_budget)

        token_pct = tokens_used / max(token_budget, 1)
        cost_pct = cost_usd / max(cost_budget, 0.001)

        if token_pct >= self.WARNING_THRESHOLD or cost_pct >= self.WARNING_THRESHOLD:
            from studio.events.emitter import emit_event

            await emit_event(
                db,
                session_id,
                "session.budget_warning",
                data={
                    "tokens_used": tokens_used,
                    "token_budget": token_budget,
                    "token_pct": round(token_pct * 100, 1),
                    "cost_usd": cost_usd,
                    "cost_budget": cost_budget,
                    "cost_pct": round(cost_pct * 100, 1),
                },
            )

        return ok
