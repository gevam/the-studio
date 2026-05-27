"""Tests for studio.observability.logging module."""

import re


def test_configure_logging_does_not_raise():
    """configure_logging() initialises structlog without errors."""
    from studio.observability.logging import configure_logging

    configure_logging("DEBUG")
    configure_logging("INFO")


def test_pii_masker_masks_email():
    """pii_masker replaces email addresses with [EMAIL]."""
    from studio.observability.logging import pii_masker

    event_dict = {"event": "user moti@example.com logged in"}
    result = pii_masker(None, None, event_dict)
    assert "[EMAIL]" in result["event"]
    assert "moti@example.com" not in result["event"]


def test_pii_masker_masks_ssn():
    """pii_masker replaces SSN patterns."""
    from studio.observability.logging import pii_masker

    event_dict = {"event": "SSN is 123-45-6789"}
    result = pii_masker(None, None, event_dict)
    assert "[SSN]" in result["event"]


def test_secret_masker_masks_api_key():
    """secret_masker replaces API key patterns."""
    from studio.observability.logging import secret_masker

    event_dict = {"event": "Using key sk-abcdefghijklmnopqrstuvwxyz12345"}
    result = secret_masker(None, None, event_dict)
    assert "[API_KEY]" in result["event"]
    assert "sk-abcdefghijklmnopqrstuvwxyz12345" not in result["event"]


def test_logger_can_be_obtained_after_configure():
    """structlog.get_logger() works after configure_logging()."""
    import structlog

    from studio.observability.logging import configure_logging

    configure_logging()
    log = structlog.get_logger("test")
    assert log is not None
