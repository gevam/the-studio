"""Tests for studio.config module."""


def test_settings_loads():
    """Settings object loads and has all expected fields."""
    from studio.config import settings

    assert settings.environment is not None
    assert settings.database_url.startswith("postgresql")
    assert settings.redis_url.startswith("redis://")
    assert isinstance(settings.rest_api_enabled, bool)
    assert settings.default_token_budget > 0
    assert settings.default_cost_budget > 0


def test_sync_database_url():
    """sync_database_url replaces asyncpg driver for Alembic."""
    from studio.config import settings

    sync_url = settings.sync_database_url
    assert "psycopg2" in sync_url
    assert "asyncpg" not in sync_url


def test_is_local_in_test_env():
    """is_local returns False for 'test' environment."""
    import os

    os.environ["ENVIRONMENT"] = "test"
    from importlib import reload

    import studio.config as cfg_module

    reload(cfg_module)
    assert not cfg_module.settings.is_local
