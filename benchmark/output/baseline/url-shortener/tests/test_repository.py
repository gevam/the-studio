"""Unit tests for the in-memory link repository (app.repository)."""
import pytest

from app.repository import InMemoryLinkRepository, LinkNotFoundError


@pytest.fixture
def repo():
    return InMemoryLinkRepository()


def test_add_then_get_returns_record(repo):
    record = repo.add(short_code="abc123", url="https://example.com")
    fetched = repo.get("abc123")
    assert fetched.short_code == "abc123"
    assert fetched.url == "https://example.com"
    assert fetched.clicks == 0
    assert fetched is record


def test_get_missing_raises(repo):
    with pytest.raises(LinkNotFoundError):
        repo.get("nope")


def test_exists_reflects_membership(repo):
    assert not repo.exists("abc")
    repo.add(short_code="abc", url="https://example.com")
    assert repo.exists("abc")


def test_add_duplicate_code_raises(repo):
    repo.add(short_code="abc", url="https://example.com")
    with pytest.raises(ValueError):
        repo.add(short_code="abc", url="https://other.com")


def test_increment_clicks_counts_up(repo):
    repo.add(short_code="abc", url="https://example.com")
    repo.increment_clicks("abc")
    repo.increment_clicks("abc")
    assert repo.get("abc").clicks == 2


def test_increment_clicks_missing_raises(repo):
    with pytest.raises(LinkNotFoundError):
        repo.increment_clicks("nope")
