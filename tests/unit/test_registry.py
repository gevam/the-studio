"""Tests for the per-agent provider registry (§4.4, §13 #4)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from studio.ai.registry import ProviderRegistry, _resolve_availability, route_agent


def test_route_agent_defaults():
    provider, model = route_agent("design_agent")
    assert (provider, model) == ("anthropic", "claude-sonnet-4-6")


def test_route_agent_reviewer_is_different_family_by_default():
    provider, model = route_agent("reviewer")
    assert provider == "openai"
    assert model == "gpt-4o"


def test_anthropic_falls_back_to_cli_without_key(monkeypatch):
    monkeypatch.setattr("studio.ai.registry.settings.anthropic_api_key", "")
    assert _resolve_availability("anthropic", "claude-sonnet-4-6", agent="design_agent") == (
        "claude_cli", "claude-sonnet-4-6",
    )


def test_anthropic_kept_when_key_present(monkeypatch):
    monkeypatch.setattr("studio.ai.registry.settings.anthropic_api_key", "sk-x")
    assert _resolve_availability("anthropic", "claude-sonnet-4-6", agent="design_agent") == (
        "anthropic", "claude-sonnet-4-6",
    )


def test_openai_reviewer_falls_back_to_distinct_model(monkeypatch):
    monkeypatch.setattr("studio.ai.registry.settings.openai_api_key", "")
    provider, model = _resolve_availability("openai", "gpt-4o", agent="reviewer")
    assert provider == "claude_cli"
    assert model == "claude-opus-4-5"  # distinct from the Sonnet default


def test_registry_caches_provider_instances():
    reg = ProviderRegistry()
    with patch("studio.ai.llm_client.ClaudeCLIProvider") as mock_cls:
        first = reg.get("claude_cli")
        second = reg.get("claude_cli")
        assert first is second
        mock_cls.assert_called_once()


def test_registry_unknown_provider_raises():
    with pytest.raises(ValueError):
        ProviderRegistry().get("nope")
