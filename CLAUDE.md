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

## Deferred to Sprint 3

- **Reviewer cross-family provider.** Sprint 2 shipped the provider registry but the Reviewer ran on `claude-opus-4-5` (Anthropic fallback) because no `OPENAI_API_KEY` was available. §4.4 requires a *different model family* from the other agents to avoid same-family blind spots. Sprint 3 resolution: either (a) wire `OPENAI_API_KEY` into the worker container and default Reviewer to GPT-4o, or (b) document an explicit decision to stay single-family with rationale. Track which path before any Sprint 3 work depends on Reviewer output quality.

- **"Accept on cap" semantics (decision only — visibility now shipped).** Cap-exhaustion forces forward progress even if the slice failed verification / the Reviewer rejected it; "done" can mean "ran out of attempts," not "fixed." Visibility is now in place (PR #5): `slice_done_node` emits `slice.accepted_under_cap` and persists `slices.rework_used` / `slices.accepted_under_cap`. **Remaining decision:** should cap-exhaustion mark the session `degraded` rather than `completed`, or escalate to a human gate (rather than silently accepting)? Decide before Sprint 3 dashboard work — §7.5 Design Health should surface the `accepted_under_cap` flag.

- **Skeleton phase bypasses the unified rework budget (CR #2 + #6).** The unified `slice_rework_budget` governs the design⇄ux loop and the four feature loops, but the skeleton-phase routers (`skeleton_friction_router`, `skeleton_verify_gate_router`) still gate on `iteration < max_design_iterations` — two bounding mechanisms coexist, so "one budget for all rework" isn't literally true and tuning `slice_rework_budget` doesn't affect skeleton churn. Sprint 3: either migrate the skeleton onto `slice_rework_budget` (treat the skeleton as slice 0 and reset the budget on skeleton→`building` — currently the design⇄ux `used` count carries unreset through the skeleton phase, which only stays harmless while the skeleton is on `iteration`), or document the skeleton as a deliberate separate knob.

- **Scope-creep fuzzy fallback keeps wholesale hallucinations (CR #4).** `detect_scope_creep` keeps the entire plan when *nothing* matches, assuming the matcher was too strict — indistinguishable from the LLM hallucinating every slice (only a `requirement.changed` fuzzy-fallback warning fires). Bare-substring matching also over-matches short titles (`"api"` ⊂ `"rapid"`). Sprint 3: switch to token-overlap with a min-overlap threshold (drop bare substring); on a total miss, cap the kept-slice count or escalate to the design human gate instead of silently building everything.
