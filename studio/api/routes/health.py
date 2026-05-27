"""Health, readiness, and metrics endpoints (always on — not behind REST gate)."""

from fastapi import APIRouter
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from studio.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness probe — returns 200 when the process is alive."""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict:
    """Readiness probe — checks DB and Redis connectivity."""
    db_ok = await _check_db()
    redis_ok = await _check_redis()

    status = "ready" if (db_ok and redis_ok) else "degraded"
    code = 200 if (db_ok and redis_ok) else 503
    body = {"status": status, "db": db_ok, "redis": redis_ok}

    if code != 200:
        return Response(content=str(body), status_code=code, media_type="application/json")
    return body


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics scrape endpoint."""
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


async def _check_db() -> bool:
    try:
        from sqlalchemy import text

        from studio.db.session import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _check_redis() -> bool:
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False
