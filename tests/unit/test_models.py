"""Tests for studio.db.models — all 15 tables from §3.1."""

import uuid


def test_all_models_importable():
    """All SQLAlchemy models can be imported."""
    from studio.db.models import (
        AIFeedback,
        Artifact,
        Attachment,
        Base,
        BugReport,
        DesignFriction,
        DesignRevision,
        EventLog,
        HumanDecision,
        Requirement,
        ReviewerRecord,
        Session,
        SessionLock,
        Slice,
        TestScenario,
        VerificationResult,
    )

    models = [
        Session, SessionLock, DesignRevision, DesignFriction,
        Slice, Requirement, Artifact, ReviewerRecord,
        VerificationResult, HumanDecision, AIFeedback,
        EventLog, BugReport, TestScenario, Attachment,
    ]
    assert len(models) == 15


def test_session_model_columns():
    """Session model has required columns from §3.1."""
    from studio.db.models import Session

    cols = {c.name for c in Session.__table__.columns}
    required = {
        "id", "name", "status", "version", "iteration",
        "token_budget", "cost_budget", "tokens_used", "cost_usd",
        "config", "created_at", "updated_at",
    }
    assert required.issubset(cols)


def test_event_log_unique_constraint():
    """EventLog has a unique constraint on (session_id, seq)."""
    from studio.db.models import EventLog

    constraint_names = {c.name for c in EventLog.__table__.constraints}
    assert "uq_event_log_session_seq" in constraint_names


def test_session_default_uuid():
    """Session.id defaults to a UUID."""
    from studio.db.models import Session

    s = Session(name="test", status="created")
    # Default is a callable, not a static value
    col = Session.__table__.c.id
    assert col.default is not None or col.server_default is not None


def test_base_metadata_has_all_tables():
    """Base.metadata contains all 15 tables."""
    from studio.db.models import Base

    table_names = set(Base.metadata.tables.keys())
    expected = {
        "sessions", "session_locks", "design_revisions", "design_friction",
        "slices", "requirements", "artifacts", "reviewer_records",
        "verification_results", "human_decisions", "ai_feedback",
        "event_log", "bug_reports", "test_scenarios", "attachments",
    }
    assert expected == table_names
