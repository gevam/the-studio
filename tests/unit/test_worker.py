"""Tests for studio.worker.arq_worker module."""

import pytest


def test_worker_settings_importable():
    """WorkerSettings can be imported and has expected attributes."""
    from studio.worker.arq_worker import WorkerSettings

    assert hasattr(WorkerSettings, "functions")
    assert hasattr(WorkerSettings, "redis_settings")
    assert hasattr(WorkerSettings, "on_startup")
    assert hasattr(WorkerSettings, "on_shutdown")
    assert hasattr(WorkerSettings, "max_jobs")


def test_worker_functions_registered():
    """ping and run_session_graph are registered as worker functions."""
    from studio.worker.arq_worker import WorkerSettings, ping, run_session_graph

    assert ping in WorkerSettings.functions
    assert run_session_graph in WorkerSettings.functions


@pytest.mark.asyncio
async def test_ping_job_returns_message():
    """ping job returns the message it receives."""
    from studio.worker.arq_worker import ping

    ctx: dict = {}
    result = await ping(ctx, message="hello")
    assert result == "hello"


@pytest.mark.asyncio
async def test_ping_job_default_message():
    """ping job returns 'pong' when called with no message."""
    from studio.worker.arq_worker import ping

    ctx: dict = {}
    result = await ping(ctx)
    assert result == "pong"


@pytest.mark.asyncio
async def test_run_session_graph_stub_returns_session_id():
    """run_session_graph stub returns the session_id it was given."""
    from studio.worker.arq_worker import run_session_graph

    ctx: dict = {}
    session_id = "test-session-123"
    result = await run_session_graph(ctx, session_id=session_id)
    assert result["session_id"] == session_id
    assert result["status"] == "not_implemented"
