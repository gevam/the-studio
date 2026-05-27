"""Initial schema — all tables from §3.1.

Revision ID: 001
Revises:
Create Date: 2026-05-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # sessions
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="created"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("current_node", sa.Text),
        sa.Column("current_loop", sa.Text),
        sa.Column("iteration", sa.Integer, nullable=False, server_default="0"),
        sa.Column("token_budget", sa.Integer, nullable=False, server_default="500000"),
        sa.Column("cost_budget", sa.Numeric(10, 4), nullable=False, server_default="50.0000"),
        sa.Column("tokens_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False, server_default="0.0000"),
        sa.Column("config", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("trace_id", sa.Text),
        sa.Column("arq_job_id", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint(
            "status IN ('created','running','paused','stopping','awaiting_human',"
            "'completed','error','cancelled')",
            name="sessions_status_check",
        ),
    )
    op.create_index("idx_sessions_status", "sessions", ["status"])

    # session_locks
    op.create_table(
        "session_locks",
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), primary_key=True),
        sa.Column("locked_by", sa.Text, nullable=False),
        sa.Column("locked_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )

    # design_revisions
    op.create_table(
        "design_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("content_key", sa.Text, nullable=False),
        sa.Column("digest", sa.Text, nullable=False),
        sa.Column("section_index", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("caused_by_agent", sa.Text),
        sa.Column("caused_by_friction_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("session_id", "version", name="uq_design_revisions_session_version"),
    )
    op.create_index("idx_design_rev_session", "design_revisions", ["session_id", "version"])

    # design_friction
    op.create_table(
        "design_friction",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("slice_id", postgresql.UUID(as_uuid=True)),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("code_location", sa.Text),
        sa.Column("friction_score", sa.Numeric(5, 2)),
        sa.Column("resolved_by_revision_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("design_revisions.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint(
            "status IN ('open','acknowledged','resolved')",
            name="design_friction_status_check",
        ),
        sa.CheckConstraint(
            "severity IN ('low','medium','high','critical')",
            name="design_friction_severity_check",
        ),
    )
    op.create_index("idx_friction_session", "design_friction", ["session_id", "status"])
    op.create_index("idx_friction_category", "design_friction", ["category"])

    # slices
    op.create_table(
        "slices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("slice_type", sa.Text, nullable=False, server_default="feature"),
        sa.Column("status", sa.Text, nullable=False, server_default="planned"),
        sa.Column("order_index", sa.Integer, nullable=False),
        sa.Column("design_version", sa.Integer, nullable=False),
        sa.Column("test_coverage", sa.Numeric(5, 2)),
        sa.Column("cyclomatic_complexity", sa.Numeric(5, 2)),
        sa.Column("coupling_score", sa.Numeric(5, 2)),
        sa.Column("duplication_pct", sa.Numeric(5, 2)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint(
            "slice_type IN ('skeleton','feature')",
            name="slices_type_check",
        ),
        sa.CheckConstraint(
            "status IN ('planned','building','verifying','reviewing','done','failed')",
            name="slices_status_check",
        ),
    )
    op.create_index("idx_slices_session", "slices", ["session_id", "order_index"])

    # requirements
    op.create_table(
        "requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("priority", sa.Text, nullable=False, server_default="medium"),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("jira_key", sa.Text),
        sa.Column("queued_changes", postgresql.JSONB),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    # artifacts
    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("slice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("slices.id")),
        sa.Column("artifact_type", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("content_key", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_artifacts_session", "artifacts", ["session_id"])

    # reviewer_records
    op.create_table(
        "reviewer_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("slice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("slices.id")),
        sa.Column("design_version", sa.Integer, nullable=False),
        sa.Column("rubric_scores", postgresql.JSONB, nullable=False),
        sa.Column("overall_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("issues", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("model_used", sa.Text, nullable=False),
        sa.Column("prompt_hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    # verification_results
    op.create_table(
        "verification_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("slice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("slices.id")),
        sa.Column("verification_type", sa.Text, nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("build_passed", sa.Boolean),
        sa.Column("test_passed", sa.Boolean),
        sa.Column("lint_passed", sa.Boolean),
        sa.Column("build_output", sa.Text),
        sa.Column("test_output", sa.Text),
        sa.Column("lint_output", sa.Text),
        sa.Column("test_coverage", sa.Numeric(5, 2)),
        sa.Column("tests_run", sa.Integer),
        sa.Column("tests_passed", sa.Integer),
        sa.Column("tests_failed", sa.Integer),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    # human_decisions
    op.create_table(
        "human_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("gate_type", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("feedback", sa.Text),
        sa.Column("diff_snapshot", postgresql.JSONB),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    # ai_feedback
    op.create_table(
        "ai_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("loop", sa.Text, nullable=False),
        sa.Column("agent", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("prompt_hash", sa.Text, nullable=False),
        sa.Column("tokens_in", sa.Integer, nullable=False),
        sa.Column("tokens_out", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("reviewer_score", sa.Numeric(5, 2)),
        sa.Column("friction_produced", sa.Integer, nullable=False, server_default="0"),
        sa.Column("friction_resolved", sa.Integer, nullable=False, server_default="0"),
        sa.Column("human_decision", sa.Text),
        sa.Column("human_corrected", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("correction_text", sa.Text),
        sa.Column("quality_signal", sa.Numeric(5, 2)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_ai_feedback_agent", "ai_feedback", ["agent", "created_at"])
    op.create_index("idx_ai_feedback_session", "ai_feedback", ["session_id"])

    # event_log
    op.create_table(
        "event_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("agent", sa.Text),
        sa.Column("loop", sa.Text),
        sa.Column("data", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("trace_id", sa.Text),
        sa.Column("span_id", sa.Text),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("session_id", "seq", name="uq_event_log_session_seq"),
    )
    op.create_index("idx_event_log_session_seq", "event_log", ["session_id", "seq"])
    op.create_index("idx_event_log_type", "event_log", ["event_type"])

    # bug_reports
    op.create_table(
        "bug_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("friction_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("design_friction.id")),
        sa.Column("jira_key", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "severity IN ('low','medium','high','critical')",
            name="bug_reports_severity_check",
        ),
        sa.CheckConstraint(
            "status IN ('open','triaged','fixed','wontfix')",
            name="bug_reports_status_check",
        ),
    )

    # test_scenarios
    op.create_table(
        "test_scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("scenario_type", sa.Text, nullable=False, server_default="functional"),
        sa.Column("status", sa.Text, nullable=False, server_default="proposed"),
        sa.Column("slice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("slices.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    # attachments
    op.create_table(
        "attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("parent_type", sa.Text, nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_attachments_parent", "attachments", ["parent_type", "parent_id"])


def downgrade() -> None:
    op.drop_table("attachments")
    op.drop_table("test_scenarios")
    op.drop_table("bug_reports")
    op.drop_table("event_log")
    op.drop_table("ai_feedback")
    op.drop_table("human_decisions")
    op.drop_table("verification_results")
    op.drop_table("reviewer_records")
    op.drop_table("artifacts")
    op.drop_table("requirements")
    op.drop_table("slices")
    op.drop_table("design_friction")
    op.drop_table("design_revisions")
    op.drop_table("session_locks")
    op.drop_table("sessions")
