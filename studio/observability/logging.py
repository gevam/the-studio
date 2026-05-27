"""structlog configuration (§7.1)."""

import re

import structlog


# --- Custom processors ---

_PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
]

_SECRET_PATTERNS = [
    (re.compile(r"(sk-[A-Za-z0-9]{20,})", re.IGNORECASE), "[API_KEY]"),
    (re.compile(r"(Bearer\s+[A-Za-z0-9._~+/=-]{20,})", re.IGNORECASE), "[BEARER_TOKEN]"),
    (re.compile(r"(password|passwd|secret|token)\s*[:=]\s*\S+", re.IGNORECASE), r"\1=[REDACTED]"),
]


def pii_masker(_logger: object, _method: str, event_dict: dict) -> dict:
    """Mask PII values in log event strings."""
    event = str(event_dict.get("event", ""))
    for pattern, replacement in _PII_PATTERNS:
        event = pattern.sub(replacement, event)
    event_dict["event"] = event
    return event_dict


def secret_masker(_logger: object, _method: str, event_dict: dict) -> dict:
    """Mask API keys and tokens in log event strings."""
    event = str(event_dict.get("event", ""))
    for pattern, replacement in _SECRET_PATTERNS:
        event = re.sub(pattern, replacement, event)
    event_dict["event"] = event
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog with processors from §7.1."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            pii_masker,
            secret_masker,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(__import__("logging"), log_level.upper(), 20)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
