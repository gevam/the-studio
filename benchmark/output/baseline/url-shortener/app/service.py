"""Business logic for shortening and resolving links."""
from __future__ import annotations

from app.codec import generate_code
from app.config import Settings
from app.repository import LinkRecord, LinkRepository


class ShortenerService:
    """Coordinates code generation, persistence, and click accounting."""

    def __init__(self, repository: LinkRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    def _generate_code(self) -> str:
        return generate_code(length=self._settings.short_code_length)

    def shorten(self, url: str) -> LinkRecord:
        """Create a short code for ``url``, retrying on the rare code collision.

        Raises:
            RuntimeError: if a free code could not be found within the
                configured number of attempts.
        """
        for _ in range(self._settings.max_code_generation_attempts):
            code = self._generate_code()
            if not self._repository.exists(code):
                return self._repository.add(short_code=code, url=url)
        raise RuntimeError(
            "could not generate a unique short code within "
            f"{self._settings.max_code_generation_attempts} attempts"
        )

    def resolve(self, short_code: str) -> LinkRecord:
        """Return the link for ``short_code`` and count the visit.

        Raises:
            LinkNotFoundError: if the code is unknown.
        """
        record = self._repository.get(short_code)
        self._repository.increment_clicks(short_code)
        return record

    def get_stats(self, short_code: str) -> LinkRecord:
        """Return the link record without counting a visit.

        Raises:
            LinkNotFoundError: if the code is unknown.
        """
        return self._repository.get(short_code)
