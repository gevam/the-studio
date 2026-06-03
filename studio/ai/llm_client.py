"""LLM client abstraction: Anthropic SDK + Claude CLI subprocess, with metrics."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog
from pydantic import ValidationError

logger = structlog.get_logger(__name__)

# Pricing constants (claude-sonnet-4-6 as of 2025)
# Adjust if model changes.
_COST_PER_TOKEN_IN: dict[str, float] = {
    "claude-sonnet-4-6": 3.00 / 1_000_000,
    "claude-opus-4-5": 15.00 / 1_000_000,
    "claude-haiku-4-5": 0.25 / 1_000_000,
    "gpt-4o": 2.50 / 1_000_000,
    "gpt-4o-mini": 0.15 / 1_000_000,
}
_COST_PER_TOKEN_OUT: dict[str, float] = {
    "claude-sonnet-4-6": 15.00 / 1_000_000,
    "claude-opus-4-5": 75.00 / 1_000_000,
    "claude-haiku-4-5": 1.25 / 1_000_000,
    "gpt-4o": 10.00 / 1_000_000,
    "gpt-4o-mini": 0.60 / 1_000_000,
}

_DEFAULT_COST_IN = 3.00 / 1_000_000
_DEFAULT_COST_OUT = 15.00 / 1_000_000


def _compute_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    cost_in = _COST_PER_TOKEN_IN.get(model, _DEFAULT_COST_IN)
    cost_out = _COST_PER_TOKEN_OUT.get(model, _DEFAULT_COST_OUT)
    return tokens_in * cost_in + tokens_out * cost_out


def _schema_tool_name(schema: type) -> str:
    """Tool/function name for a Pydantic schema (snake_case-ish, API-safe)."""
    import re

    return re.sub(r"(?<!^)(?=[A-Z])", "_", schema.__name__).lower()


def _extract_json_object(text: str) -> dict:
    """Extract the first valid top-level JSON object from text (CLI fallback)."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = next(
            (i for i in range(len(lines) - 1, 0, -1) if lines[i].strip() == "```"),
            len(lines),
        )
        text = "\n".join(lines[1:end]).strip()
    decoder = json.JSONDecoder()
    idx = 0
    while (brace := text.find("{", idx)) != -1:
        try:
            obj, _ = decoder.raw_decode(text, brace)  # tolerates trailing content
            return obj
        except json.JSONDecodeError:
            idx = brace + 1
    raise ValueError("no valid JSON object found in response")


@dataclass
class LLMResponse:
    content: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model: str
    latency_ms: int


@dataclass
class StructuredResponse:
    """A schema-validated model plus the usage of the call that produced it."""

    parsed: Any
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model: str
    latency_ms: int


class StructuredOutputError(RuntimeError):
    """A provider could not produce schema-valid structured output.

    Raised by a provider's complete_structured on a refusal, a missing/empty
    tool-use block, a None parse, or unparseable text. LLMClient retries once with
    a reminder; if it still fails, this propagates to the node, which marks the
    session errored (same handling as BudgetExceeded) rather than crashing the graph.
    """


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

    async def complete_structured(
        self,
        messages: list[dict],
        *,
        system: str,
        schema: type,
        max_tokens: int,
        temperature: float,
        model: str,
    ) -> StructuredResponse:
        """Return an instance of ``schema`` via native structured output (no parse)."""
        ...


class AnthropicProvider:
    """LLM provider using Anthropic's AsyncAnthropic SDK with cache_control on system."""

    def __init__(self, api_key: str) -> None:
        # Key is passed in by the registry from settings — single source of truth,
        # so the registry's availability check and this constructor never disagree.
        if not api_key:
            raise RuntimeError(
                "Anthropic API key is empty. "
                "Set anthropic_api_key or use provider='claude_cli'."
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

    async def complete_structured(
        self,
        messages: list[dict],
        *,
        system: str,
        schema: type,
        max_tokens: int,
        temperature: float,
        model: str,
    ) -> StructuredResponse:
        # Native tool-calling: force a single tool whose input IS the schema.
        tool_name = _schema_tool_name(schema)
        start = time.monotonic()
        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            tools=[{
                "name": tool_name,
                "description": f"Return a {schema.__name__} object.",
                "input_schema": schema.model_json_schema(),
            }],
            tool_choice={"type": "tool", "name": tool_name},
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        tool_block = next(
            (b for b in response.content if getattr(b, "type", "") == "tool_use"), None,
        )
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        if tool_block is None:
            raise StructuredOutputError(
                f"Anthropic returned no tool_use block for {schema.__name__} "
                f"(stop_reason={getattr(response, 'stop_reason', '?')})"
            )
        try:
            parsed = schema(**tool_block.input)
        except ValidationError as exc:
            raise StructuredOutputError(f"{schema.__name__} validation failed: {exc}") from exc
        return StructuredResponse(
            parsed=parsed,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=_compute_cost(model, tokens_in, tokens_out),
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
        import tempfile

        self._cli_path = self._find_cli()
        # Run the agent CLI in an isolated empty dir so it cannot read the host
        # repo and wander off-task (it is a coding agent, not a bare model).
        self._cwd = tempfile.mkdtemp(prefix="studio-cli-provider-")

    def __del__(self) -> None:
        # Best-effort cleanup of the per-instance temp working dir.
        import shutil

        shutil.rmtree(getattr(self, "_cwd", ""), ignore_errors=True)

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
                cwd=self._cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=full_prompt.encode()), timeout=900
            )
        except TimeoutError:
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

    async def complete_structured(
        self,
        messages: list[dict],
        *,
        system: str,
        schema: type,
        max_tokens: int,
        temperature: float,
        model: str,
    ) -> StructuredResponse:
        """Best-effort structured output — NOT native, unlike the SDK providers.

        The claude CLI has no tool-calling surface, so this constrains the model
        with the JSON Schema in the prompt and parses the reply. Kept only for
        offline (Max-subscription) runs; raises StructuredOutputError when the
        reply isn't schema-valid so LLMClient can retry / the node can degrade.
        """
        schema_json = json.dumps(schema.model_json_schema())
        instruction = (
            f"{system}\n\nOutput ONLY a single JSON object matching this schema. "
            "Start your reply with { and output nothing else — no preamble, no "
            f"explanation, no markdown code fences:\n{schema_json}"
        )
        response = await self.complete(
            messages, system=instruction, max_tokens=max_tokens,
            temperature=temperature, model=model,
        )
        try:
            parsed = schema(**_extract_json_object(response.content))
        except (ValueError, ValidationError) as exc:
            raise StructuredOutputError(
                f"CLI did not return schema-valid JSON for {schema.__name__}: {exc}"
            ) from exc
        return StructuredResponse(
            parsed=parsed,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
            model=model,
            latency_ms=response.latency_ms,
        )


class OpenAIProvider:
    """LLM provider using OpenAI's AsyncOpenAI SDK (for the Reviewer's different family)."""

    def __init__(self, api_key: str) -> None:
        # Key passed in by the registry from settings (single source of truth).
        if not api_key:
            raise RuntimeError("OpenAI API key is empty; cannot use the OpenAI provider.")
        try:
            from openai import AsyncOpenAI  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("openai package not installed") from exc

        self._client = AsyncOpenAI(api_key=api_key)

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
        msgs: list[dict] = [{"role": "system", "content": system}, *messages]
        if prefill:
            msgs.append({"role": "assistant", "content": prefill})

        start = time.monotonic()
        response = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=msgs,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        content = response.choices[0].message.content or ""
        if prefill:
            content = prefill + content
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        cost = _compute_cost(model, tokens_in, tokens_out)

        return LLMResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            model=model,
            latency_ms=latency_ms,
        )

    async def complete_structured(
        self,
        messages: list[dict],
        *,
        system: str,
        schema: type,
        max_tokens: int,
        temperature: float,
        model: str,
    ) -> StructuredResponse:
        # Native structured outputs via the SDK parse helper.
        start = time.monotonic()
        completion = await self._client.beta.chat.completions.parse(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "system", "content": system}, *messages],
            response_format=schema,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        usage = completion.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        message = completion.choices[0].message
        if getattr(message, "refusal", None) or message.parsed is None:
            raise StructuredOutputError(
                f"OpenAI returned no parsed {schema.__name__} "
                f"(refusal={getattr(message, 'refusal', None)!r})"
            )
        return StructuredResponse(
            parsed=message.parsed,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=_compute_cost(model, tokens_in, tokens_out),
            model=model,
            latency_ms=latency_ms,
        )


class LLMClient:
    """Unified LLM client with per-agent provider routing, DB recording, and metrics.

    By default (provider="registry"/"auto") each call routes to the provider+model
    the ProviderRegistry assigns to that agent. Passing a concrete provider name
    forces a single provider for every agent (used by tests and single-model runs);
    that forced instance lives on ``self._provider`` and can be overridden directly.
    """

    def __init__(self, provider: str = "registry", budget_enforcer=None, registry=None) -> None:
        from studio.ai.budget import BudgetEnforcer
        from studio.ai.registry import ProviderRegistry

        self._budget = budget_enforcer or BudgetEnforcer()
        self._registry = registry or ProviderRegistry()
        self._provider: LLMProvider | None = None  # forced single provider (legacy/test)
        self._provider_name: str | None = None

        if provider not in ("registry", "auto"):
            self._provider_name = provider
            self._provider = self._registry.get(provider)  # type: ignore[assignment]

    def _route(self, agent: str, model: str | None) -> tuple[LLMProvider, str]:
        """Resolve the provider instance and model name for this call."""
        if self._provider is not None:
            return self._provider, (model or "claude-sonnet-4-6")
        provider, resolved_model = self._registry.resolve(agent)
        return provider, (model or resolved_model)  # type: ignore[return-value]

    async def complete(
        self,
        agent: str,
        system_prompt: str,
        user_content: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        prompt_hash: str = "",
        session_id: uuid.UUID | None = None,
        db=None,  # AsyncSession | None
        prefill: str = "",
    ) -> LLMResponse:
        """Call the agent's routed LLM, record metrics and events."""
        from studio.observability.metrics import llm_calls_total, llm_latency_seconds

        # Budget circuit breaker: check the session's persisted usage before
        # spending more. Warns at 80% (session.budget_warning), hard-stops at 100%.
        if db is not None and session_id is not None:
            await self._enforce_budget(db, session_id)

        provider, model = self._route(agent, model)
        messages = [{"role": "user", "content": user_content}]

        llm_calls_total.labels(agent=agent, model=model).inc()

        response = await provider.complete(
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

    async def complete_structured(
        self,
        agent: str,
        system_prompt: str,
        user_content: str,
        schema: type,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        prompt_hash: str = "",
        session_id: uuid.UUID | None = None,
        db=None,
    ) -> StructuredResponse:
        """Schema-validated completion via the provider's native structured output."""
        from studio.observability.metrics import llm_calls_total, llm_latency_seconds

        if db is not None and session_id is not None:
            await self._enforce_budget(db, session_id)

        provider, model = self._route(agent, model)
        llm_calls_total.labels(agent=agent, model=model).inc()

        # One retry with an explicit reminder before giving up — a transient bad
        # generation (refusal, stray prose, truncation) usually self-corrects.
        attempts = [
            user_content,
            user_content + (
                "\n\nReminder: respond with ONLY a single JSON object that exactly "
                f"matches the {schema.__name__} schema — no prose, no code fences."
            ),
        ]
        last_exc: StructuredOutputError | None = None
        result = None
        for attempt in attempts:
            try:
                result = await provider.complete_structured(
                    [{"role": "user", "content": attempt}],
                    system=system_prompt, schema=schema,
                    max_tokens=max_tokens, temperature=temperature, model=model,
                )
                break
            except StructuredOutputError as exc:
                last_exc = exc
                logger.warning("structured_output_retry", agent=agent, error=str(exc)[:200])
        if result is None:
            raise last_exc  # exhausted retries — propagate to the node
        llm_latency_seconds.labels(agent=agent, model=model).observe(result.latency_ms / 1000)

        if db is not None and session_id is not None:
            await self._record_call_events(
                db, session_id, agent=agent, model=model, prompt_hash=prompt_hash,
                tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                latency_ms=result.latency_ms, cost_usd=result.cost_usd,
            )

        logger.info(
            "llm_complete_structured", agent=agent, model=model, schema=schema.__name__,
            tokens_in=result.tokens_in, tokens_out=result.tokens_out,
            cost_usd=round(result.cost_usd, 6),
        )
        return result

    async def _record_call_events(
        self, db, session_id: uuid.UUID, *, agent: str, model: str, prompt_hash: str,
        tokens_in: int, tokens_out: int, latency_ms: int, cost_usd: float,
    ) -> None:
        """Emit agent.llm_call/llm_response and record ai_feedback for one call."""
        from studio.events.emitter import emit_event

        await emit_event(
            db, session_id, "agent.llm_call",
            data={
                "agent": agent, "model": model,
                "prompt_hash": prompt_hash, "tokens_in": tokens_in,
            },
            agent=agent,
        )
        await emit_event(
            db, session_id, "agent.llm_response",
            data={"agent": agent, "model": model, "tokens_out": tokens_out,
                  "latency_ms": latency_ms, "cost_usd": cost_usd},
            agent=agent,
        )
        await self._record_ai_feedback(
            db=db, session_id=session_id, agent=agent, model=model, prompt_hash=prompt_hash,
            tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms, cost_usd=cost_usd,
        )

    async def _enforce_budget(self, db, session_id: uuid.UUID) -> None:
        """Check the session's persisted budget; raise BudgetExceeded at 100%."""
        from studio.ai.budget import BudgetExceeded
        from studio.db.models import Session

        session = await db.get(Session, session_id)
        if session is None:
            return  # nothing to enforce against yet

        ok = await self._budget.check_and_emit(
            tokens_used=session.tokens_used or 0,
            token_budget=session.token_budget or 1,
            cost_usd=float(session.cost_usd or 0.0),
            cost_budget=float(session.cost_budget or 0.001),
            session_id=session_id,
            db=db,
        )
        if not ok:
            raise BudgetExceeded(
                f"Session {session_id} budget exhausted: "
                f"tokens {session.tokens_used}/{session.token_budget}, "
                f"cost ${float(session.cost_usd):.4f}/${float(session.cost_budget):.2f}"
            )

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
        from studio.events.emitter import emit_event

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
            return

        # §7.2 mandatory event paired with the ai_feedback row.
        await emit_event(
            db,
            session_id,
            "ai.feedback_recorded",
            data={"agent": agent, "quality_signal": "llm_call_recorded"},
            agent=agent,
        )
