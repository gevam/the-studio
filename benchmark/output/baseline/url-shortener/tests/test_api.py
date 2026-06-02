"""End-to-end HTTP API tests for the URL shortener."""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

EXAMPLE_URL = "https://example.com/some/long/path?q=1"


# --- Shorten ---------------------------------------------------------------

def test_shorten_returns_short_code_and_url(client):
    resp = client.post("/shorten", json={"url": EXAMPLE_URL})
    assert resp.status_code == 201
    body = resp.json()
    assert body["url"] == EXAMPLE_URL
    assert len(body["short_code"]) == 7
    assert body["short_url"].endswith(body["short_code"])


def test_shorten_rejects_invalid_url(client):
    resp = client.post("/shorten", json={"url": "not-a-url"})
    assert resp.status_code == 422


def test_shorten_rejects_non_http_scheme(client):
    resp = client.post("/shorten", json={"url": "ftp://example.com/file"})
    assert resp.status_code == 422


def test_shorten_missing_body_is_rejected(client):
    resp = client.post("/shorten", json={})
    assert resp.status_code == 422


def test_two_shortens_yield_distinct_codes(client):
    a = client.post("/shorten", json={"url": "https://a.com"}).json()["short_code"]
    b = client.post("/shorten", json={"url": "https://b.com"}).json()["short_code"]
    assert a != b


# --- Redirect --------------------------------------------------------------

def test_redirect_sends_to_original_url(client):
    code = client.post("/shorten", json={"url": EXAMPLE_URL}).json()["short_code"]
    resp = client.get(f"/{code}", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == EXAMPLE_URL


def test_redirect_unknown_code_returns_404(client):
    resp = client.get("/doesnotexist", follow_redirects=False)
    assert resp.status_code == 404


# --- Stats -----------------------------------------------------------------

def test_stats_start_at_zero(client):
    code = client.post("/shorten", json={"url": EXAMPLE_URL}).json()["short_code"]
    body = client.get(f"/stats/{code}").json()
    assert body["clicks"] == 0
    assert body["url"] == EXAMPLE_URL
    assert body["short_code"] == code
    assert "created_at" in body


def test_stats_count_redirects(client):
    code = client.post("/shorten", json={"url": EXAMPLE_URL}).json()["short_code"]
    for _ in range(3):
        client.get(f"/{code}", follow_redirects=False)
    assert client.get(f"/stats/{code}").json()["clicks"] == 3


def test_stats_unknown_code_returns_404(client):
    assert client.get("/stats/missing").status_code == 404


# --- Health ----------------------------------------------------------------

def test_health_check_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --- Rate limiting ---------------------------------------------------------

def test_rate_limit_returns_429_when_exceeded():
    settings = Settings(
        base_url="http://testserver",
        rate_limit_max_requests=3,
        rate_limit_window_seconds=60,
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        statuses = [client.get("/health").status_code for _ in range(4)]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429


def test_rate_limit_response_sets_retry_after_header():
    settings = Settings(
        base_url="http://testserver",
        rate_limit_max_requests=1,
        rate_limit_window_seconds=60,
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        client.get("/health")
        blocked = client.get("/health")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 0
