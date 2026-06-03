"""Application configuration.

All tunable values live here so the rest of the codebase contains no
magic numbers. Settings can be overridden from the environment (prefix
``URLSHORT_``) or constructed explicitly in tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields

# Defaults (named constants, not magic numbers scattered across the code).
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_SHORT_CODE_LENGTH = 7
DEFAULT_MAX_CODE_GENERATION_ATTEMPTS = 10
DEFAULT_RATE_LIMIT_MAX_REQUESTS = 100
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60.0

_ENV_PREFIX = "URLSHORT_"


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    base_url: str = DEFAULT_BASE_URL
    short_code_length: int = DEFAULT_SHORT_CODE_LENGTH
    max_code_generation_attempts: int = DEFAULT_MAX_CODE_GENERATION_ATTEMPTS
    rate_limit_max_requests: int = DEFAULT_RATE_LIMIT_MAX_REQUESTS
    rate_limit_window_seconds: float = DEFAULT_RATE_LIMIT_WINDOW_SECONDS

    def __post_init__(self) -> None:
        if self.short_code_length <= 0:
            raise ValueError("short_code_length must be positive")
        if self.max_code_generation_attempts <= 0:
            raise ValueError("max_code_generation_attempts must be positive")

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "Settings":
        """Build settings from environment variables, falling back to defaults."""
        env = os.environ if environ is None else environ
        values: dict[str, object] = {}
        for field in fields(cls):
            raw = env.get(f"{_ENV_PREFIX}{field.name.upper()}")
            if raw is None:
                continue
            caster = field.type
            # dataclass stores annotations as strings under `from __future__`.
            if caster == "int":
                values[field.name] = int(raw)
            elif caster == "float":
                values[field.name] = float(raw)
            else:
                values[field.name] = raw
        return cls(**values)  # type: ignore[arg-type]
