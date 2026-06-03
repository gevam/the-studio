"""ShortenService (design v3): generate + persist a short code for a long URL.

Dependencies (LinkRepository, CodeGenerator) are injected, matching the design's
injection points. URL validation is intentionally minimal for the skeleton.
"""

from __future__ import annotations

from datetime import UTC, datetime

from url_shortener.codegen import CodeGenerator
from url_shortener.models import ShortLink
from url_shortener.repository import LinkRepository


class InvalidURLError(ValueError):
    """Raised when a long URL is not an acceptable http(s) URL."""


class ShortenService:
    def __init__(self, repository: LinkRepository, codes: CodeGenerator) -> None:
        self._repository = repository
        self._codes = codes

    def shorten(self, long_url: str, owner_id: str | None = None) -> ShortLink:
        if not long_url.startswith(("http://", "https://")):
            raise InvalidURLError(long_url)
        link = ShortLink(
            code=self._codes.generate(),
            long_url=long_url,
            created_at=datetime.now(UTC),
            owner_id=owner_id,
        )
        self._repository.save(link)
        return link
