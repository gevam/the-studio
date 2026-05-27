"""Prometheus metrics definitions (§7.3)."""

from prometheus_client import Counter, Gauge, Histogram

# --- Counters ---
sessions_total = Counter(
    "studio_sessions_total",
    "Total sessions created",
    ["status"],
)
llm_calls_total = Counter(
    "studio_llm_calls_total",
    "Total LLM calls",
    ["agent", "model"],
)
design_revisions_total = Counter(
    "studio_design_revisions_total",
    "Design revisions",
    ["caused_by"],
)
design_friction_total = Counter(
    "studio_design_friction_total",
    "Design friction items reported",
    ["category", "severity"],
)
slices_built_total = Counter(
    "studio_slices_built_total",
    "Slices built",
    ["type"],
)
verification_failures_total = Counter(
    "studio_verification_failures_total",
    "Verification failures",
    ["check"],
)
human_decisions_total = Counter(
    "studio_human_decisions_total",
    "Human gate decisions",
    ["gate_type", "action"],
)

# --- Histograms ---
loop_duration_seconds = Histogram(
    "studio_loop_duration_seconds",
    "Duration of each loop pass",
    ["loop"],
)
llm_latency_seconds = Histogram(
    "studio_llm_latency_seconds",
    "LLM call latency",
    ["agent", "model"],
)
reviewer_score_histogram = Histogram(
    "studio_reviewer_score",
    "Reviewer scores per agent",
    ["agent"],
    buckets=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
)
code_quality_score = Histogram(
    "studio_code_quality_score",
    "Code quality metric values",
    ["metric"],
)
design_friction_score = Histogram(
    "studio_design_friction_score",
    "Friction scores by category",
    ["category"],
    buckets=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
)
session_cost_usd = Histogram(
    "studio_session_cost_usd",
    "Total session cost in USD",
    buckets=[0.01, 0.05, 0.1, 0.5, 1, 5, 10, 25, 50, 100],
)
tokens_per_loop = Histogram(
    "studio_tokens_per_loop",
    "Tokens used per loop pass",
    ["loop"],
    buckets=[100, 500, 1000, 5000, 10000, 50000, 100000],
)

# --- Gauges ---
active_sessions = Gauge("studio_active_sessions", "Number of currently active sessions")
sessions_awaiting_human = Gauge(
    "studio_sessions_awaiting_human",
    "Sessions blocked on human gate",
)
open_friction_items = Gauge("studio_open_friction_items", "Open design friction items")
backlog_size = Gauge("studio_backlog_size", "Remaining unbuilt slices")
