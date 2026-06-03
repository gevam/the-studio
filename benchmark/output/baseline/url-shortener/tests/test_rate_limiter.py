"""Unit tests for the sliding-window rate limiter (app.rate_limiter)."""
import pytest

from app.rate_limiter import SlidingWindowRateLimiter


class FakeClock:
    """A controllable monotonic clock for deterministic time-based tests."""

    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_limiter(max_requests, window_seconds, clock):
    return SlidingWindowRateLimiter(
        max_requests=max_requests,
        window_seconds=window_seconds,
        time_func=clock,
    )


def test_allows_up_to_the_limit():
    clock = FakeClock()
    limiter = make_limiter(max_requests=3, window_seconds=60, clock=clock)
    assert [limiter.allow("ip") for _ in range(3)] == [True, True, True]


def test_blocks_once_limit_exceeded():
    clock = FakeClock()
    limiter = make_limiter(max_requests=2, window_seconds=60, clock=clock)
    limiter.allow("ip")
    limiter.allow("ip")
    assert limiter.allow("ip") is False


def test_window_slides_and_frees_capacity():
    clock = FakeClock()
    limiter = make_limiter(max_requests=2, window_seconds=60, clock=clock)
    limiter.allow("ip")
    limiter.allow("ip")
    assert limiter.allow("ip") is False
    clock.advance(61)  # both earlier hits fall out of the window
    assert limiter.allow("ip") is True


def test_keys_are_isolated():
    clock = FakeClock()
    limiter = make_limiter(max_requests=1, window_seconds=60, clock=clock)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    assert limiter.allow("a") is False


def test_retry_after_reports_seconds_until_capacity():
    clock = FakeClock()
    limiter = make_limiter(max_requests=1, window_seconds=60, clock=clock)
    limiter.allow("ip")
    clock.advance(10)
    assert limiter.allow("ip") is False
    assert limiter.retry_after("ip") == pytest.approx(50)


def test_retry_after_is_zero_when_capacity_available():
    clock = FakeClock()
    limiter = make_limiter(max_requests=2, window_seconds=60, clock=clock)
    limiter.allow("ip")  # one slot used, one free
    assert limiter.retry_after("ip") == 0.0


@pytest.mark.parametrize("bad", [0, -1])
def test_rejects_non_positive_max_requests(bad):
    with pytest.raises(ValueError):
        make_limiter(max_requests=bad, window_seconds=60, clock=FakeClock())


@pytest.mark.parametrize("bad", [0, -5])
def test_rejects_non_positive_window(bad):
    with pytest.raises(ValueError):
        make_limiter(max_requests=1, window_seconds=bad, clock=FakeClock())
