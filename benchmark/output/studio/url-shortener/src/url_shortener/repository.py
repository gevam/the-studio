"""Persistence layer (LinkRepository injection point, design v3).

SQLite-backed implementation behind a Protocol so the storage backend is an
injectable seam. The walking skeleton proves real persistence (a fresh
repository instance over the same file resolves a previously stored code).
"""

from __future__ import annotations

import sqlite3
from typing import Protocol

from url_shortener.models import ShortLink


class LinkRepository(Protocol):
    def save(self, link: ShortLink) -> None: ...
    def resolve(self, code: str) -> str | None: ...


class SqliteLinkRepository:
    """Stores ShortLinks in a SQLite database file."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS short_links (
                    code TEXT PRIMARY KEY,
                    long_url TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    owner_id TEXT
                )
                """
            )

    def save(self, link: ShortLink) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO short_links (code, long_url, created_at, owner_id) "
                "VALUES (?, ?, ?, ?)",
                (link.code, link.long_url, link.created_at.isoformat(), link.owner_id),
            )

    def resolve(self, code: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT long_url FROM short_links WHERE code = ?", (code,)
            ).fetchone()
        return row[0] if row else None
