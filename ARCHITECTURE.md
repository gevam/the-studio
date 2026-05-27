# The Studio — Architecture & Implementation Guide

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [LangGraph Definition](#2-langgraph-definition)
3. [Postgres Schema & State Projection](#3-postgres-schema--state-projection)
4. [Agent Specifications](#4-agent-specifications)
5. [Living Design Artifact Schema](#5-living-design-artifact-schema)
6. [API Surface](#6-api-surface)
7. [Observability Plan](#7-observability-plan)
8. [AI-Native Plan](#8-ai-native-plan)
9. [Token Efficiency & Prompt Caching](#9-token-efficiency--prompt-caching)
10. [CI/CD Pipeline & Environments](#10-cicd-pipeline--environments)
11. [Benchmark Harness](#11-benchmark-harness)
12. [Phased Build Plan](#12-phased-build-plan)
13. [Open Questions](#13-open-questions)

---

## 1. System Architecture

### 1.1 Component Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Docker Compose Stack                        │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐│
│  │  React/Vite  │   │   FastAPI     │   │     Arq Worker           ││
│  │  Frontend    │◄─►│   Backend     │◄─►│  (Durable Execution)     ││
│  │  :5173       │ws │   :8000       │   │                          ││
│  └──────────────┘   └──────┬───────┘   │  ┌────────────────────┐  ││
│                            │           │  │  LangGraph Engine   │  ││
│                            │           │  │                     │  ││
│                            │           │  │  ┌───────┐          │  ││
│                            │           │  │  │Design │◄─┐       │  ││
│                            │           │  │  │Agent  │  │       │  ││
│                            │           │  │  └───┬───┘  │       │  ││
│                            │           │  │      │      │       │  ││
│                            │           │  │  ┌───▼───┐  │       │  ││
│                            │           │  │  │ UX    │  │       │  ││
│                            │           │  │  │ Agent │  │       │  ││
│                            │           │  │  └───┬───┘  │       │  ││
│                            │           │  │      │      │       │  ││
│                            │           │  │  ┌───▼───┐  │       │  ││
│                            │           │  │  │Build  │──┘       │  ││
│                            │           │  │  │Agent  │          │  ││
│                            │           │  │  └───┬───┘          │  ││
│                            │           │  │      │              │  ││
│                            │           │  │  ┌───▼───┐          │  ││
│                            │           │  │  │Review │          │  ││
│                            │           │  │  │Agent  │          │  ││
│                            │           │  │  └───────┘          │  ││
│                            │           │  └────────────────────┘  ││
│                            │           └──────────────────────────┘│
│  ┌──────────────┐   ┌──────▼───────┐   ┌──────────────────────┐   │
│  │   Redis      │   │  Postgres    │   │  Verification        │   │
│  │  (Arq queue) │   │  (all state) │   │  Sandbox             │   │
│  │  :6379       │   │  :5432       │   │  (isolated container)│   │
│  └──────────────┘   └──────────────┘   └──────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                    Observability Stack                           ││
│  │  Prometheus :9090 │ Grafana :3000 │ Jaeger :16686 │ Loki :3100 ││
│  │  Promtail (sidecar)                                             ││
│  └─────────────────────────────────────────────────────────────────┘│
│                                                                     │
│  ┌──────────────┐                                                   │
│  │  Project Vol │  ← Developed project lives here (git-managed)    │
│  └──────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 Key Structural Choices

**Why LangGraph StateGraph (cyclic)?** The three loops (Design⇄UX, Design⇄Build, Build⇄Verification) are inherently cyclic. LangGraph's StateGraph supports cyclic edges as first-class constructs, not exception-handling hacks. Conditional edges route based on state (friction detected → loop back to Design). Human-interrupt nodes are native.

**Why Arq over Celery/background tasks?** Arq is lightweight (Redis-backed), supports job resumption, and avoids the complexity of Celery's broker setup. Graph runs survive API restarts. Cancellation semantics: a `STOPPING` status flag checked between LLM calls; mid-call interruption marks the session `PAUSED_STOPPING` with the last completed node recorded for resumption.

**Why Postgres from day one (not SQLite)?** Concurrent sessions, optimistic locking (`sessions.version`), `JSONB` for flexible structured data, proper indexing for event replay, and the `ai_feedback` append-only table all require a real RDBMS.

**Why a separate verification sandbox?** The developed project's build/test/lint must run in isolation from The Studio's own runtime. A sibling Docker container with a mounted project volume, invoked via Docker API or `docker exec`. No LLM judges code quality — the compiler and test suite do.

**Why WebSocket + event log (not pure polling)?** Real-time streaming of agent output and loop events. But the event log (with monotonic `seq`) is truth — WebSocket is transport. Reconnect with `last_seq`, replay missed events, deduplicate by `seq`. REST fallback via `/sessions/{id}/events?since=`.

---

## 2. LangGraph Definition

### 2.1 Graph Topology

```
                    ┌──────────────┐
                    │  ENTRY       │
                    │  (init_sess) │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  DESIGN      │◄────────────────────────┐
                    │  AGENT       │                          │
                    └──────┬───────┘                          │
                           │                                  │
                    ┌──────▼───────┐                          │
              ┌────►│  UX/CUSTOMER │                          │
              │     │  AGENT       │                          │
              │     └──────┬───────┘                          │
              │            │                                  │
              │     ┌──────▼───────┐                          │
              │     │  DESIGN_UX   │──► needs_revision? ──YES─┘
              │     │  GATE        │                     │
              │     └──────────────┘                    NO
              │                                         │
              │     ┌──────▼───────┐                    │
              │     │  SKELETON    │ (first pass only)   │
              │     │  BUILD       │                     │
              │     └──────┬───────┘                     │
              │            │                              │
              │     ┌──────▼───────┐                      │
              │     │  SKELETON    │                      │
              │     │  VERIFY      │── fail? ─► DESIGN ──┘
              │     └──────┬───────┘
              │            │ pass
              │     ┌──────▼───────┐
              │     │  HUMAN GATE  │ ← approve design
              │     │  (design)    │
              │     └──────┬───────┘
              │            │ approved
              │     ┌──────▼───────┐
              │     │  SLICE PLAN  │◄────────────────────┐
              │     └──────┬───────┘                     │
              │            │                              │
              │     ┌──────▼───────┐                     │
              │     │  BUILD       │                     │
              │     │  AGENT       │                     │
              │     └──────┬───────┘                     │
              │            │                              │
              │            ├── friction? ──► DESIGN ──► (loops back)
              │            │                              │
              │     ┌──────▼───────┐                     │
              │     │  VERIFY      │                     │
              │     │  (build+test)│── fail? ──► BUILD ──┘
              │     └──────┬───────┘       (retry, max 3)
              │            │ pass
              │     ┌──────▼───────┐
              │     │  UX REVIEW   │── ux_issue? ──► DESIGN
              │     │  (per slice) │
              │     └──────┬───────┘
              │            │ pass
              │     ┌──────▼───────┐
              │     │  REVIEWER    │── reject? ──► BUILD
              │     └──────┬───────┘
              │            │ pass
              │     ┌──────▼───────┐
              │     │  SLICE DONE  │── more_slices? ──► SLICE PLAN
              │     └──────┬───────┘
              │            │ all done
              │     ┌──────▼───────┐
              │     │  HUMAN GATE  │ ← approve MVP
              │     │  (ship)      │
              │     └──────┬───────┘
              │            │
              │     ┌──────▼───────┐
              │     │  COMPLETE    │
              │     └──────────────┘
```

### 2.2 Nodes

```python
# studio/graph/nodes.py

NODES = {
    "init_session":       InitSessionNode,       # Create session, load config
    "design_agent":       DesignAgentNode,        # Run Design agent
    "ux_agent":           UXAgentNode,            # Run UX/Customer agent
    "design_ux_gate":     DesignUXGateNode,       # Evaluate Design⇄UX convergence
    "skeleton_build":     SkeletonBuildNode,       # Build walking skeleton
    "skeleton_verify":    SkeletonVerifyNode,      # Verify skeleton (sandbox)
    "human_gate_design":  HumanGateNode,          # Hard gate: approve design
    "slice_plan":         SlicePlanNode,           # Plan next slice(s)
    "build_agent":        BuildAgentNode,          # Build a slice (via coding agent)
    "verify":             VerifyNode,              # Run build/test/lint in sandbox
    "ux_review":          UXReviewNode,            # UX review per slice
    "reviewer":           ReviewerNode,            # Reviewer agent (different model)
    "slice_done":         SliceDoneNode,           # Check if more slices remain
    "human_gate_ship":    HumanGateNode,           # Hard gate: approve MVP
    "complete":           CompleteNode,            # Finalize session
}
```

### 2.3 Conditional Edges

```python
# studio/graph/edges.py

def design_ux_router(state: GraphState) -> str:
    """After UX review of design, loop back or proceed."""
    if state.design_ux_needs_revision and state.design_ux_iterations < state.config.max_design_ux_loops:
        return "design_agent"  # Loop: Design ⇄ UX
    return "skeleton_build"    # Converged — build skeleton

def skeleton_verify_router(state: GraphState) -> str:
    if not state.skeleton_verified:
        return "design_agent"  # Skeleton failed — design flaw
    return "human_gate_design"

def build_friction_router(state: GraphState) -> str:
    """After build, check for design friction."""
    if state.pending_friction_items:
        return "design_agent"  # Key mechanism: friction → design revision
    return "verify"

def verify_router(state: GraphState) -> str:
    if not state.verification_passed:
        if state.verify_retries < 3:
            return "build_agent"  # Retry build
        return "design_agent"     # Persistent failure = design problem
    return "ux_review"

def ux_review_router(state: GraphState) -> str:
    if state.ux_issues_found:
        return "design_agent"
    return "reviewer"

def reviewer_router(state: GraphState) -> str:
    if state.reviewer_rejected:
        return "build_agent"
    return "slice_done"

def slice_done_router(state: GraphState) -> str:
    if state.remaining_slices:
        return "slice_plan"
    return "human_gate_ship"
```

### 2.4 Graph State

```python
# studio/graph/state.py

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

@dataclass
class GraphState:
    """Thin projection from DB — never holds full artifacts."""
    # Identity
    session_id: UUID
    session_version: int  # optimistic concurrency

    # Design digest (≤500 tokens)
    design_digest: str
    design_version: int
    design_section_ids: list[str]  # IDs for on-demand fetch

    # Loop counters
    current_loop: str  # "design_ux" | "design_build" | "build_verify"
    current_node: str
    iteration: int
    design_ux_iterations: int = 0
    build_iterations: int = 0
    verify_retries: int = 0

    # Routing flags
    design_ux_needs_revision: bool = False
    skeleton_verified: bool = False
    pending_friction_items: list[UUID] = field(default_factory=list)
    verification_passed: bool = False
    ux_issues_found: bool = False
    reviewer_rejected: bool = False
    remaining_slices: list[UUID] = field(default_factory=list)
    current_slice_id: Optional[UUID] = None

    # Budget
    tokens_used: int = 0
    cost_usd: float = 0.0
    token_budget: int = 0
    cost_budget: float = 0.0

    # Human gate
    awaiting_human: bool = False
    human_gate_type: Optional[str] = None  # "design" | "ship"
    human_gate_expires_at: Optional[str] = None

    # Config (loaded once)
    config: Optional[dict] = None

    # Trace context
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
```

### 2.5 Human Interrupt Implementation

```python
# studio/graph/human_gate.py

from langgraph.prebuilt import interrupt

class HumanGateNode:
    def __init__(self, gate_type: str):
        self.gate_type = gate_type  # "design" or "ship"

    async def __call__(self, state: GraphState) -> GraphState:
        # Compute diff since last approval
        diff = await self.compute_diff(state)

        # Persist the gate request with expiry
        gate = await self.create_gate_record(state, diff)

        # Emit event
        await emit_event("human.checkpoint", {
            "gate_type": self.gate_type,
            "session_id": str(state.session_id),
            "expires_at": gate.expires_at.isoformat(),
            "diff_summary": diff.summary,
        })

        # LangGraph interrupt — graph pauses here
        decision = interrupt({
            "gate_type": self.gate_type,
            "diff": diff.to_dict(),
            "expires_at": gate.expires_at.isoformat(),
        })

        # Resumed with decision
        if decision["action"] == "approve":
            state.awaiting_human = False
            return state
        else:
            # "request_changes" — feedback goes to design agent
            state.human_feedback = decision["feedback"]
            state.awaiting_human = False
            # Router will send to design_agent
            return state
```

---

## 3. Postgres Schema & State Projection

### 3.1 Full Schema

```sql
-- studio/db/schema.sql

-- ============================================================
-- SESSIONS
-- ============================================================
CREATE TABLE sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'created'
                    CHECK (status IN (
                        'created', 'running', 'paused', 'stopping',
                        'awaiting_human', 'completed', 'error', 'cancelled'
                    )),
    version         INTEGER NOT NULL DEFAULT 1,  -- optimistic concurrency
    current_node    TEXT,
    current_loop    TEXT,
    iteration       INTEGER NOT NULL DEFAULT 0,

    -- Budget
    token_budget    INTEGER NOT NULL DEFAULT 500000,
    cost_budget     NUMERIC(10,4) NOT NULL DEFAULT 50.0000,
    tokens_used     INTEGER NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10,4) NOT NULL DEFAULT 0.0000,

    -- Config (JSONB for flexibility)
    config          JSONB NOT NULL DEFAULT '{}',

    -- Trace
    trace_id        TEXT,

    -- Arq job
    arq_job_id      TEXT,

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_sessions_status ON sessions(status);

-- ============================================================
-- SESSION LOCKS (per-session mutex for concurrent access)
-- ============================================================
CREATE TABLE session_locks (
    session_id      UUID PRIMARY KEY REFERENCES sessions(id),
    locked_by       TEXT NOT NULL,        -- worker ID
    locked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL  -- stale lock reaping
);

-- ============================================================
-- DESIGN REVISIONS (the living design, versioned)
-- ============================================================
CREATE TABLE design_revisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    version         INTEGER NOT NULL,
    content_hash    TEXT NOT NULL,        -- SHA-256 of content
    content_key     TEXT NOT NULL,        -- object storage / git ref
    digest          TEXT NOT NULL,        -- ≤500 token summary

    -- Sections stored as JSONB array of {id, title, hash}
    section_index   JSONB NOT NULL DEFAULT '[]',

    -- Provenance
    reason          TEXT NOT NULL,
    caused_by_agent TEXT,                 -- "design" | "build" | "human"
    caused_by_friction_id UUID,           -- if revision caused by friction

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (session_id, version)
);

CREATE INDEX idx_design_rev_session ON design_revisions(session_id, version DESC);

-- ============================================================
-- DESIGN FRICTION
-- ============================================================
CREATE TABLE design_friction (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    slice_id        UUID,                 -- which slice surfaced it
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'acknowledged', 'resolved')),
    severity        TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    category        TEXT NOT NULL,        -- "testability", "coupling", "complexity",
                                          -- "duplication", "readability", "workaround"
    description     TEXT NOT NULL,
    code_location   TEXT,                 -- file:line
    friction_score  NUMERIC(5,2),
    resolved_by_revision_id UUID REFERENCES design_revisions(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX idx_friction_session ON design_friction(session_id, status);
CREATE INDEX idx_friction_category ON design_friction(category);

-- ============================================================
-- SLICES
-- ============================================================
CREATE TABLE slices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    name            TEXT NOT NULL,
    description     TEXT,
    slice_type      TEXT NOT NULL DEFAULT 'feature'
                    CHECK (slice_type IN ('skeleton', 'feature')),
    status          TEXT NOT NULL DEFAULT 'planned'
                    CHECK (status IN (
                        'planned', 'building', 'verifying', 'reviewing',
                        'done', 'failed'
                    )),
    order_index     INTEGER NOT NULL,
    design_version  INTEGER NOT NULL,     -- design version at time of build

    -- Quality metrics (from verification)
    test_coverage   NUMERIC(5,2),
    cyclomatic_complexity NUMERIC(5,2),
    coupling_score  NUMERIC(5,2),
    duplication_pct NUMERIC(5,2),

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_slices_session ON slices(session_id, order_index);

-- ============================================================
-- REQUIREMENTS
-- ============================================================
CREATE TABLE requirements (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    title           TEXT NOT NULL,
    description     TEXT,
    priority        TEXT NOT NULL DEFAULT 'medium'
                    CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'deferred', 'completed', 'removed')),
    jira_key        TEXT,                 -- synced Jira issue key
    queued_changes  JSONB,                -- pending changes (applied at loop boundary)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- ARTIFACTS (code files, design sections, etc.)
-- ============================================================
CREATE TABLE artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    slice_id        UUID REFERENCES slices(id),
    artifact_type   TEXT NOT NULL,        -- "code", "test", "config", "design_section"
    path            TEXT NOT NULL,        -- file path or section ID
    content_hash    TEXT NOT NULL,
    content_key     TEXT NOT NULL,        -- git ref or object key
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_artifacts_session ON artifacts(session_id);

-- ============================================================
-- REVIEWER RECORDS
-- ============================================================
CREATE TABLE reviewer_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    slice_id        UUID REFERENCES slices(id),
    design_version  INTEGER NOT NULL,

    -- Structured output (Pydantic schema → JSONB)
    rubric_scores   JSONB NOT NULL,       -- {criterion: {score, finding, evidence}}
    overall_score   NUMERIC(5,2) NOT NULL,
    passed          BOOLEAN NOT NULL,
    issues          JSONB NOT NULL DEFAULT '[]',

    model_used      TEXT NOT NULL,        -- different model from other agents
    prompt_hash     TEXT NOT NULL,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- VERIFICATION RESULTS
-- ============================================================
CREATE TABLE verification_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    slice_id        UUID REFERENCES slices(id),
    verification_type TEXT NOT NULL,      -- "build", "test", "lint", "all"

    passed          BOOLEAN NOT NULL,
    build_passed    BOOLEAN,
    test_passed     BOOLEAN,
    lint_passed     BOOLEAN,

    -- Raw outputs
    build_output    TEXT,
    test_output     TEXT,
    lint_output     TEXT,

    -- Metrics
    test_coverage   NUMERIC(5,2),
    tests_run       INTEGER,
    tests_passed    INTEGER,
    tests_failed    INTEGER,

    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- HUMAN DECISIONS
-- ============================================================
CREATE TABLE human_decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    gate_type       TEXT NOT NULL,        -- "design", "ship", "steering"
    action          TEXT NOT NULL,        -- "approve", "request_changes"
    feedback        TEXT,
    diff_snapshot   JSONB,
    expires_at      TIMESTAMPTZ NOT NULL,
    decided_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- AI FEEDBACK (append-only, for self-improvement — §8)
-- ============================================================
CREATE TABLE ai_feedback (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    loop            TEXT NOT NULL,
    agent           TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_hash     TEXT NOT NULL,
    tokens_in       INTEGER NOT NULL,
    tokens_out      INTEGER NOT NULL,
    latency_ms      INTEGER NOT NULL,
    cost_usd        NUMERIC(10,6) NOT NULL,
    reviewer_score  NUMERIC(5,2),
    friction_produced INTEGER NOT NULL DEFAULT 0,
    friction_resolved INTEGER NOT NULL DEFAULT 0,
    human_decision  TEXT,                 -- "approve" | "request_changes" | null
    human_corrected BOOLEAN NOT NULL DEFAULT false,
    correction_text TEXT,                 -- anonymized
    quality_signal  NUMERIC(5,2),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_feedback_agent ON ai_feedback(agent, created_at DESC);
CREATE INDEX idx_ai_feedback_session ON ai_feedback(session_id);

-- ============================================================
-- EVENT LOG (append-only, monotonic seq per session)
-- ============================================================
CREATE TABLE event_log (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES sessions(id),
    seq             INTEGER NOT NULL,     -- monotonic per session
    event_type      TEXT NOT NULL,
    agent           TEXT,
    loop            TEXT,
    data            JSONB NOT NULL DEFAULT '{}',
    trace_id        TEXT,
    span_id         TEXT,
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (session_id, seq)
);

CREATE INDEX idx_event_log_session_seq ON event_log(session_id, seq);
CREATE INDEX idx_event_log_type ON event_log(event_type);

-- ============================================================
-- BUG REPORTS
-- ============================================================
CREATE TABLE bug_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    severity        TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'triaged', 'fixed', 'wontfix')),
    friction_id     UUID REFERENCES design_friction(id), -- bugs often → friction
    jira_key        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- TEST SCENARIOS
-- ============================================================
CREATE TABLE test_scenarios (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    scenario_type   TEXT NOT NULL DEFAULT 'functional'
                    CHECK (scenario_type IN ('functional', 'edge_case', 'regression', 'ux')),
    status          TEXT NOT NULL DEFAULT 'proposed'
                    CHECK (status IN ('proposed', 'accepted', 'implemented', 'deprecated')),
    slice_id        UUID REFERENCES slices(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- ATTACHMENTS (images, screenshots for requirements/bugs/etc.)
-- ============================================================
CREATE TABLE attachments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    parent_type     TEXT NOT NULL,        -- "requirement", "bug_report", "test_scenario", "design"
    parent_id       UUID NOT NULL,
    filename        TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    storage_key     TEXT NOT NULL,        -- object storage key
    size_bytes      INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_attachments_parent ON attachments(parent_type, parent_id);
```

### 3.2 State Projection

The graph state is **never** the database. It is a thin read-projection assembled per-node:

```python
# studio/db/projection.py

async def project_state(session_id: UUID, db: AsyncSession) -> GraphState:
    """Build the thin GraphState from normalized DB tables."""
    session = await db.get(Session, session_id)
    if session is None:
        raise SessionNotFound(session_id)

    # Get latest design digest (≤500 tokens)
    latest_design = await db.execute(
        select(DesignRevision)
        .where(DesignRevision.session_id == session_id)
        .order_by(DesignRevision.version.desc())
        .limit(1)
    )
    design = latest_design.scalar_one_or_none()

    # Get open friction items (IDs only)
    friction_ids = await db.execute(
        select(DesignFriction.id)
        .where(DesignFriction.session_id == session_id)
        .where(DesignFriction.status == 'open')
    )

    # Get remaining slices
    remaining = await db.execute(
        select(Slice.id)
        .where(Slice.session_id == session_id)
        .where(Slice.status.in_(['planned', 'building']))
        .order_by(Slice.order_index)
    )

    return GraphState(
        session_id=session.id,
        session_version=session.version,
        design_digest=design.digest if design else "",
        design_version=design.version if design else 0,
        design_section_ids=[s["id"] for s in (design.section_index if design else [])],
        current_loop=session.current_loop,
        current_node=session.current_node,
        iteration=session.iteration,
        tokens_used=session.tokens_used,
        cost_usd=float(session.cost_usd),
        token_budget=session.token_budget,
        cost_budget=float(session.cost_budget),
        pending_friction_items=[r.id for r in friction_ids.scalars()],
        remaining_slices=[r.id for r in remaining.scalars()],
        config=session.config,
        trace_id=session.trace_id,
    )
```

---

## 4. Agent Specifications

### 4.1 Design Agent

**Role:** Owns and iterates the living design artifact. Works at design altitude — interfaces, boundaries, data model, flows, contracts. Concrete enough to critique, abstract enough not to be implementation.

**Responsibilities:**
- Create initial design from requirements (module boundaries, interfaces as Protocols, data model, UX flows, customer journey, decision log)
- Apply SOLID principles, plan dependency injection points
- Maintain STRIDE threat model section
- Maintain i18n/RTL plan (Hebrew bidi, plural forms, font stack)
- Maintain privacy data inventory (what PII, where, why, retention, encryption, erasure path)
- Process design friction reports from Build agent → revise design
- Process UX feedback → revise design
- Process human feedback from gates → revise design
- Every revision: update content hash, bump version, write reason + cause

**Input Contract:**
```python
@dataclass
class DesignAgentInput:
    design_digest: str                    # ≤500 tokens
    relevant_section_ids: list[str]       # fetched on demand
    trigger: str                          # "initial" | "friction" | "ux_feedback" | "human_feedback" | "skeleton_fail"
    friction_items: list[FrictionItem]    # if trigger == "friction"
    ux_feedback: Optional[str]            # if trigger == "ux_feedback"
    human_feedback: Optional[str]         # if trigger == "human_feedback"
    requirements: list[Requirement]
    iteration: int
    budget_remaining: BudgetInfo
```

**Output Contract:**
```python
@dataclass
class DesignAgentOutput:
    revised_design: DesignContent         # full updated design
    digest: str                           # ≤500 token summary
    revision_reason: str
    sections_changed: list[str]           # section IDs
    decisions_added: list[ArchDecision]   # ADR entries
    open_questions: list[str]
    tokens_used: int
    cost_usd: float
```

**Model:** Primary model (Claude Sonnet 4 via Max, or configured provider/model).

### 4.2 UX/Customer Agent

**Role:** The user's voice. Always on, never skipped. Reviews design AND every built slice from the customer's perspective. Even APIs/CLIs have users.

**Responsibilities:**
- Review design for customer journey completeness, simplicity, discoverability
- Define the experience metric (per-project: e.g., "task completion in ≤3 steps", "API call succeeds with ≤2 reads of docs")
- Review each built slice against the experience metric
- Flag UX issues: confusing flows, inconsistent patterns, accessibility gaps, missing error states, i18n/RTL problems
- Provide the "is this the simplest possible thing for the user?" check

**Input Contract:**
```python
@dataclass
class UXAgentInput:
    design_digest: str
    customer_journey_section_id: str      # fetched on demand
    context: str                          # "design_review" | "slice_review"
    slice_artifacts: Optional[list[str]]  # if reviewing a built slice
    experience_metric: ExperienceMetric
    prior_ux_issues: list[UXIssue]
    iteration: int
```

**Output Contract:**
```python
@dataclass
class UXAgentOutput:
    experience_score: float               # 0-10
    issues: list[UXIssue]                 # each with severity, description, suggestion
    journey_complete: bool
    simplicity_assessment: str
    needs_design_revision: bool
    revision_suggestions: list[str]
    tokens_used: int
    cost_usd: float
```

**Model:** Primary model (same as Design agent).

### 4.3 Build Agent

**Role:** Builds software in thin slices via the configurable coding agent. Strict TDD. Equally important: reports design friction upstream.

**Responsibilities:**
- Build the walking skeleton first (one thin vertical slice: UI/CLI → logic → data → back)
- Build feature slices in TDD: Red (write failing test) → Green (minimal implementation) → Refactor
- Use the configurable coding agent (default: Claude Code) for actual code generation
- **Detect and report design friction:** when code is hard to test, coupled, full of workarounds, or ugly → emit `design_friction` event, do NOT patch locally
- Measure and report: test coverage, cyclomatic complexity, coupling, duplication
- Commit to git with meaningful messages after each passing slice

**Input Contract:**
```python
@dataclass
class BuildAgentInput:
    design_digest: str
    relevant_design_sections: list[str]   # fetched by ID
    slice: SliceSpec                       # what to build
    slice_type: str                        # "skeleton" | "feature"
    project_path: str                      # path to project volume
    coding_agent: str                      # "claude_code" | "aider" | etc.
    tdd_strict: bool                       # always True
    iteration: int
```

**Output Contract:**
```python
@dataclass
class BuildAgentOutput:
    files_changed: list[FileChange]
    tests_written: list[str]              # test file paths
    friction_items: list[FrictionReport]  # THE KEY MECHANISM
    git_commit_hash: Optional[str]
    metrics: CodeQualityMetrics           # coverage, complexity, coupling, duplication
    tokens_used: int
    cost_usd: float

@dataclass
class FrictionReport:
    severity: str                          # "low" | "medium" | "high" | "critical"
    category: str                          # "testability" | "coupling" | "complexity" | "duplication" | "readability" | "workaround"
    description: str
    code_location: str                     # file:line
    friction_score: float                  # 0-10
    suggested_design_change: str           # what the Build agent thinks should change
```

**Model:** Primary model for orchestration; coding agent (Claude Code) for actual code generation.

### 4.4 Reviewer Agent

**Role:** Validates design + code against a rubric, but ONLY after deterministic checks pass. Anchored to verifiable findings, not opinion. Uses a different model.

**Responsibilities:**
- Only runs AFTER verification (build/test/lint) passes — never reviews unverified code
- Evaluates against a structured rubric (Pydantic schema, via tool-calling / structured output)
- Checks: design adherence, test quality (not just coverage), security (STRIDE alignment), i18n readiness, API contract consistency, error handling, naming/readability
- Every finding must cite specific evidence (file, line, code snippet)
- Produces pass/fail + scored rubric

**Input Contract:**
```python
@dataclass
class ReviewerInput:
    design_digest: str
    relevant_design_sections: list[str]
    slice: SliceSpec
    verification_result: VerificationResult  # must be passing
    code_artifacts: list[str]              # file paths
    test_artifacts: list[str]
```

**Output Contract (Pydantic — structured output, no prompt-and-parse):**
```python
from pydantic import BaseModel

class RubricScore(BaseModel):
    criterion: str
    score: float          # 0-10
    finding: str          # what was found
    evidence: str         # file:line or specific reference
    severity: str         # "info" | "warning" | "error"

class ReviewerOutput(BaseModel):
    rubric_scores: list[RubricScore]
    overall_score: float  # weighted average
    passed: bool          # overall_score >= threshold
    issues: list[str]     # actionable issues
    tokens_used: int
    cost_usd: float
```

**Model:** Different from other agents (e.g., if others use Claude Sonnet, Reviewer uses GPT-4o or Claude Opus, or vice versa). Configurable.

### 4.5 Design Friction Reporting Contract

This is the key mechanism (§4 of the spec). It must be concrete and observable:

```python
# studio/friction/contract.py

@dataclass
class DesignFrictionEvent:
    """Structured event emitted by Build agent when code quality
    signals a design defect."""
    session_id: UUID
    slice_id: UUID
    severity: Literal["low", "medium", "high", "critical"]
    category: Literal[
        "testability",    # hard to write tests for
        "coupling",       # modules too intertwined
        "complexity",     # cyclomatic complexity too high
        "duplication",    # repeated patterns that should be abstracted
        "readability",    # code is unclear despite correct logic
        "workaround",     # code works around a design limitation
    ]
    description: str      # what the friction is
    code_location: str    # file:line
    friction_score: float # 0-10, computed from metrics
    suggested_design_change: str
    metrics_snapshot: CodeQualityMetrics

# Flow:
# 1. Build agent detects friction → emits DesignFrictionEvent
# 2. Event persisted to design_friction table (status: "open")
# 3. Event logged to event_log as "design_friction.reported"
# 4. GraphState.pending_friction_items updated
# 5. Conditional edge routes to Design agent
# 6. Design agent receives friction items, revises design
# 7. On revision: friction item status → "resolved", linked to revision ID
# 8. Metrics emitted to Prometheus (counter by category, gauge of open items)
# 9. Dashboard shows friction over time, resolution rate, category breakdown
```

### 4.6 Reviewer Deterministic-Anchor Checks

The Reviewer only runs after these deterministic checks pass in the Verify node:

```python
# studio/verification/checks.py

DETERMINISTIC_CHECKS = [
    "build_succeeds",         # project compiles / no syntax errors
    "all_tests_pass",         # test suite green
    "coverage_gate",          # ≥80% line coverage
    "lint_clean",             # linter produces zero errors (warnings OK)
    "no_secrets_in_code",     # grep for API keys, passwords, tokens
    "no_pii_in_logs",         # grep log statements for email/phone/SSN patterns
    "type_check_passes",      # mypy / tsc strict
]

# These run in the verification sandbox.
# If ANY fails, the result routes back to Build agent (not Reviewer).
# Reviewer never sees unverified code.
```

---

## 5. Living Design Artifact Schema

### 5.1 Design Content Structure

```python
# studio/design/schema.py

from pydantic import BaseModel
from datetime import datetime

class DesignSection(BaseModel):
    id: str                    # stable ID (e.g., "modules", "data_model", "ux_flows")
    title: str
    content: str               # markdown
    content_hash: str          # SHA-256

class ModuleBoundary(BaseModel):
    name: str
    responsibility: str
    interfaces: list[str]      # Protocol / interface definitions
    dependencies: list[str]    # what it depends on
    injection_points: list[str]

class DataEntity(BaseModel):
    name: str
    fields: list[dict]         # {name, type, nullable, pii, description}
    relationships: list[str]
    privacy_classification: str # "public" | "internal" | "sensitive" | "pii"

class UXFlow(BaseModel):
    name: str
    steps: list[str]
    entry_point: str
    success_criteria: str
    error_states: list[str]
    i18n_considerations: list[str]

class ArchitectureDecision(BaseModel):
    id: str                    # ADR-001
    title: str
    context: str
    decision: str
    rationale: str
    consequences: list[str]
    status: str                # "proposed" | "accepted" | "superseded"
    date: datetime

class ThreatModelEntry(BaseModel):
    threat_type: str           # S/T/R/I/D/E
    description: str
    component: str
    mitigation: str
    status: str

class PrivacyDataItem(BaseModel):
    data_element: str
    classification: str
    purpose: str
    retention: str
    encryption: str
    erasure_path: str

class LivingDesign(BaseModel):
    """The complete living design artifact."""
    version: int
    content_hash: str

    # Core sections
    modules: list[ModuleBoundary]
    data_model: list[DataEntity]
    ux_flows: list[UXFlow]
    customer_journey: str               # markdown
    experience_metric: dict             # {name, definition, target, measurement}

    # Cross-cutting
    architecture_decisions: list[ArchitectureDecision]
    threat_model: list[ThreatModelEntry]
    privacy_inventory: list[PrivacyDataItem]
    i18n_plan: dict                     # {framework, locales, rtl_strategy, hebrew_specifics}

    # Health
    open_questions: list[str]
    known_friction: list[str]           # links to friction IDs

    # Sections index (for selective fetch)
    sections: list[DesignSection]
```

### 5.2 Revision & Diff Model

```python
# studio/design/revision.py

import hashlib
import difflib
from datetime import datetime

class DesignRevisionModel:
    """Handles versioning, hashing, and diffing of the living design."""

    @staticmethod
    def compute_hash(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def create_revision(
        session_id: UUID,
        previous: Optional[LivingDesign],
        updated: LivingDesign,
        reason: str,
        caused_by: str,
    ) -> DesignRevision:
        new_version = (previous.version + 1) if previous else 1
        content_str = updated.model_dump_json()

        return DesignRevision(
            session_id=session_id,
            version=new_version,
            content_hash=DesignRevisionModel.compute_hash(content_str),
            content_key=f"designs/{session_id}/v{new_version}.json",
            digest=DesignRevisionModel.generate_digest(updated),
            section_index=[
                {"id": s.id, "title": s.title, "hash": s.content_hash}
                for s in updated.sections
            ],
            reason=reason,
            caused_by_agent=caused_by,
        )

    @staticmethod
    def generate_digest(design: LivingDesign) -> str:
        """Generate ≤500 token summary of current design state."""
        modules = ", ".join(m.name for m in design.modules)
        entities = ", ".join(e.name for e in design.data_model)
        flows = ", ".join(f.name for f in design.ux_flows)
        friction = len(design.known_friction)
        questions = len(design.open_questions)

        return (
            f"Design v{design.version} | "
            f"Modules: {modules} | "
            f"Data: {entities} | "
            f"Flows: {flows} | "
            f"Metric: {design.experience_metric.get('name', 'TBD')} | "
            f"Decisions: {len(design.architecture_decisions)} | "
            f"Open friction: {friction} | "
            f"Open questions: {questions}"
        )

    @staticmethod
    def diff(old: LivingDesign, new: LivingDesign) -> dict:
        """Compute structured diff between two design versions."""
        old_json = old.model_dump_json(indent=2)
        new_json = new.model_dump_json(indent=2)

        unified = list(difflib.unified_diff(
            old_json.splitlines(),
            new_json.splitlines(),
            fromfile=f"v{old.version}",
            tofile=f"v{new.version}",
            lineterm="",
        ))

        # Section-level diff
        old_sections = {s.id: s for s in old.sections}
        new_sections = {s.id: s for s in new.sections}
        changed = [
            sid for sid in new_sections
            if sid in old_sections and old_sections[sid].content_hash != new_sections[sid].content_hash
        ]
        added = [sid for sid in new_sections if sid not in old_sections]
        removed = [sid for sid in old_sections if sid not in new_sections]

        return {
            "from_version": old.version,
            "to_version": new.version,
            "unified_diff": "\n".join(unified),
            "sections_changed": changed,
            "sections_added": added,
            "sections_removed": removed,
            "decisions_added": [
                d for d in new.architecture_decisions
                if d.id not in {dd.id for dd in old.architecture_decisions}
            ],
        }
```

---

## 6. API Surface

### 6.1 REST Endpoints

All REST endpoints (except health/metrics) gated by `rest_api_enabled` config — return 503 when off.

```
# Health (always on, not behind gate)
GET  /health                              → {"status": "ok"}
GET  /ready                               → {"status": "ready", "db": true, "redis": true}
GET  /metrics                             → Prometheus text format

# Sessions
POST   /api/sessions                      → Create session
GET    /api/sessions                      → List sessions
GET    /api/sessions/{id}                 → Get session detail
POST   /api/sessions/{id}/run             → Start/resume session
POST   /api/sessions/{id}/pause           → Pause session
POST   /api/sessions/{id}/stop            → Stop session
POST   /api/sessions/{id}/resume          → Resume from pause
POST   /api/sessions/{id}/restart-from    → Restart from checkpoint {body: {node}}
GET    /api/sessions/{id}/export          → Export artifacts (zip)
POST   /api/sessions/{id}/load            → Load saved state
GET    /api/sessions/{id}/events          → Event replay (query: since=seq)

# Living Design
GET    /api/sessions/{id}/design          → Current design
GET    /api/sessions/{id}/design/history  → Revision history
GET    /api/sessions/{id}/design/diff     → Diff between versions (query: from=, to=)
GET    /api/sessions/{id}/design/sections/{section_id} → Fetch section by ID

# Design Friction
GET    /api/sessions/{id}/friction        → List friction items (query: status=)
GET    /api/sessions/{id}/friction/{fid}  → Friction detail

# Requirements
POST   /api/sessions/{id}/requirements    → Add requirement
GET    /api/sessions/{id}/requirements    → List requirements
PUT    /api/sessions/{id}/requirements/{rid} → Update requirement
DELETE /api/sessions/{id}/requirements/{rid} → Remove requirement

# Bug Reports
POST   /api/sessions/{id}/bugs            → Report bug
GET    /api/sessions/{id}/bugs            → List bugs
PUT    /api/sessions/{id}/bugs/{bid}      → Update bug
GET    /api/sessions/{id}/bugs/{bid}      → Bug detail

# Test Scenarios
POST   /api/sessions/{id}/tests           → Add test scenario
GET    /api/sessions/{id}/tests           → List test scenarios
PUT    /api/sessions/{id}/tests/{tid}     → Update test scenario

# Human Gates
POST   /api/sessions/{id}/approve         → Approve gate {body: {gate_type}}
POST   /api/sessions/{id}/reject          → Reject gate {body: {gate_type, feedback}}

# Git
GET    /api/sessions/{id}/git/log         → Git log
POST   /api/sessions/{id}/git/commit      → Manual commit
POST   /api/sessions/{id}/git/push        → Push to remote

# AI Improvement (§8)
GET    /api/ai/health                     → AI health summary
GET    /api/ai/feedback                   → AI feedback records (query: agent=, since=)
GET    /api/ai/suggestions                → Pending prompt improvement suggestions
POST   /api/ai/suggestions/{sid}/apply    → Apply a suggestion (human-approved)

# Config
GET    /api/config                        → Current config
PUT    /api/config                        → Update config

# Attachments
POST   /api/sessions/{id}/attachments     → Upload attachment (multipart)
GET    /api/attachments/{aid}             → Download attachment

# WebSocket
WS     /ws/{session_id}?last_seq=N        → Live event stream (reconnect-safe)
```

### 6.2 WebSocket Events

```typescript
// All events follow this envelope:
interface WSEvent {
  session_id: string;
  seq: number;               // monotonic per session
  event_type: string;
  agent?: string;
  loop?: string;
  data: Record<string, any>;
  trace_id?: string;
  span_id?: string;
  timestamp: string;
}

// Event types (from §7 mandatory events):
type EventType =
  | "agent.started" | "agent.completed"
  | "agent.llm_call" | "agent.llm_response"
  | "agent.token_stream"           // live streaming chunks
  | "design.revised"               // with reason
  | "design_friction.reported"     // with severity, category
  | "skeleton.validated"
  | "slice.started" | "slice.built" | "slice.verified"
  | "verification.result"          // build/test/lint pass-fail
  | "reviewer.evaluated"
  | "human.checkpoint"             // gate triggered
  | "human.decision"               // gate resolved
  | "requirement.changed"
  | "jira.synced"
  | "git.committed"
  | "session.created" | "session.completed" | "session.error"
  | "session.budget_warning"       // at 80% of budget
  | "ai.feedback_recorded"
  | "ai.suggestion_created";
```

### 6.3 CLI Commands (Full Parity)

```bash
# All commands support --json for machine-readable output

# Sessions
studio session new --name "My Project" --requirements requirements.md
studio session list [--status running|paused|completed]
studio session status <session-id>
studio session run <session-id>
studio session pause <session-id>
studio session stop <session-id>
studio session resume <session-id>
studio session export <session-id> [--output ./artifacts]
studio session load <session-id> --state state.json
studio session restart-from <session-id> --node design_agent

# Living Design
studio design show <session-id>
studio design history <session-id>
studio design diff <session-id> --from 1 --to 3

# Friction
studio friction list <session-id> [--status open|resolved]

# Requirements
studio requirements add <session-id> --title "..." --description "..."
studio requirements list <session-id>
studio requirements update <session-id> <req-id> --title "..."
studio requirements remove <session-id> <req-id>

# Bugs
studio bugs report <session-id> --title "..." --severity high
studio bugs list <session-id>
studio bugs update <session-id> <bug-id> --status fixed

# Tests
studio tests add <session-id> --name "..." --type functional
studio tests list <session-id>

# Human gates (for CI automation)
studio approve <session-id> --gate design
studio reject <session-id> --gate design --feedback "..."

# Git
studio git log <session-id>
studio git commit <session-id> --message "..."
studio git push <session-id>

# Config
studio config show
studio config set llm_provider anthropic
studio config set coding_agent claude_code
studio config set rest_api_enabled true

# AI Health
studio ai-health [--agent design]

# Watch (live event stream)
studio watch <session-id>

# Colored output via rich; --json disables colors and outputs JSON
```

---

## 7. Observability Plan

### 7.1 Structured Logging

```python
# studio/observability/logging.py

import structlog

def configure_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            pii_masker,           # custom: mask emails, phones, SSNs
            secret_masker,        # custom: mask API keys, tokens
            prompt_body_filter,   # custom: only in DEBUG + behind flag
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
    )

# Every log entry includes:
# - timestamp (ISO 8601)
# - level (info, warning, error, debug)
# - service ("studio-backend" | "studio-worker")
# - session_id
# - loop ("design_ux" | "design_build" | "build_verify")
# - agent ("design" | "ux" | "build" | "reviewer")
# - event (the event name)
# - duration_ms
# - iteration
# - trace_id
# - span_id
# - data (structured payload, PII-free)
```

### 7.2 Mandatory Events

```python
MANDATORY_EVENTS = {
    # Agent lifecycle
    "agent.started":            {"agent", "loop", "iteration"},
    "agent.completed":          {"agent", "loop", "iteration", "duration_ms", "tokens_used"},
    "agent.llm_call":           {"agent", "model", "prompt_hash", "tokens_in"},
    "agent.llm_response":       {"agent", "model", "tokens_out", "latency_ms", "cost_usd"},

    # Design
    "design.revised":           {"version", "reason", "caused_by", "sections_changed"},
    "design_friction.reported": {"severity", "category", "description", "friction_score", "slice_id"},

    # Skeleton
    "skeleton.validated":       {"passed", "duration_ms"},

    # Slices
    "slice.started":            {"slice_id", "slice_name", "slice_type"},
    "slice.built":              {"slice_id", "files_changed", "tests_written", "friction_count"},
    "slice.verified":           {"slice_id", "passed", "coverage", "complexity"},

    # Verification
    "verification.result":      {"build_passed", "test_passed", "lint_passed", "duration_ms"},

    # Reviewer
    "reviewer.evaluated":       {"overall_score", "passed", "issues_count", "model_used"},

    # Human
    "human.checkpoint":         {"gate_type", "expires_at"},
    "human.decision":           {"gate_type", "action", "has_feedback"},

    # External
    "requirement.changed":      {"requirement_id", "change_type"},
    "jira.synced":              {"jira_key", "sync_type"},
    "git.committed":            {"commit_hash", "files_changed"},

    # Session
    "session.created":          {"session_name"},
    "session.completed":        {"total_duration_ms", "total_cost_usd", "total_tokens"},
    "session.error":            {"error_type", "error_message"},

    # AI-native
    "ai.feedback_recorded":     {"agent", "quality_signal"},
    "ai.suggestion_created":    {"agent", "suggestion_type"},
}
```

### 7.3 Metrics (Prometheus)

```python
# studio/observability/metrics.py
from prometheus_client import Counter, Histogram, Gauge

# Counters
sessions_total = Counter("studio_sessions_total", "Total sessions", ["status"])
llm_calls_total = Counter("studio_llm_calls_total", "LLM calls", ["agent", "model"])
design_revisions_total = Counter("studio_design_revisions_total", "Design revisions", ["caused_by"])
design_friction_total = Counter("studio_design_friction_total", "Friction items", ["category", "severity"])
slices_built_total = Counter("studio_slices_built_total", "Slices built", ["type"])
verification_failures_total = Counter("studio_verification_failures_total", "Verification failures", ["check"])
human_decisions_total = Counter("studio_human_decisions_total", "Human decisions", ["gate_type", "action"])

# Histograms
loop_duration_seconds = Histogram("studio_loop_duration_seconds", "Loop duration", ["loop"])
llm_latency_seconds = Histogram("studio_llm_latency_seconds", "LLM latency", ["agent", "model"])
reviewer_score = Histogram("studio_reviewer_score", "Reviewer scores", ["agent"])
code_quality_score = Histogram("studio_code_quality_score", "Code quality", ["metric"])
design_friction_score = Histogram("studio_design_friction_score", "Friction scores", ["category"])
session_cost_usd = Histogram("studio_session_cost_usd", "Session cost USD")
tokens_per_loop = Histogram("studio_tokens_per_loop", "Tokens per loop", ["loop"])

# Gauges
active_sessions = Gauge("studio_active_sessions", "Active sessions")
sessions_awaiting_human = Gauge("studio_sessions_awaiting_human", "Sessions awaiting human")
open_friction_items = Gauge("studio_open_friction_items", "Open friction items")
backlog_size = Gauge("studio_backlog_size", "Remaining slices")
```

### 7.4 Traces (OpenTelemetry)

```python
# studio/observability/tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.jaeger.thrift import JaegerExporter

tracer = trace.get_tracer("studio")

# Span hierarchy:
# session (root)
#   └─ loop_iteration (one per loop pass)
#       ├─ llm_call (per LLM invocation)
#       ├─ verification_run (build/test/lint)
#       └─ design_revision (if revision occurs)

# Trace context propagated via:
# - GraphState.trace_id / span_id
# - HTTP headers (for REST API calls)
# - WebSocket message metadata
# - Event log entries
```

### 7.5 Dashboards (Grafana, provisioned on startup)

**Dashboard 1: Session Overview**
- Active sessions (gauge)
- Session status breakdown (pie)
- Sessions awaiting human input
- Session cost over time

**Dashboard 2: Loop Activity**
- Loop iterations per session (time series)
- Loop duration distribution (histogram)
- Node execution frequency (bar)
- Current loop/node per active session (table)

**Dashboard 3: Design Health** ← The key dashboard
- Open friction items over time (should trend down)
- Friction by category (stacked area)
- Code quality trend (coverage, complexity, coupling — should improve)
- Design revision frequency (should stabilize)
- Friction resolution rate
- "Is the codebase getting simpler?" metric

**Dashboard 4: LLM Cost**
- Cost by agent (stacked bar)
- Tokens in/out by agent (time series)
- Cost per slice (histogram)
- Budget utilization gauge
- Model usage breakdown

**Dashboard 5: Customer Experience**
- Experience metric score over time (should improve)
- UX issues found per slice
- Journey completeness trend
- Experience score vs design revision correlation

**Dashboard 6: AI Health** (§8)
- Per-agent prompt version and score over time
- First-pass approval rate
- Human correction rate
- Cost efficiency (score / cost)
- Model comparison (shadow mode results)
- Regression alerts

### 7.6 Observability Stack (Docker Compose)

```yaml
# In docker-compose.yml
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./observability/prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    volumes:
      - ./observability/grafana/provisioning:/etc/grafana/provisioning
      - ./observability/grafana/dashboards:/var/lib/grafana/dashboards
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_AUTH_ANONYMOUS_ENABLED=true

  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"   # UI
      - "6831:6831/udp" # agent

  loki:
    image: grafana/loki:latest
    ports:
      - "3100:3100"

  promtail:
    image: grafana/promtail:latest
    volumes:
      - /var/log:/var/log
      - ./observability/promtail.yml:/etc/promtail/config.yml
```

---

## 8. AI-Native Plan

### 8.1 AIFeedbackRecord

Every loop iteration writes one record (append-only):

```python
# studio/ai/feedback.py

@dataclass
class AIFeedbackRecord:
    session_id: UUID
    loop: str               # "design_ux" | "design_build" | "build_verify"
    agent: str              # "design" | "ux" | "build" | "reviewer"
    model: str              # "claude-sonnet-4-20250514" etc.
    prompt_hash: str        # SHA-256 of the prompt template
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float
    reviewer_score: Optional[float]
    friction_produced: int  # friction items this iteration created
    friction_resolved: int  # friction items resolved by this iteration's revision
    human_decision: Optional[str]  # "approve" | "request_changes"
    human_corrected: bool
    correction_text: Optional[str]  # anonymized (no PII)
    quality_signal: Optional[float] # composite quality score
```

### 8.2 Prompt Versioning

```
prompts/
├── design_agent/
│   ├── system.md          # v1.0.0 — system prompt
│   ├── initial_design.md  # v1.0.0 — initial design task
│   ├── friction_revision.md  # v1.0.0 — revision from friction
│   └── metadata.json      # {version, hash, last_updated, author}
├── ux_agent/
│   ├── system.md
│   ├── design_review.md
│   ├── slice_review.md
│   └── metadata.json
├── build_agent/
│   ├── system.md
│   ├── skeleton.md
│   ├── feature_slice.md
│   ├── friction_detection.md
│   └── metadata.json
└── reviewer/
    ├── system.md
    ├── review_rubric.md
    └── metadata.json
```

Each prompt file:
- Content-hashed (SHA-256) on load
- Hot-reloadable in staging (file watcher)
- Versioned in git with semantic commit messages
- Loaded at runtime, not embedded in code
- A domain expert edits the markdown, not Python

### 8.3 Improvement Worker

```python
# studio/ai/improvement_worker.py

class ImprovementWorker:
    """Runs on configurable interval (default: daily).
    Analyzes AIFeedbackRecords to find underperforming agents/prompts."""

    async def run(self):
        # 1. Query ai_feedback for agents with:
        #    - Low reviewer scores (< threshold)
        #    - High friction production (> threshold)
        #    - High human correction rate (> threshold)
        underperformers = await self.find_underperformers()

        for agent_name, metrics in underperformers.items():
            # 2. Collect human correction samples
            corrections = await self.get_correction_samples(agent_name, limit=10)

            # 3. Call improvement LLM with:
            #    - Current prompt
            #    - Performance metrics
            #    - Human corrections
            #    - Request: specific prompt edit suggestions
            suggestion = await self.generate_suggestion(
                agent_name, metrics, corrections
            )

            # 4. Write suggestion to DB
            await self.save_suggestion(suggestion)

            # 5. Open Jira ticket for human review
            await self.create_jira_ticket(suggestion)

            # 6. Emit event
            await emit_event("ai.suggestion_created", {
                "agent": agent_name,
                "suggestion_type": suggestion.type,
                "current_score": metrics.avg_score,
            })
```

### 8.4 Shadow Mode

```python
# studio/ai/shadow.py

class ShadowRunner:
    """Runs a candidate model alongside the active model.
    Output discarded, but AIFeedbackRecord captured for comparison."""

    async def run_shadow(
        self,
        active_model: str,
        candidate_model: str,
        prompt: str,
        input_data: dict,
    ) -> AIFeedbackRecord:
        # Run candidate in background (fire-and-forget, with timeout)
        shadow_response = await asyncio.wait_for(
            self.call_model(candidate_model, prompt, input_data),
            timeout=60,
        )

        # Score the shadow output using the Reviewer (offline)
        shadow_score = await self.offline_review(shadow_response)

        # Record for comparison
        return AIFeedbackRecord(
            model=candidate_model,
            quality_signal=shadow_score,
            # ... other fields
        )
```

### 8.5 Determinism for Replay

```python
# studio/ai/determinism.py

@dataclass
class RunConfig:
    """Pinned per session for reproducibility."""
    model_version: str        # exact model string
    prompt_hashes: dict       # {agent: prompt_hash}
    seed: int                 # for models that support seed
    temperature: float        # pinned (typically 0 for determinism)
    max_tokens: int

# Every LLM call logs: model_version, prompt_hash, seed, temperature
# Replay: load RunConfig, re-run with same inputs → same outputs (best-effort)
```

---

## 9. Token Efficiency & Prompt Caching

### 9.1 Prompt Structure (per agent call)

```
┌─────────────────────────────────────────┐
│  STATIC PREFIX (cacheable)              │ ← cache breakpoint here
│  ┌─────────────────────────────────────┐│
│  │ System prompt (≤1.5K tokens)        ││
│  │ - Identity, role, output contract   ││
│  │ - Core principles (stable)          ││
│  └─────────────────────────────────────┘│
├─────────────────────────────────────────┤
│  DYNAMIC SECTION                        │
│  ┌─────────────────────────────────────┐│
│  │ Design digest (≤500 tokens)         ││
│  │ Fetched sections (by ID, on demand) ││
│  │ Loop-specific context (delta only)  ││
│  │ - Prior output summary              ││
│  │ - Reviewer/friction feedback        ││
│  │ - Human feedback (if any)           ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘

Target: ≤8K tokens typical, 20K hard cap → summarize above it
```

### 9.2 Caching Strategy

```python
# studio/ai/caching.py

class PromptCacheManager:
    """Manages prompt caching for Anthropic API."""

    def build_messages(
        self,
        system_prompt: str,        # stable → cached
        design_digest: str,        # changes per revision
        sections: list[str],       # fetched by ID
        task_context: str,         # loop-specific delta
    ) -> list[dict]:
        return [
            {
                "role": "system",
                "content": system_prompt,
                # Anthropic cache_control on the system message
                "cache_control": {"type": "ephemeral"},
            },
            {
                "role": "user",
                "content": self.assemble_context(
                    design_digest, sections, task_context
                ),
            },
        ]

    def assemble_context(self, digest, sections, task) -> str:
        """Assemble ≤8K token context. Summarize if over 20K."""
        context = f"## Design State\n{digest}\n\n"

        for section in sections:
            context += f"## {section.title}\n{section.content}\n\n"

        context += f"## Task\n{task}\n"

        tokens = estimate_tokens(context)
        if tokens > 20000:
            context = self.summarize(context, target=8000)

        return context
```

### 9.3 Delta-Only Loop Iterations

```python
# Instead of re-sending the full context each iteration:
# 1. System prompt → cached (never re-sent in full)
# 2. Design digest → only updated when design version changes
# 3. Task context → only the delta:
#    - What changed since last iteration
#    - Reviewer feedback (if any)
#    - Friction items (if any, just the new ones)
#    - Human feedback (if any)
```

### 9.4 Budget Enforcement

```python
# studio/ai/budget.py

class BudgetEnforcer:
    """Hard stop when budget exceeded."""

    async def check(self, state: GraphState) -> bool:
        if state.tokens_used >= state.token_budget:
            await emit_event("session.budget_warning", {
                "type": "token_budget_exceeded",
                "used": state.tokens_used,
                "budget": state.token_budget,
            })
            return False  # stop

        if state.cost_usd >= state.cost_budget:
            await emit_event("session.budget_warning", {
                "type": "cost_budget_exceeded",
                "used": state.cost_usd,
                "budget": state.cost_budget,
            })
            return False  # stop

        # Warning at 80%
        if state.tokens_used >= state.token_budget * 0.8:
            await emit_event("session.budget_warning", {
                "type": "approaching_token_limit",
            })

        return True  # continue
```

---

## 10. CI/CD Pipeline & Environments

### 10.1 Three Environments

| Environment | Purpose | Deploy | Config |
|---|---|---|---|
| **local** | Dev on laptop | `docker compose up` | `.env.local` |
| **staging** | Pre-prod, hot-reload prompts, shadow mode | Auto on `main` merge | `.env.staging` |
| **prod** | Production | Manual promote from staging | `.env.prod`, Docker secrets |

### 10.2 Pipeline (GitHub Actions)

```yaml
# .github/workflows/ci.yml
name: CI/CD

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install ruff mypy
      - run: ruff check .
      - run: mypy studio/ --strict

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: studio_test
          POSTGRES_PASSWORD: test
      redis:
        image: redis:7
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[test]"
      - run: pytest --cov=studio --cov-report=xml -v
      - run: |  # Coverage gate
          coverage=$(python -c "import xml.etree.ElementTree as ET; print(ET.parse('coverage.xml').getroot().attrib['line-rate'])")
          python -c "assert float('$coverage') >= 0.80, f'Coverage {coverage} < 80%'"

  contract-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pytest tests/contracts/ -v
      # Tests: design schema ↔ agent I/O, digest format, friction schema

  build-images:
    needs: [lint, test, contract-tests]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose build

  health-check:
    needs: build-images
    runs-on: ubuntu-latest
    steps:
      - run: docker compose up -d
      - run: |
          sleep 10
          curl -f http://localhost:8000/health
          curl -f http://localhost:8000/ready
          curl -f http://localhost:8000/metrics
          curl -f http://localhost:3000  # Grafana
      - run: docker compose down

  deploy-staging:
    if: github.ref == 'refs/heads/main'
    needs: health-check
    runs-on: ubuntu-latest
    steps:
      - run: echo "Deploy to staging (blue/green)"

  benchmark:
    needs: deploy-staging
    runs-on: ubuntu-latest
    steps:
      - run: echo "Run benchmark harness against staging"
```

### 10.3 Sprint 0 Definition of Done

Before any feature work, ALL of these must exist and pass:

- [ ] Postgres schema applied and migrated (Alembic)
- [ ] Redis connected, Arq worker starts
- [ ] `/health`, `/ready`, `/metrics` endpoints responding
- [ ] Observability stack running (Prometheus, Grafana, Jaeger, Loki)
- [ ] At least one Grafana dashboard provisioned
- [ ] CI pipeline green (lint, test, build, health check)
- [ ] Staging environment deployable
- [ ] Verification sandbox container starts and runs a trivial build/test
- [ ] Benchmark harness can run a sample project through plain Claude Code
- [ ] Event log table accepts writes and supports replay query
- [ ] WebSocket endpoint connects and streams

---

## 11. Benchmark Harness

### 11.1 Design

The Studio must measurably beat a baseline of "plain Claude Code with good prompts." The benchmark harness proves this.

```python
# studio/benchmark/harness.py

@dataclass
class BenchmarkProject:
    name: str
    description: str
    requirements: list[str]
    complexity: str          # "trivial" | "simple" | "moderate"
    expected_modules: int
    expected_tests: int

BENCHMARK_PROJECTS = [
    BenchmarkProject(
        name="todo-cli",
        description="CLI todo app with persistence",
        requirements=["Add/remove/list todos", "Persist to file", "Mark complete"],
        complexity="trivial",
        expected_modules=3,
        expected_tests=10,
    ),
    BenchmarkProject(
        name="url-shortener",
        description="URL shortener HTTP API",
        requirements=["Shorten URL", "Redirect", "Click stats", "Rate limiting"],
        complexity="simple",
        expected_modules=5,
        expected_tests=20,
    ),
    BenchmarkProject(
        name="expense-tracker",
        description="Expense tracker with categories, budgets, and reports",
        requirements=[
            "CRUD expenses", "Categories", "Monthly budgets",
            "Budget vs actual report", "CSV export", "Multi-currency"
        ],
        complexity="moderate",
        expected_modules=8,
        expected_tests=40,
    ),
]

class BenchmarkRunner:
    """Runs the same projects through both plain Claude Code
    and The Studio, then compares metrics."""

    async def run_baseline(self, project: BenchmarkProject) -> BenchmarkResult:
        """Run project through plain Claude Code with good prompts."""
        # Use the coding agent directly with a well-crafted prompt
        # Measure: code quality, test coverage, complexity, coupling, time, cost
        ...

    async def run_studio(self, project: BenchmarkProject) -> BenchmarkResult:
        """Run project through The Studio."""
        # Create session, add requirements, run, collect metrics
        ...

    def compare(self, baseline: BenchmarkResult, studio: BenchmarkResult) -> Comparison:
        """Compare results. Studio must beat baseline on:
        - Code quality (testability, coupling, complexity, readability)
        - Customer experience metric
        - Test coverage
        - Design coherence (fewer workarounds, cleaner interfaces)
        Cost and time may be higher — that's acceptable IF quality is better."""
        ...

@dataclass
class BenchmarkResult:
    project: str
    approach: str            # "baseline" | "studio"
    duration_seconds: float
    total_cost_usd: float
    total_tokens: int
    test_coverage: float
    cyclomatic_complexity: float
    coupling_score: float
    duplication_pct: float
    tests_count: int
    tests_passing: int
    lint_issues: int
    experience_score: Optional[float]
    friction_items_found: int
    friction_items_resolved: int
    design_revisions: int
```

---

## 12. Phased Build Plan

### Sprint 0: Foundations (Week 1-2)

**Goal:** "You can deploy and observe it before any agent exists."

```
1. Project scaffolding
   ├── Python package structure (studio/)
   ├── pyproject.toml with dependencies
   ├── Docker Compose (all services)
   ├── Alembic migrations setup
   └── .env.local / .env.staging / .env.prod templates

2. Postgres schema
   ├── All tables from §3.1
   ├── Alembic initial migration
   └── SQLAlchemy models

3. Redis + Arq worker
   ├── Worker startup
   ├── Job enqueue/dequeue
   └── Cancellation semantics

4. FastAPI skeleton
   ├── /health, /ready, /metrics
   ├── CORS, error handling
   ├── REST API gate (503 when disabled)
   └── WebSocket endpoint (connects, sends pings)

5. Event log
   ├── Append events
   ├── Replay query (since seq)
   ├── WebSocket broadcast
   └── Contract test: event schema

6. Observability stack
   ├── Prometheus config + scrape targets
   ├── Grafana provisioning (at least Session Overview dashboard)
   ├── Jaeger config
   ├── Loki + Promtail config
   └── structlog configuration

7. Verification sandbox
   ├── Docker container for project builds
   ├── Mount project volume
   ├── Run trivial build/test cycle
   └── Return structured result

8. CI/CD pipeline
   ├── GitHub Actions workflow
   ├── Lint, test, build, health check
   └── Staging deploy step (stub)

9. Benchmark harness
   ├── BenchmarkProject definitions
   ├── Baseline runner (plain Claude Code)
   ├── Result schema and comparison
   └── Run baseline for todo-cli

10. CLI skeleton
    ├── Click/Typer structure
    ├── --json support
    ├── config show/set
    └── session list (empty)
```

### Sprint 1: Walking Skeleton of The Studio (Week 3-4)

**Goal:** "One thin vertical slice proves the Design⇄Build loop end-to-end."

```
1. Prompt files
   ├── Design agent system + initial_design prompts
   ├── Build agent system + skeleton prompts
   └── Prompt loading, hashing, metadata

2. LLM client abstraction
   ├── AnthropicClient (Claude via Max subscription)
   ├── Model config (switchable provider)
   ├── Token counting, cost tracking
   └── Prompt caching (static prefix)

3. Design agent (minimal)
   ├── Create initial design from requirements
   ├── Write design revision to DB
   ├── Generate digest
   └── Output contract implementation

4. Build agent (minimal)
   ├── Build walking skeleton via coding agent
   ├── TDD: write test first, then implement
   ├── Detect friction (basic: hard-to-test code)
   ├── Emit design_friction events
   └── Output contract implementation

5. LangGraph graph (minimal)
   ├── init_session → design_agent → skeleton_build → skeleton_verify
   ├── Friction edge: skeleton_verify fail → design_agent
   ├── Arq job execution
   └── State projection from DB

6. Verification node
   ├── Run build in sandbox
   ├── Run tests in sandbox
   ├── Run lint in sandbox
   ├── Return structured result

7. Design friction flow
   ├── Build agent emits friction
   ├── Friction persisted to DB
   ├── Conditional edge routes to Design agent
   ├── Design agent revises
   ├── Friction resolved, linked to revision
   └── ** This proves the key mechanism **

8. Run benchmark: todo-cli through Studio skeleton
   └── Compare with baseline
```

### Sprint 2: Complete Loops (Week 5-6)

**Goal:** "All three loops work. Human gates work."

```
1. UX/Customer agent
   ├── Prompts
   ├── Design review mode
   ├── Slice review mode
   ├── Experience metric definition
   └── Output contract

2. Design ⇄ UX loop
   ├── Graph edges
   ├── Convergence check
   └── Loop limit

3. Reviewer agent
   ├── Prompts
   ├── Pydantic structured output (tool-calling)
   ├── Different model config
   ├── Rubric scoring
   └── Only runs after verification passes

4. Build ⇄ Verification loop
   ├── Retry logic (max 3)
   ├── Persistent failure → design agent
   └── Coverage gate (≥80%)

5. Human gates
   ├── LangGraph interrupt
   ├── Design approval gate (with diff)
   ├── Ship approval gate
   ├── Timeout + expiry
   └── API endpoints: approve/reject

6. Slice planning
   ├── Plan slices from requirements
   ├── Order by dependency
   ├── Feature slice build loop
   └── Scope-creep detector

7. Full graph assembly
   ├── All nodes connected
   ├── All conditional edges
   ├── End-to-end: requirements → design → skeleton → slices → ship
   └── Run benchmark: url-shortener through full Studio
```

### Sprint 3: Interfaces & Polish (Week 7-8)

**Goal:** "Users can observe, interact, and control via UI + CLI + API."

```
1. REST API (full)
   ├── All endpoints from §6.1
   ├── 503 gate when disabled
   ├── Optimistic concurrency (409)
   └── OpenAPI spec

2. CLI (full)
   ├── All commands from §6.3
   ├── Rich colored output
   ├── --json mode
   ├── watch command (event stream)
   └── Parity test with API

3. Web UI
   ├── React + Vite + TypeScript + Tailwind + shadcn/ui
   ├── Loop view (react-flow canvas)
   ├── Living Design view (rendered, diff, friction links)
   ├── Design Friction board
   ├── Agent panel (streaming output)
   ├── Control bar (Run/Pause/Stop/Resume)
   ├── Human approval modal (diff view)
   ├── Customer Experience panel
   ├── Requirements panel
   ├── Config panel
   ├── WebSocket connection (reconnect, replay, dedupe)
   └── 409 handling (refetch + toast)

4. Observability dashboards (complete)
   ├── All 6 dashboards from §7.5
   └── Grafana provisioning
```

### Sprint 4: AI-Native & Integrations (Week 9-10)

**Goal:** "The system improves itself. External integrations work."

```
1. AIFeedbackRecord
   ├── Write on every loop iteration
   ├── Query API
   └── Index for improvement worker

2. Improvement worker
   ├── Underperformer detection
   ├── Correction sampling
   ├── Suggestion generation
   ├── Jira ticket creation
   └── Configurable interval

3. Shadow mode
   ├── Candidate model runner
   ├── Offline review scoring
   ├── Comparison dashboard
   └── Promotion workflow

4. AI Health tab (UI)
   ├── Per-agent score over time
   ├── Approval/correction rates
   ├── Cost efficiency
   ├── Apply Suggestion action

5. Jira integration (MCP)
   ├── Requirements sync
   ├── Friction items as Jira issues
   ├── Bug sync
   └── Task management

6. GitHub integration (MCP)
   ├── Source control for Studio itself
   └── PR workflow

7. Git (project)
   ├── Init repo in project volume
   ├── Commit per slice
   ├── Design versioned alongside code
   └── Push to remote

8. Bug Reports & Test Scenarios screens
   ├── CRUD API
   ├── Friction routing (bug → friction)
   └── UI screens

9. Attachments
   ├── Upload to object storage
   ├── Link to requirements/bugs/design
   └── UI upload component

10. Final benchmark
    ├── Run expense-tracker through full Studio
    ├── Compare all three projects
    └── Publish results
```

---

## 13. Open Questions

These are flagged rather than assumed:

1. **Coding agent interface:** How exactly does the Build agent invoke Claude Code? Via CLI subprocess? MCP? API? This determines the Build agent's implementation significantly. **Recommendation:** Start with CLI subprocess (`claude-code --prompt "..." --project-dir /path`), abstract behind an interface for swappability.

2. **Object storage for design/artifacts:** The spec says "object storage / git, referenced by key." For MVP, store design content as files in the project git repo (versioned alongside code). Defer S3/MinIO until multi-session concurrent access requires it. **Risk:** Large designs may bloat the git repo.

3. **Max subscription vs API key:** "Default Claude via Max subscription (no API key)." How does this work programmatically? If Max subscription provides API access, use the Anthropic SDK. If it means using Claude interactively, the architecture needs a different LLM client. **Recommendation:** Implement the Anthropic SDK client, support both API key and Max subscription auth.

4. **Reviewer model selection:** "Uses a different model from the other agents." Which model? If primary is Claude Sonnet, Reviewer could be Claude Opus, GPT-4o, or Gemini Pro. **Recommendation:** Make it a config value, default to a different-family model (e.g., GPT-4o if primary is Claude).

5. **Verification sandbox security:** Running arbitrary generated code in a Docker container has security implications. Should the sandbox be network-isolated? Resource-limited? Time-limited? **Recommendation:** Yes to all three. `--network none`, memory/CPU limits, 5-minute timeout.

6. **Event log retention:** The append-only event log will grow. Retention policy? Archival? **Recommendation:** 30-day retention in Postgres, archive to cold storage for replay/audit.

7. **Design digest ≤500 tokens:** Is this sufficient for complex projects? The digest is a summary, and agents can fetch full sections by ID, so it should be. But the threshold may need tuning. **Recommendation:** Start at 500, monitor, adjust if agents frequently need to fetch too many sections.

8. **i18n implementation details:** "i18n framework and RTL-safe logical CSS" — which framework? For a Python backend, `gettext` or `babel`. For React frontend, `react-intl` or `i18next`. **Recommendation:** `i18next` for frontend (good RTL support, Hebrew plural forms), `babel` for backend strings.

9. **Jira MCP server:** Is there a standard Jira MCP server, or does this need to be built? **Recommendation:** Check for existing Jira MCP servers; build a thin adapter if none exists.

10. **Session concurrency:** Can multiple humans interact with the same session simultaneously? The spec mentions per-session locking, which suggests single-writer. **Recommendation:** Single active writer (the Arq worker), multiple readers (UI/API). Human gates are the interaction points.

---

## Appendix A: Project Structure

```
the-studio/
├── docker-compose.yml
├── docker-compose.override.yml      # local dev overrides
├── .env.local
├── .env.staging
├── .env.prod
├── .github/
│   └── workflows/
│       └── ci.yml
├── studio/                          # Python backend package
│   ├── __init__.py
│   ├── main.py                      # FastAPI app
│   ├── config.py                    # Configuration management
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── sessions.py
│   │   │   ├── design.py
│   │   │   ├── friction.py
│   │   │   ├── requirements.py
│   │   │   ├── bugs.py
│   │   │   ├── tests.py
│   │   │   ├── git_routes.py
│   │   │   ├── ai_health.py
│   │   │   ├── config_routes.py
│   │   │   ├── attachments.py
│   │   │   └── health.py
│   │   ├── websocket.py
│   │   ├── middleware.py             # REST gate, CORS, error handling
│   │   └── schemas.py               # Pydantic request/response schemas
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py                # SQLAlchemy models
│   │   ├── session.py               # DB session management
│   │   ├── projection.py            # State projection
│   │   └── migrations/
│   │       └── versions/
│   │           └── 001_initial.py
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py                 # GraphState
│   │   ├── builder.py               # LangGraph graph construction
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── init_session.py
│   │   │   ├── design_agent.py
│   │   │   ├── ux_agent.py
│   │   │   ├── build_agent.py
│   │   │   ├── reviewer.py
│   │   │   ├── verify.py
│   │   │   ├── skeleton.py
│   │   │   ├── slice_plan.py
│   │   │   ├── human_gate.py
│   │   │   └── complete.py
│   │   └── edges.py                 # Conditional routing functions
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py                  # Base agent class
│   │   ├── design.py
│   │   ├── ux.py
│   │   ├── build.py
│   │   └── reviewer.py
│   ├── design/
│   │   ├── __init__.py
│   │   ├── schema.py                # LivingDesign Pydantic model
│   │   ├── revision.py              # Versioning, hashing, diffing
│   │   └── digest.py                # Digest generation
│   ├── friction/
│   │   ├── __init__.py
│   │   ├── contract.py              # FrictionReport schema
│   │   ├── detector.py              # Code quality → friction detection
│   │   └── router.py                # Friction → Design agent routing
│   ├── verification/
│   │   ├── __init__.py
│   │   ├── sandbox.py               # Docker sandbox management
│   │   ├── checks.py                # Deterministic check definitions
│   │   └── runner.py                # Run checks, collect results
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── llm_client.py            # LLM abstraction (Anthropic/OpenAI/Google)
│   │   ├── caching.py               # Prompt caching
│   │   ├── budget.py                # Token/cost budget enforcement
│   │   ├── feedback.py              # AIFeedbackRecord
│   │   ├── improvement_worker.py
│   │   ├── shadow.py                # Shadow mode
│   │   └── determinism.py           # Run config pinning
│   ├── events/
│   │   ├── __init__.py
│   │   ├── emitter.py               # Event emission
│   │   ├── replay.py                # Event replay
│   │   └── schemas.py               # Event type definitions
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── jira.py                  # Jira MCP integration
│   │   ├── github.py                # GitHub MCP integration
│   │   └── git.py                   # Project git operations
│   ├── worker/
│   │   ├── __init__.py
│   │   └── arq_worker.py            # Arq worker configuration
│   └── observability/
│       ├── __init__.py
│       ├── logging.py               # structlog config
│       ├── metrics.py               # Prometheus metrics
│       └── tracing.py               # OpenTelemetry setup
├── prompts/                          # Versioned prompt files
│   ├── design_agent/
│   ├── ux_agent/
│   ├── build_agent/
│   └── reviewer/
├── cli/
│   ├── __init__.py
│   └── main.py                      # Click/Typer CLI
├── frontend/                         # React app
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── stores/                   # zustand
│   │   ├── components/
│   │   │   ├── LoopView.tsx          # react-flow canvas
│   │   │   ├── DesignView.tsx
│   │   │   ├── FrictionBoard.tsx
│   │   │   ├── AgentPanel.tsx
│   │   │   ├── ControlBar.tsx
│   │   │   ├── HumanApproval.tsx
│   │   │   ├── ExperiencePanel.tsx
│   │   │   ├── RequirementsPanel.tsx
│   │   │   ├── ConfigPanel.tsx
│   │   │   └── AIHealthTab.tsx
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts
│   │   │   └── useSession.ts
│   │   └── lib/
│   │       ├── api.ts                # REST client
│   │       └── types.ts              # TypeScript types
│   └── public/
├── observability/
│   ├── prometheus.yml
│   ├── promtail.yml
│   ├── loki.yml
│   └── grafana/
│       ├── provisioning/
│       │   ├── datasources/
│       │   └── dashboards/
│       └── dashboards/
│           ├── session-overview.json
│           ├── loop-activity.json
│           ├── design-health.json
│           ├── llm-cost.json
│           ├── customer-experience.json
│           └── ai-health.json
├── sandbox/
│   └── Dockerfile                    # Verification sandbox
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contracts/                    # Agent ↔ design schema contracts
│   └── benchmark/
├── Dockerfile                        # Backend
├── Dockerfile.frontend               # Frontend
└── pyproject.toml
```

---

## Appendix B: Docker Compose

```yaml
# docker-compose.yml
version: "3.9"

services:
  backend:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://studio:studio@postgres:5432/studio
      - REDIS_URL=redis://redis:6379
      - ENVIRONMENT=local
    volumes:
      - project-data:/project
      - ./prompts:/app/prompts
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    user: "1000:1000"

  worker:
    build: .
    command: python -m studio.worker.arq_worker
    environment:
      - DATABASE_URL=postgresql+asyncpg://studio:studio@postgres:5432/studio
      - REDIS_URL=redis://redis:6379
      - ENVIRONMENT=local
    volumes:
      - project-data:/project
      - ./prompts:/app/prompts
      - /var/run/docker.sock:/var/run/docker.sock  # for sandbox
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    user: "1000:1000"

  frontend:
    build:
      context: ./frontend
      dockerfile: ../Dockerfile.frontend
    ports:
      - "5173:5173"

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: studio
      POSTGRES_USER: studio
      POSTGRES_PASSWORD: studio
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U studio"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  sandbox:
    build: ./sandbox
    volumes:
      - project-data:/project
    network_mode: "none"        # network isolated
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: 2G

  # Observability
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./observability/prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    volumes:
      - ./observability/grafana/provisioning:/etc/grafana/provisioning
      - ./observability/grafana/dashboards:/var/lib/grafana/dashboards
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_AUTH_ANONYMOUS_ENABLED=true

  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"
      - "6831:6831/udp"

  loki:
    image: grafana/loki:latest
    ports:
      - "3100:3100"
    volumes:
      - ./observability/loki.yml:/etc/loki/local-config.yaml

  promtail:
    image: grafana/promtail:latest
    volumes:
      - /var/log:/var/log:ro
      - ./observability/promtail.yml:/etc/promtail/config.yml

volumes:
  pgdata:
  project-data:
```

---

## Appendix C: Key Dependencies

```toml
# pyproject.toml [project.dependencies]
[project]
name = "the-studio"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    # Core
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.9",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "arq>=0.26",
    "redis>=5.2",

    # LangGraph
    "langgraph>=0.2",
    "langchain-core>=0.3",
    "langchain-anthropic>=0.3",
    "langchain-openai>=0.3",

    # LLM clients
    "anthropic>=0.40",
    "openai>=1.50",

    # Observability
    "structlog>=24.0",
    "prometheus-client>=0.21",
    "opentelemetry-api>=1.28",
    "opentelemetry-sdk>=1.28",
    "opentelemetry-exporter-jaeger>=1.21",

    # CLI
    "typer>=0.12",
    "rich>=13.9",

    # Utilities
    "httpx>=0.27",
    "websockets>=13",
    "python-multipart>=0.0.12",
]

[project.optional-dependencies]
test = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "httpx>=0.27",  # for TestClient
    "ruff>=0.7",
    "mypy>=1.13",
]
```

---

*This document is the implementation guide for Claude Code. Build in the order specified in §12 (Phased Build Plan). Start with Sprint 0 foundations. Flag questions from §13 as they become blocking. Every structural choice is justified; override only with a better justification.*
