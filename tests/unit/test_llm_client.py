"""Tests for LLMClient and providers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from studio.ai.llm_client import LLMClient, LLMResponse, _compute_cost


def test_compute_cost_sonnet():
    cost = _compute_cost("claude-sonnet-4-6", tokens_in=1000, tokens_out=500)
    expected = 1000 * 3.0 / 1_000_000 + 500 * 15.0 / 1_000_000
    assert abs(cost - expected) < 1e-9


def test_compute_cost_unknown_model_uses_default():
    cost = _compute_cost("unknown-model", tokens_in=1000, tokens_out=1000)
    assert cost > 0


@pytest.mark.asyncio
async def test_llm_client_auto_uses_anthropic_when_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    with patch("studio.ai.llm_client.AnthropicProvider") as mock_cls:
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = LLMResponse(
            content="test",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
            model="claude-sonnet-4-6",
            latency_ms=100,
        )
        mock_cls.return_value = mock_provider

        client = LLMClient(provider="auto")
        assert client._provider_name == "anthropic"


@pytest.mark.asyncio
async def test_llm_client_complete_calls_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with patch("studio.ai.llm_client.ClaudeCLIProvider") as mock_cls:
        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value=LLMResponse(
            content="hello",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.001,
            model="claude-sonnet-4-6",
            latency_ms=200,
        ))
        mock_cls.return_value = mock_provider

        client = LLMClient(provider="claude_cli")
        response = await client.complete(
            agent="test",
            system_prompt="system",
            user_content="hello",
        )
        assert response.content == "hello"
        assert response.tokens_in == 10


def test_llm_client_invalid_provider():
    with pytest.raises(ValueError):
        LLMClient(provider="invalid")
