"""Shared pytest fixtures for the HTTP API tests."""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings():
    # Generous rate limit so functional tests are never throttled by accident.
    return Settings(
        base_url="http://testserver",
        short_code_length=7,
        rate_limit_max_requests=1000,
        rate_limit_window_seconds=60,
    )


@pytest.fixture
def client(settings):
    app = create_app(settings=settings)
    with TestClient(app) as test_client:
        yield test_client
