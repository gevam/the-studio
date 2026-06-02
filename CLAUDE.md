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
- #5 (sandbox): `--network none`, 2GB/2CPU, 5-min timeout.
- _Add new resolutions here as they're decided._

## Things to flag, never assume
Open questions from §13 still pending. If you hit one, stop and ask in the PR.

## Don'ts
- Don't patch ugly code locally — emit a friction event (§4 — this is the whole thesis).
- Don't bypass the verification sandbox.
- Don't add `localStorage` / `sessionStorage` in frontend artifacts.
- Don't change ARCHITECTURE.md without a corresponding ADR entry in the living design schema.
