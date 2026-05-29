"""LLM client abstraction: Anthropic SDK + Claude CLI subprocess, with metrics."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)

# Pricing constants (claude-sonnet-4-6 as of 2025)
# Adjust if model changes.
_COST_PER_TOKEN_IN: dict[str, float] = {
    "claude-sonnet-4-6": 3.00 / 1_000_000,
    "claude-opus-4-5": 15.00 / 1_000_000,
    "claude-haiku-4-5": 0.25 / 1_000_000,
}
_COST_PER_TOKEN_OUT: dict[str, float] = {
    "claude-sonnet-4-6": 15.00 / 1_000_000,
    "claude-opus-4-5": 75.00 / 1_000_000,
    "claude-haiku-4-5": 1.25 / 1_000_000,
}

_DEFAULT_COST_IN = 3.00 / 1_000_000
_DEFAULT_COST_OUT = 15.00 / 1_000_000


def _compute_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    cost_in = _COST_PER_TOKEN_IN.get(model, _DEFAULT_COST_IN)
    cost_out = _COST_PER_TOKEN_OUT.get(model, _DEFAULT_COST_OUT)
    return tokens_in * cost_in + tokens_out * cost_out


@dataclass
class LLMResponse:
    content: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model: str
    latency_ms: int


@runtime_checkable
class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[dict],
        *,
        system: str,
        max_tokens: int,
        temperature: float,
        model: str,
        prefill: str = "",
    ) -> LLMResponse: ...


class AnthropicProvider:
    """LLM provider using Anthropic's AsyncAnthropic SDK with cache_control on system."""

    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY") or ""
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Set the env var or use provider='claude_cli'."
            )
        try:
            from anthropic import AsyncAnthropic  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("anthropic package not installed") from exc

        self._client = AsyncAnthropic(api_key=api_key)

    async def complete(
        self,
        messages: list[dict],
        *,
        system: str,
        max_tokens: int,
        temperature: float,
        model: str,
        prefill: str = "",
    ) -> LLMResponse:
        from anthropic import AsyncAnthropic  # type: ignore[import]

        msgs = list(messages)
        if prefill:
            msgs = msgs + [{"role": "assistant", "content": prefill}]

        start = time.monotonic()
        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=msgs,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        content = response.content[0].text if response.content else ""
        if prefill:
            content = prefill + content
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        cost = _compute_cost(model, tokens_in, tokens_out)

        return LLMResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            model=model,
            latency_ms=latency_ms,
        )


class ClaudeCLIProvider:
    """LLM provider using the claude CLI subprocess (for Max subscription auth).

    NOTE: The claude CLI is installed on the HOST at ~/.local/bin/claude.
    It is NOT available inside Docker worker containers.
    For Sprint 1, run benchmarks directly via Python (not through Arq).
    """

    # Search path for the claude binary
    _CLI_CANDIDATES = [
        "/home/geva/.local/bin/claude",
        "claude",  # fallback: hope it's on PATH
    ]

    def __init__(self) -> None:
        self._cli_path = self._find_cli()

    def _find_cli(self) -> str:
        import shutil

        for candidate in self._CLI_CANDIDATES:
            if candidate == "claude":
                found = shutil.which("claude")
                if found:
                    return found
            else:
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    return candidate
        # Default — will fail at runtime if not present
        return "claude"

    async def complete(
        self,
        messages: list[dict],
        *,
        system: str,
        max_tokens: int,
        temperature: float,
        model: str,
        prefill: str = "",
    ) -> LLMResponse:
        # Build a single prompt string: system + user turns concatenated
        prompt_parts: list[str] = []
        if system:
            prompt_parts.append(f"<system>\n{system}\n</system>")
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle content blocks
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            prompt_parts.append(f"<{role}>\n{content}\n</{role}>")
        if prefill:
            # Open the assistant turn without closing it so CLI continues from prefill
            prompt_parts.append(f"<assistant>\n{prefill}")

        full_prompt = "\n\n".join(prompt_parts)

        cmd = [
            self._cli_path,
            "-p",
            "--output-format", "json",
        ]

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=full_prompt.encode()), timeout=900
            )
        except asyncio.TimeoutError:
            raise RuntimeError("Claude CLI timed out after 900s")
        except FileNotFoundError:
            raise RuntimeError(
                f"Claude CLI not found at {self._cli_path}. "
                "Install claude or set ANTHROPIC_API_KEY."
            )

        latency_ms = int((time.monotonic() - start) * 1000)

        if proc.returncode != 0:
            err = stderr.decode(errors="replace")
            raise RuntimeError(f"Claude CLI exited with code {proc.returncode}: {err}")

        raw = stdout.decode(errors="replace").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Claude CLI returned invalid JSON: {exc}\nRaw: {raw[:500]}")

        content = parsed.get("result", "")
        if prefill:
            content = prefill + content
        cost_usd = float(parsed.get("total_cost_usd", 0.0))

        usage = parsed.get("usage", {})
        tokens_in = int(usage.get("input_tokens", 0))
        tokens_out = int(usage.get("output_tokens", 0))

        return LLMResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            model=model,
            latency_ms=latency_ms,
        )


class LLMClient:
    """Unified LLM client that records to DB, emits events, and tracks metrics."""

    def __init__(self, provider: str = "auto") -> None:
        if provider == "auto":
            api_key = os.environ.get("ANTHROPIC_API_KEY") or ""
            if api_key:
                self._provider: LLMProvider = AnthropicProvider()
                self._provider_name = "anthropic"
            else:
                self._provider = ClaudeCLIProvider()
                self._provider_name = "claude_cli"
        elif provider == "anthropic":
            self._provider = AnthropicProvider()
            self._provider_name = "anthropic"
        elif provider == "claude_cli":
            self._provider = ClaudeCLIProvider()
            self._provider_name = "claude_cli"
        else:
            raise ValueError(f"Unknown provider: {provider!r}")

    async def complete(
        self,
        agent: str,
        system_prompt: str,
        user_content: str,
        *,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
        temperature: float = 0.0,
        prompt_hash: str = "",
        session_id: Optional[uuid.UUID] = None,
        db=None,  # AsyncSession | None
        prefill: str = "",
    ) -> LLMResponse:
        """Call the LLM, record metrics and events."""
        from studio.observability.metrics import llm_calls_total, llm_latency_seconds

        messages = [{"role": "user", "content": user_content}]

        llm_calls_total.labels(agent=agent, model=model).inc()

        response = await self._provider.complete(
            messages,
            system=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model,
            prefill=prefill,
        )

        llm_latency_seconds.labels(agent=agent, model=model).observe(
            response.latency_ms / 1000
        )

        # Emit events if we have a DB session
        if db is not None and session_id is not None:
            from studio.events.emitter import emit_event

            await emit_event(
                db,
                session_id,
                "agent.llm_call",
                data={
                    "agent": agent,
                    "model": model,
                    "prompt_hash": prompt_hash,
                    "tokens_in": response.tokens_in,
                },
                agent=agent,
            )
            await emit_event(
                db,
                session_id,
                "agent.llm_response",
                data={
                    "agent": agent,
                    "model": model,
                    "tokens_out": response.tokens_out,
                    "latency_ms": response.latency_ms,
                    "cost_usd": response.cost_usd,
                },
                agent=agent,
            )

            # Record to ai_feedback table
            await self._record_ai_feedback(
                db=db,
                session_id=session_id,
                agent=agent,
                model=model,
                prompt_hash=prompt_hash,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                latency_ms=response.latency_ms,
                cost_usd=response.cost_usd,
            )

        logger.info(
            "llm_complete",
            agent=agent,
            model=model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=round(response.cost_usd, 6),
            latency_ms=response.latency_ms,
        )

        return response

    async def _record_ai_feedback(
        self,
        *,
        db,
        session_id: uuid.UUID,
        agent: str,
        model: str,
        prompt_hash: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        cost_usd: float,
    ) -> None:
        from studio.db.models import AIFeedback

        row = AIFeedback(
            session_id=session_id,
            loop="design_build",
            agent=agent,
            model=model,
            prompt_hash=prompt_hash,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )
        db.add(row)
        try:
            await db.flush()
        except Exception as exc:
            logger.warning("ai_feedback_flush_failed", error=str(exc))
