"""Unit tests for application settings (app.config)."""
import pytest

from app.config import Settings


def test_defaults_are_sane():
    s = Settings()
    assert s.short_code_length > 0
    assert s.rate_limit_max_requests > 0
    assert s.rate_limit_window_seconds > 0


def test_from_env_overrides_typed_fields():
    env = {
        "URLSHORT_BASE_URL": "https://sho.rt",
        "URLSHORT_SHORT_CODE_LENGTH": "9",
        "URLSHORT_RATE_LIMIT_MAX_REQUESTS": "5",
        "URLSHORT_RATE_LIMIT_WINDOW_SECONDS": "30.5",
    }
    s = Settings.from_env(env)
    assert s.base_url == "https://sho.rt"
    assert s.short_code_length == 9
    assert s.rate_limit_max_requests == 5
    assert s.rate_limit_window_seconds == 30.5


def test_from_env_falls_back_to_defaults_when_unset():
    s = Settings.from_env({})
    assert s == Settings()


@pytest.mark.parametrize("length", [0, -3])
def test_rejects_non_positive_short_code_length(length):
    with pytest.raises(ValueError):
        Settings(short_code_length=length)


def test_rejects_non_positive_generation_attempts():
    with pytest.raises(ValueError):
        Settings(max_code_generation_attempts=0)
