# Cap-hitting diagnosis — why all 4 url-shortener slices hit the rework cap

**Session:** `ab01b4e6-8ff6-4f42-a17e-0d8f71a9c7be` (instrumented re-run, `diag/cap-investigation`)
**Outcome:** `status=completed`, 95% coverage, **all 4 feature slices `accepted_under_cap`** (`rework_used=7`, budget 5).

## Verdict: **H1 (convergence bug), uniform across all 4 slices.**

The rework loop rejects on the **same issue every attempt and never improves**. It is the
**friction loop** — not the reviewer — that exhausts the budget, and the friction is *identical*
on every iteration.

## What consumed the budget

Per slice, `rework_used=7` breaks down as **5 friction + 1 ux + 1 reviewer**:

| loop_type | events (4 slices) | per slice |
|---|---|---|
| friction | 20 | 5 (attempts 0–4) |
| ux | 4 | 1 (cap-accepted) |
| reviewer | 4 | 1 (cap-accepted) |
| verify | 0 | — |

The **friction loop alone spends the entire budget (5/5)**. By the time the slice reaches
`ux_review`/`reviewer`, the budget is exhausted, so each runs exactly once and is accepted on
cap — the reviewer never gets a second attempt to act on its feedback.

## The friction trail (the H1 signal)

Every slice, every attempt, byte-identical:

```
attempt 0 | [high/duplication] 10 duplicate code block(s) detected (≥6 lines each)
attempt 1 | [high/duplication] 10 duplicate code block(s) detected (≥6 lines each)
attempt 2 | [high/duplication] 10 duplicate code block(s) detected (≥6 lines each)
attempt 3 | [high/duplication] 10 duplicate code block(s) detected (≥6 lines each)
attempt 4 | [high/duplication] 10 duplicate code block(s) detected (≥6 lines each)
```

Flat. Same category, same count, same description — for all four slices. That is the H1 test
(*same issue across ≥3 attempts, flat score*) satisfied decisively and uniformly.

### Reviewer trail (one attempt/slice — no trajectory to read)

| slice | attempt | overall_score | rejection reason |
|---|---|---|---|
| Shorten a URL | 6 | 2.9 | "no changed files … working tree is clean" |
| Follow a short link (redirect) | 6 | 4.4 | "No changed files provided, no rubric criterion could be anchored to file:line" |
| Record/view click statistics | 6 | 2.8 | "No changed files provided — the implementation could not be anchored" |
| Enforce rate limiting | 6 | 4.2 | "Changed files: none for a slice that introduces multiple new components" |

The reviewer rejects on **missing evidence, not code quality** — `reviewer_node` passes no
`code_artifacts`, so the Reviewer has nothing to anchor to. Secondary bug; **not** the cap driver
(it only runs once per slice).

## Why the friction loop can't converge (root cause)

Duplication is a **code-level** defect, but the friction loop routes it to the **design agent**:

`build_agent` (detects 10 duplicate blocks) → `feature_friction_router` → `design_agent`
(revises the *design*, marks friction "resolved") → `build_agent` (regenerates code) → **same 10
duplicate blocks** → repeat.

Two breaks in the feedback path:
1. **The design→build handoff drops the friction.** `BuildAgentInput` (built in `build_agent_node`)
   carries `design_digest` / `slice_name` / `slice_description` — **not** the friction items. So the
   build agent regenerates without ever being told "you produced 10 duplicate blocks; dedupe them."
2. **A design revision cannot fix code-level duplication.** `design_agent` marks the friction
   `resolved` on revision (the Sprint-1 "optimistic resolution" note), but the generated code is
   unchanged, so the detector re-reports the identical friction next build.

The loop is **structurally incapable** of resolving duplication/complexity friction: the signal
goes to the one agent that can't act on it, and is marked resolved without the code changing.

## Cross-cutting: is the opus-fallback Reviewer contributing?

**No — not to the cap.** The cap is friction-driven; the reviewer isn't even reached a second time.
Its rejections are a legitimate process complaint ("no changed files"), not same-family nitpicking.
The cross-family-provider item stays lower priority **for this symptom** (revisit once the reviewer
actually gets `code_artifacts` and iterates).

## Recommended Sprint 3 opening move (H1)

**Fix the friction feedback path before anything else** — it's a real convergence bug, and it's
why "completed/95%" is really "force-accepted on every slice."

Concretely, in priority order:
1. **Feed friction to the agent that can act on it.** Route code-level friction
   (`duplication`, `complexity`) to a **build rebuild** carrying the specific friction
   (locations + "dedupe/decompose this"), rather than to `design_agent`. Minimal change:
   thread `pending_friction` (descriptions + `code_location`) into `BuildAgentInput` and the build
   prompt so regeneration addresses it.
2. **Stop marking friction resolved on design revision** unless re-detection confirms it cleared
   (ties to the tracked optimistic-resolution decision). Otherwise the metric and the loop both lie.
3. **Then** fix `reviewer_node` to pass `code_artifacts` (the `slice.built` event shows
   `files_changed=8`, so the data exists — the reviewer just isn't given it), so the reviewer can
   review substance once the budget isn't pre-consumed by friction.

A budget increase (H3) is **not** the answer — more attempts of an unconverging loop just burns more
tokens on the identical friction. "Mark degraded" is the honest status here only *after* #1/#2,
since today the rework is genuinely accomplishing nothing.

## Diagnostic SQL (re-runnable)

```sql
-- Per-loop budget consumption
SELECT data->>'loop_type', count(*)
FROM event_log WHERE event_type='rework.attempt' AND session_id='<run>'
GROUP BY 1 ORDER BY 2 DESC;

-- Friction trail (the H1 signal: same text every attempt)
SELECT data->>'slice_name', data->>'attempt', data->>'friction'
FROM event_log WHERE event_type='rework.attempt' AND session_id='<run>'
  AND data->>'loop_type'='friction' ORDER BY data->>'slice_name', seq;

-- Reviewer rejection trail (overall_score trajectory + issues)
SELECT data->>'slice_name', data->>'attempt', data->>'overall_score', data->>'issues'
FROM event_log WHERE event_type='rework.attempt' AND session_id='<run>'
  AND data->>'loop_type'='reviewer' ORDER BY data->>'slice_name', seq;
```

## Disposition of the instrumentation

The `rework.attempt` event is **worth promoting** into Sprint 3 (not throwaway): it's the only thing
that distinguished H1 from H3 here, and it feeds the §7.5 "why did this slice hit the cap" dashboard
directly. Recommend keeping it (un-gating or leaving the `rework_trace` flag, default off in prod),
but the `diag/cap-investigation` branch itself stays unmerged — cherry-pick `_rework_trace.py` + the
node calls into the Sprint 3 work.
