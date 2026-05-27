"""Tests for /health, /ready, /metrics endpoints."""

from unittest.mock import AsyncMock, patch


def test_health_returns_ok(client):
    """/health always returns 200 with {status: ok}."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_does_not_require_db(client):
    """/health is independent of DB/Redis — pure liveness check."""
    with patch("studio.api.routes.health._check_db", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = False
        response = client.get("/health")
    # /health must still return 200 even if DB is down
    assert response.status_code == 200


def test_ready_when_db_and_redis_up(client):
    """/ready returns 200 when both DB and Redis are healthy."""
    with (
        patch("studio.api.routes.health._check_db", new_callable=AsyncMock) as mock_db,
        patch("studio.api.routes.health._check_redis", new_callable=AsyncMock) as mock_redis,
    ):
        mock_db.return_value = True
        mock_redis.return_value = True
        response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["db"] is True
    assert data["redis"] is True


def test_ready_when_db_down(client):
    """/ready returns 503 when DB is unavailable."""
    with (
        patch("studio.api.routes.health._check_db", new_callable=AsyncMock) as mock_db,
        patch("studio.api.routes.health._check_redis", new_callable=AsyncMock) as mock_redis,
    ):
        mock_db.return_value = False
        mock_redis.return_value = True
        response = client.get("/ready")
    assert response.status_code == 503


def test_metrics_returns_prometheus_format(client):
    """/metrics returns text with prometheus content type."""
    response = client.get("/metrics")
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "text/plain" in content_type or "application/openmetrics-text" in content_type


def test_rest_gate_returns_503_when_disabled(client):
    """API routes return 503 when rest_api_enabled is False."""
    with patch("studio.api.middleware.settings") as mock_settings:
        mock_settings.rest_api_enabled = False
        response = client.get("/api/sessions")
    assert response.status_code == 503


def test_rest_gate_allows_health_when_disabled(client):
    """/health bypasses the REST gate regardless of rest_api_enabled."""
    with patch("studio.api.middleware.settings") as mock_settings:
        mock_settings.rest_api_enabled = False
        response = client.get("/health")
    assert response.status_code == 200
