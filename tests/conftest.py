"""Shared pytest fixtures."""

import os

import pytest
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
