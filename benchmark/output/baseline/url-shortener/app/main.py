"""FastAPI application factory and HTTP routes."""
from __future__ import annotations

import math

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.config import Settings
from app.models import ShortenRequest, ShortenResponse, StatsResponse
from app.rate_limiter import SlidingWindowRateLimiter
from app.repository import InMemoryLinkRepository, LinkNotFoundError, LinkRepository
from app.service import ShortenerService

_UNKNOWN_CLIENT = "unknown"


def _client_key(request: Request) -> str:
    """Identify the caller for rate-limiting purposes."""
    return request.client.host if request.client else _UNKNOWN_CLIENT


def create_app(
    settings: Settings | None = None,
    repository: LinkRepository | None = None,
    rate_limiter: SlidingWindowRateLimiter | None = None,
) -> FastAPI:
    """Build a fully wired application.

    Dependencies are injectable so tests can supply strict limits or
    pre-seeded storage.
    """
    settings = settings or Settings.from_env()
    repository = repository or InMemoryLinkRepository()
    rate_limiter = rate_limiter or SlidingWindowRateLimiter(
        max_requests=settings.rate_limit_max_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    service = ShortenerService(repository=repository, settings=settings)

    app = FastAPI(title="URL Shortener", version="1.0.0")

    def enforce_rate_limit(request: Request) -> None:
        key = _client_key(request)
        if not rate_limiter.allow(key):
            retry_after = math.ceil(rate_limiter.retry_after(key))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )

    rate_limited = Depends(enforce_rate_limit)

    @app.get("/health", dependencies=[rate_limited])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/shorten",
        response_model=ShortenResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[rate_limited],
    )
    def shorten(payload: ShortenRequest) -> ShortenResponse:
        record = service.shorten(str(payload.url))
        short_url = f"{settings.base_url.rstrip('/')}/{record.short_code}"
        return ShortenResponse(
            short_code=record.short_code,
            short_url=short_url,
            url=record.url,
        )

    @app.get("/stats/{short_code}", response_model=StatsResponse, dependencies=[rate_limited])
    def stats(short_code: str) -> StatsResponse:
        try:
            record = service.get_stats(short_code)
        except LinkNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Short code not found"
            )
        return StatsResponse(
            short_code=record.short_code,
            url=record.url,
            clicks=record.clicks,
            created_at=record.created_at,
        )

    # Catch-all redirect — declared last so it never shadows the routes above.
    @app.get("/{short_code}", dependencies=[rate_limited])
    def redirect(short_code: str) -> RedirectResponse:
        try:
            record = service.resolve(short_code)
        except LinkNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Short code not found"
            )
        return RedirectResponse(
            url=record.url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
        )

    return app


# Module-level app for ``uvicorn app.main:app``.
app = create_app()
