"""Arq worker configuration and job definitions."""

import uuid

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
    """Run the LangGraph session graph for a given session."""
    from studio.ai.llm_client import LLMClient
    from studio.ai.prompt_loader import PromptLoader
    from studio.db.projection import project_state
    from studio.db.session import AsyncSessionLocal
    from studio.graph.builder import build_sprint1_graph

    logger.info("run_session_graph_start", session_id=session_id)

    llm = LLMClient(provider="auto")
    prompt_loader = PromptLoader()

    compiled = build_sprint1_graph(
        db_factory=AsyncSessionLocal,
        llm=llm,
        prompt_loader=prompt_loader,
    )

    # Load initial state from DB
    sid = uuid.UUID(session_id)
    async with AsyncSessionLocal() as db:
        state = await project_state(sid, db)
        await db.commit()

    # Run graph — each node opens its own DB session via the factory
    try:
        final_state = await compiled.ainvoke(state)
        status = "completed" if final_state.get("skeleton_verified") else "error"
        logger.info(
            "run_session_graph_done",
            session_id=session_id,
            status=status,
            iterations=final_state.get("iteration", 0),
        )
        return {
            "session_id": session_id,
            "status": status,
            "iterations": final_state.get("iteration", 0),
            "cost_usd": final_state.get("cost_usd", 0.0),
        }
    except Exception as exc:
        logger.error("run_session_graph_error", session_id=session_id, error=str(exc))
        # Mark session as error in DB
        async with AsyncSessionLocal() as db:
            from studio.db.models import Session as SessionModel
            session = await db.get(SessionModel, sid)
            if session:
                session.status = "error"
                await db.commit()
        return {"session_id": session_id, "status": "error", "error": str(exc)}


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
