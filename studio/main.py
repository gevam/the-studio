"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from studio.api.middleware import setup_middleware
from studio.api.routes.health import router as health_router
from studio.api.websocket import router as ws_router
from studio.config import settings
from studio.observability.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    import structlog

    log = structlog.get_logger(__name__)
    log.info("studio_starting", environment=settings.environment, version="0.1.0")
    yield
    log.info("studio_stopping")


app = FastAPI(
    title="The Studio",
    description="AI-native software development orchestrator",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

setup_middleware(app)
app.include_router(health_router)
app.include_router(ws_router)
