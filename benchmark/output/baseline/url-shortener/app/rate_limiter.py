"""Sliding-window rate limiting.

Each caller key (typically a client IP) keeps a log of request timestamps.
A request is allowed when fewer than ``max_requests`` have occurred within
the trailing ``window_seconds``. The clock is injectable so behaviour is
fully deterministic under test.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, Deque


class SlidingWindowRateLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._time = time_func
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    def _evict_expired(self, key: str, now: float) -> Deque[float]:
        """Drop timestamps that have aged out of the window and return the log."""
        hits = self._hits[key]
        cutoff = now - self._window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def allow(self, key: str) -> bool:
        """Record and permit a request, or refuse it if the key is over budget."""
        now = self._time()
        hits = self._evict_expired(key, now)
        if len(hits) >= self._max_requests:
            return False
        hits.append(now)
        return True

    def retry_after(self, key: str) -> float:
        """Seconds until the oldest in-window hit expires (0 if capacity is free)."""
        now = self._time()
        hits = self._evict_expired(key, now)
        if len(hits) < self._max_requests:
            return 0.0
        return (hits[0] + self._window_seconds) - now
