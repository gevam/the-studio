"""Middleware: REST API gate (503 when disabled), CORS, error handling."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from studio.config import settings

# Paths that bypass the REST gate (always allowed)
_ALWAYS_ALLOWED = frozenset(["/health", "/ready", "/metrics"])
_ALWAYS_ALLOWED_PREFIXES = ("/ws/", "/docs", "/openapi")


class RestApiGateMiddleware(BaseHTTPMiddleware):
    """Return 503 for all API routes when rest_api_enabled is False.

    Health/metrics/WebSocket paths are exempt so the system remains
    observable and connectable even when the REST API is turned off.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in _ALWAYS_ALLOWED:
            return await call_next(request)
        if any(path.startswith(p) for p in _ALWAYS_ALLOWED_PREFIXES):
            return await call_next(request)
        if not settings.rest_api_enabled:
            return JSONResponse(
                {"detail": "REST API is disabled. Set REST_API_ENABLED=true to enable."},
                status_code=503,
            )
        return await call_next(request)


def setup_middleware(app: FastAPI) -> None:
    """Attach all middleware to the FastAPI app."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RestApiGateMiddleware)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        import structlog

        log = structlog.get_logger(__name__)
        log.exception("unhandled_exception", path=request.url.path, exc=str(exc))
        return JSONResponse({"detail": "Internal server error"}, status_code=500)
