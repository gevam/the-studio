"""Provider registry: per-agent LLM provider routing with graceful fallback.

Replaces the Sprint 1 single-provider construction (CR §6 prerequisite). Each
agent routes to a (provider, model) pair from config; the Reviewer defaults to a
different model family (§4.4, §13 #4). Providers are constructed lazily and cached.

Fallback policy (so a session can still run when a key/SDK is missing):
  anthropic → claude_cli   when ANTHROPIC_API_KEY is unset
  openai    → claude_cli   when OPENAI_API_KEY is unset
The Reviewer thus still runs offline, just not on a different family — logged.
"""

from __future__ import annotations

import structlog

from studio.config import settings

logger = structlog.get_logger(__name__)

# Model used for the Reviewer when it has to fall back to the Claude family — kept
# distinct from the other agents' default so it is still "a different model".
_REVIEWER_FALLBACK_MODEL = "claude-opus-4-5"


def route_agent(agent: str) -> tuple[str, str]:
    """Return the (provider_name, model) configured for an agent."""
    if agent == "reviewer":
        return settings.reviewer_provider, settings.reviewer_model
    return settings.default_provider, settings.default_model


def _resolve_availability(provider_name: str, model: str, *, agent: str) -> tuple[str, str]:
    """Apply fallback when the configured provider's credentials are unavailable."""
    if provider_name == "anthropic" and not settings.anthropic_api_key:
        return "claude_cli", model
    if provider_name == "openai" and not settings.openai_api_key:
        fallback_model = _REVIEWER_FALLBACK_MODEL if agent == "reviewer" else settings.default_model
        logger.warning(
            "provider_fallback",
            agent=agent, requested="openai", reason="OPENAI_API_KEY unset",
            fallback="claude_cli", model=fallback_model,
        )
        return "claude_cli", fallback_model
    return provider_name, model


class ProviderRegistry:
    """Constructs and caches LLMProvider instances, and resolves agent routing."""

    def __init__(self) -> None:
        self._cache: dict[str, object] = {}

    def get(self, provider_name: str) -> object:
        """Return a cached provider instance by name."""
        if provider_name not in self._cache:
            self._cache[provider_name] = self._construct(provider_name)
        return self._cache[provider_name]

    def resolve(self, agent: str) -> tuple[object, str]:
        """Return the (provider_instance, model) an agent should use."""
        provider_name, model = route_agent(agent)
        provider_name, model = _resolve_availability(provider_name, model, agent=agent)
        return self.get(provider_name), model

    @staticmethod
    def _construct(provider_name: str) -> object:
        from studio.ai.llm_client import (
            AnthropicProvider,
            ClaudeCLIProvider,
            OpenAIProvider,
        )

        if provider_name == "anthropic":
            return AnthropicProvider(settings.anthropic_api_key)
        if provider_name == "openai":
            return OpenAIProvider(settings.openai_api_key)
        if provider_name == "claude_cli":
            return ClaudeCLIProvider()
        raise ValueError(f"Unknown provider: {provider_name!r}")
