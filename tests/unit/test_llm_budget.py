"""Unit test: LLMClient.complete enforces budget before calling the provider."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from studio.ai.budget import BudgetExceeded
from studio.ai.llm_client import LLMClient, LLMResponse


class _FakeSession:
    tokens_used = 2000
    token_budget = 1000  # already exhausted
    cost_usd = 0.0
    cost_budget = 50.0


@pytest.mark.asyncio
async def test_complete_raises_before_provider_when_over_budget():
    # Mocked provider + enforcer + db so no network / DB needed. The real
    # threshold logic is covered in test_budget.py; here we assert the wiring:
    # an over-budget verdict aborts before the provider is called.
    client = LLMClient(provider="claude_cli")  # constructs but never invokes the CLI
    client._provider = AsyncMock()
    client._budget = MagicMock()
    client._budget.check_and_emit = AsyncMock(return_value=False)

    db = AsyncMock()
    db.get = AsyncMock(return_value=_FakeSession())

    with pytest.raises(BudgetExceeded):
        await client.complete(
            agent="design_agent",
            system_prompt="sys",
            user_content="hi",
            session_id=uuid.uuid4(),
            db=db,
        )

    client._provider.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_proceeds_when_under_budget():
    client = LLMClient(provider="claude_cli")
    client._provider = AsyncMock(
        return_value=None,
        complete=AsyncMock(
            return_value=LLMResponse(
                content="ok", tokens_in=10, tokens_out=5,
                cost_usd=0.001, model="m", latency_ms=10,
            )
        ),
    )

    class _Ok(_FakeSession):
        tokens_used = 10
        token_budget = 1000

    db = AsyncMock()
    db.get = AsyncMock(return_value=_Ok())

    # No session_id/db → skips both budget check and event emission entirely.
    resp = await client.complete(
        agent="design_agent", system_prompt="sys", user_content="hi",
    )
    assert resp.content == "ok"
    client._provider.complete.assert_awaited_once()
