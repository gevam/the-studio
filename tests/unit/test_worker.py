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


def test_run_session_graph_is_async():
    """run_session_graph is an async function (not the old stub)."""
    import asyncio
    from studio.worker.arq_worker import run_session_graph
    assert asyncio.iscoroutinefunction(run_session_graph)
