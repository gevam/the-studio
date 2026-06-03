"""Domain data models for the walking skeleton.

Only the ShortLink entity is needed for the first vertical slice (Shorten a URL).
ClickEvent / ClickStats (design v3) are intentionally deferred — walking
skeleton builds one thin slice, not the whole data model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ShortLink:
    """A persisted mapping from a short code to a long URL."""

    code: str
    long_url: str
    created_at: datetime
    owner_id: str | None = None
