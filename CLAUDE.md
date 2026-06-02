# The Studio — Claude Code Memory

## What this is
A multi-agent SDLC system. Read **ARCHITECTURE.md** in full before any task.
Everything in this file is operational rules; ARCHITECTURE.md is the design.

## Source of truth
- **ARCHITECTURE.md** — the design spec. Cite section numbers (§4.5, §7.2) in commits and PRs.
- **prompts/** — agent prompts are versioned config, not code (§8.2). Hot-reloadable.
- **sprint-1-report.md** (after each acceptance run) — current state of the build.

## Workflow rules
- Branch per sprint: `sprint-N`. Never commit to `master`.
- Conventional Commits: `feat:`, `fix:`, `test:`, `chore:`, `docs:`. Reference the section: `feat(§4.5): friction detector for testability category`.
- Open a PR when the sprint's Definition of Done passes. Do NOT merge — humans review.
- Every bug fix needs a regression test under `tests/` that would have caught it.

## Build order (§19)
Foundations before agents. Design⇄Build loop before UX/Reviewer. Loops before UI. Never skip ahead.

## Coding standards
- Python 3.12, async-first, strict mypy.
- SQLAlchemy 2.0 async. No raw SQL except in migrations.
- Pydantic 2 for all I/O contracts; never prompt-and-parse.
- structlog for logs; never `print`. Never log PII or secrets (§7.1).
- Tests: pytest + pytest-asyncio. ≥80% coverage gate (§4.6).
- Frontend: TypeScript strict, no `any`. shadcn/ui + Tailwind. No localStorage.

## Definition of "done" for any change
- Tests pass locally (`pytest`).
- New code has tests.
- `ruff check .` and `mypy studio/ --strict` are clean.
- Event emissions match §7.2 if applicable.
- `./sprint-N-acceptance.sh` still passes if the sprint has one.

## Open questions resolved so far
- #1 (coding agent interface): `claude` CLI subprocess, abstracted behind `CodingAgent` Protocol.
- #3 (auth): API key if present, else `claude` CLI Max auth.
- #4 (Reviewer model): different family from the other agents — default `openai`/`gpt-4o` (config: `reviewer_provider`/`reviewer_model`). When `OPENAI_API_KEY` is absent it falls back to `claude_cli` on `claude-opus-4-5` (still a distinct model from the Sonnet agents). Routing lives in `studio/ai/registry.py`.
- #5 (sandbox): `--network none`, 2GB/2CPU, 5-min timeout.
- _Add new resolutions here as they're decided._

## Deferred decisions (tracked for Sprint 2)
From the PR #2 code review. Behavior NOT changed yet — decide before building on it:
- **Friction resolution semantics:** today friction is marked `resolved` when the design agent *produces a revision* in response (resolution-on-revision), not when re-verification confirms the friction is gone (resolution-on-reverify). All friction IDs passed to the agent are resolved regardless of what the LLM addressed — partial resolution isn't representable. Decide which semantics we want; it affects the resolution-rate metric. (See `tests/unit/agents/test_design.py`.)
- **Verify→Build vs Verify→Design edge:** verification failures currently route to the Design agent (Sprint 1 thesis). §4.6 says deterministic-check failures route to Build. Split the edges when the Reviewer lands.
- **Provider registry:** `LLMClient` binds one provider at construction. §4.4 Reviewer needs a different-family model → add `OpenAIProvider` + per-agent `agent → (provider, model)` routing (Sprint 2 first task).
- **Structured output:** agents prompt-and-parse JSON. Reviewer (§4.4) needs Pydantic structured output / tool-calling — add to the provider layer before the Reviewer.
- **Digest token cap (§9.1):** `generate_digest` is not length-enforced; add an `estimate_tokens` + truncate before complex designs.
- **`--strict` mypy in verification (§4.6)** and **cache-token cost accounting (§9.2):** track and tighten.

## Things to flag, never assume
Open questions from §13 still pending. If you hit one, stop and ask in the PR.

## Don'ts
- Don't patch ugly code locally — emit a friction event (§4 — this is the whole thesis).
- Don't bypass the verification sandbox.
- Don't add `localStorage` / `sessionStorage` in frontend artifacts.
- Don't change ARCHITECTURE.md without a corresponding ADR entry in the living design schema.
