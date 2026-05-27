"""Arq worker configuration and job definitions.

Sprint 0: worker starts, enqueues, dequeues a ping job.
Sprint 1+ will add: run_session_graph, cancel_session.
"""

from arq import create_pool
from arq.connections import RedisSettings

import structlog

from studio.config import settings
from studio.observability.logging import configure_logging

logger = structlog.get_logger(__name__)


# --- Job definitions ---

async def ping(ctx: dict, message: str = "pong") -> str:
    """Trivial job to verify the worker processes tasks."""
    logger.info("ping_job", message=message)
    return message


async def run_session_graph(ctx: dict, session_id: str) -> dict:
    """Placeholder: will run LangGraph session in Sprint 1."""
    logger.info("run_session_graph_stub", session_id=session_id)
    return {"session_id": session_id, "status": "not_implemented"}


# --- Startup / shutdown hooks ---

async def startup(ctx: dict) -> None:
    configure_logging(settings.log_level)
    logger.info("worker_starting", environment=settings.environment)


async def shutdown(ctx: dict) -> None:
    logger.info("worker_stopping")


# --- Worker settings ---

class WorkerSettings:
    functions = [ping, run_session_graph]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.worker_concurrency
    job_timeout = 3600  # 1 hour max per job
    keep_result = 3600  # keep results for 1 hour


# --- Helper: enqueue a job from any async context ---

async def enqueue_session(session_id: str) -> str:
    """Enqueue a run_session_graph job; returns the arq job ID."""
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    job = await pool.enqueue_job("run_session_graph", session_id)
    await pool.aclose()
    if job is None:
        raise RuntimeError(f"Failed to enqueue job for session {session_id}")
    return job.job_id


if __name__ == "__main__":
    import arq.worker

    arq.worker.run_worker(WorkerSettings)
