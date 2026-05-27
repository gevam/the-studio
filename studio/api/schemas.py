"""Pydantic request/response schemas for the REST API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class SessionStatus(BaseModel):
    id: UUID
    name: str
    description: str | None
    status: str
    version: int
    current_node: str | None
    current_loop: str | None
    iteration: int
    tokens_used: int
    cost_usd: float
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    sessions: list[SessionStatus]
    total: int


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    db: bool
    redis: bool
