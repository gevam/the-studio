"""Tests for structured-output support (CR §6 prerequisite; no prompt-and-parse)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from studio.ai.llm_client import (
    ClaudeCLIProvider,
    LLMClient,
    LLMResponse,
    StructuredResponse,
    _extract_json_object,
    _schema_tool_name,
)


class Sample(BaseModel):
    name: str
    score: int


def test_schema_tool_name_snake_cases():
    assert _schema_tool_name(Sample) == "sample"

    class RubricScore(BaseModel):
        x: int = 0

    assert _schema_tool_name(RubricScore) == "rubric_score"


def test_extract_json_object_handles_prose_and_fences_and_trailing():
    assert _extract_json_object('here: {"name": "a", "score": 1} done')["score"] == 1
    assert _extract_json_object('```json\n{"name": "b", "score": 2}\n```')["name"] == "b"


@pytest.mark.asyncio
async def test_cli_structured_validates_against_schema(monkeypatch):
    provider = ClaudeCLIProvider()
    # Stub the underlying text completion; structured wraps + validates it.
    provider.complete = AsyncMock(  # type: ignore[method-assign]
        return_value=LLMResponse(
            content='{"name": "todo", "score": 9}', tokens_in=10, tokens_out=5,
            cost_usd=0.001, model="m", latency_ms=10,
        )
    )
    result = await provider.complete_structured(
        [{"role": "user", "content": "go"}], system="sys", schema=Sample,
        max_tokens=100, temperature=0.0, model="m",
    )
    assert isinstance(result.parsed, Sample)
    assert result.parsed.name == "todo" and result.parsed.score == 9


@pytest.mark.asyncio
async def test_llm_client_complete_structured_routes_and_returns_parsed():
    client = LLMClient(provider="claude_cli")
    client._provider = AsyncMock()
    client._provider.complete_structured = AsyncMock(
        return_value=StructuredResponse(
            parsed=Sample(name="x", score=3), tokens_in=10, tokens_out=5,
            cost_usd=0.001, model="m", latency_ms=10,
        )
    )
    result = await client.complete_structured(
        agent="reviewer", system_prompt="s", user_content="u", schema=Sample,
    )
    assert result.parsed.score == 3
    client._provider.complete_structured.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_structured_retries_once_then_raises():
    # Provider always fails → LLMClient retries exactly once, then raises.
    from studio.ai.llm_client import StructuredOutputError

    client = LLMClient(provider="claude_cli")
    client._provider = AsyncMock()
    client._provider.complete_structured = AsyncMock(
        side_effect=StructuredOutputError("no valid JSON"),
    )
    with pytest.raises(StructuredOutputError):
        await client.complete_structured(
            agent="reviewer", system_prompt="s", user_content="u", schema=Sample,
        )
    assert client._provider.complete_structured.await_count == 2  # initial + 1 retry


@pytest.mark.asyncio
async def test_complete_structured_recovers_on_retry():
    from studio.ai.llm_client import StructuredOutputError

    client = LLMClient(provider="claude_cli")
    client._provider = AsyncMock()
    client._provider.complete_structured = AsyncMock(side_effect=[
        StructuredOutputError("bad"),
        StructuredResponse(parsed=Sample(name="ok", score=5), tokens_in=1, tokens_out=1,
                           cost_usd=0.0, model="m", latency_ms=1),
    ])
    result = await client.complete_structured(
        agent="reviewer", system_prompt="s", user_content="u", schema=Sample,
    )
    assert result.parsed.score == 5
