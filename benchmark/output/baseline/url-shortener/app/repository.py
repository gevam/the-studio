"""Storage abstraction for shortened links.

A ``LinkRepository`` Protocol decouples the service layer from storage, so
the in-memory implementation here can later be swapped for a database-backed
one without touching business logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


class LinkNotFoundError(KeyError):
    """Raised when a short code is not present in the repository."""


@dataclass
class LinkRecord:
    """A single shortened link and its click tally."""

    short_code: str
    url: str
    clicks: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class LinkRepository(Protocol):
    """Persistence contract for shortened links."""

    def add(self, short_code: str, url: str) -> LinkRecord: ...

    def get(self, short_code: str) -> LinkRecord: ...

    def exists(self, short_code: str) -> bool: ...

    def increment_clicks(self, short_code: str) -> None: ...


class InMemoryLinkRepository:
    """Process-local, dictionary-backed implementation of ``LinkRepository``."""

    def __init__(self) -> None:
        self._links: dict[str, LinkRecord] = {}

    def add(self, short_code: str, url: str) -> LinkRecord:
        if short_code in self._links:
            raise ValueError(f"short_code already exists: {short_code}")
        record = LinkRecord(short_code=short_code, url=url)
        self._links[short_code] = record
        return record

    def get(self, short_code: str) -> LinkRecord:
        try:
            return self._links[short_code]
        except KeyError as exc:
            raise LinkNotFoundError(short_code) from exc

    def exists(self, short_code: str) -> bool:
        return short_code in self._links

    def increment_clicks(self, short_code: str) -> None:
        self.get(short_code).clicks += 1
