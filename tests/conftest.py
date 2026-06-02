"""Shared pytest fixtures."""

import os

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Use test env vars before importing anything from studio
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://studio:studio@localhost:5432/studio_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("REST_API_ENABLED", "true")


@pytest.fixture(scope="session")
def app():
    from studio.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest_asyncio.fixture
async def session_factory():
    """Yield AsyncSessionLocal against the live test DB, or skip if unreachable.

    Disposes the engine pool on teardown so the next test's function-scoped event
    loop never inherits a connection bound to a closed loop.
    """
    from sqlalchemy import text

    from studio.db.session import AsyncSessionLocal, engine

    try:
        async with AsyncSessionLocal() as probe:
            await probe.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — any connection failure means "no live DB"
        pytest.skip("live database not reachable")

    yield AsyncSessionLocal
    await engine.dispose()
