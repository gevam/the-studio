"""Unit tests for the shortener service layer (app.service)."""
import pytest

from app.config import Settings
from app.repository import InMemoryLinkRepository, LinkNotFoundError
from app.service import ShortenerService


@pytest.fixture
def service():
    settings = Settings(short_code_length=6)
    return ShortenerService(repository=InMemoryLinkRepository(), settings=settings)


def test_shorten_returns_record_with_code(service):
    record = service.shorten("https://example.com")
    assert len(record.short_code) == 6
    assert record.url == "https://example.com"
    assert record.clicks == 0


def test_shorten_persists_and_is_resolvable(service):
    record = service.shorten("https://example.com")
    resolved = service.resolve(record.short_code)
    assert resolved.url == "https://example.com"


def test_resolve_increments_click_count(service):
    code = service.shorten("https://example.com").short_code
    service.resolve(code)
    service.resolve(code)
    assert service.get_stats(code).clicks == 2


def test_get_stats_does_not_increment(service):
    code = service.shorten("https://example.com").short_code
    service.get_stats(code)
    assert service.get_stats(code).clicks == 0


def test_resolve_unknown_code_raises(service):
    with pytest.raises(LinkNotFoundError):
        service.resolve("missing")


def test_shorten_retries_on_code_collision():
    """If the generator first yields a taken code, the service retries."""
    settings = Settings(short_code_length=4, max_code_generation_attempts=5)
    repo = InMemoryLinkRepository()
    service = ShortenerService(repository=repo, settings=settings)

    codes = iter(["DUPED", "DUPED", "FRESH"])
    service._generate_code = lambda: next(codes)  # type: ignore[method-assign]

    first = service.shorten("https://a.com")
    second = service.shorten("https://b.com")
    assert first.short_code == "DUPED"
    assert second.short_code == "FRESH"


def test_shorten_gives_up_after_max_attempts():
    settings = Settings(short_code_length=4, max_code_generation_attempts=3)
    repo = InMemoryLinkRepository()
    service = ShortenerService(repository=repo, settings=settings)
    service._generate_code = lambda: "SAME"  # type: ignore[method-assign]

    service.shorten("https://a.com")
    with pytest.raises(RuntimeError):
        service.shorten("https://b.com")
