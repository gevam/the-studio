"""Pydantic I/O contracts for the HTTP API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class ShortenRequest(BaseModel):
    """Request body for creating a short link."""

    url: HttpUrl = Field(..., description="Absolute http(s) URL to shorten.")


class ShortenResponse(BaseModel):
    """Response returned after creating a short link."""

    short_code: str
    short_url: str
    url: str


class StatsResponse(BaseModel):
    """Click statistics for a short link."""

    short_code: str
    url: str
    clicks: int
    created_at: datetime
