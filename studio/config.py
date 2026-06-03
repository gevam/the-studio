from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://studio:studio@localhost:5432/studio"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Runtime
    environment: str = "local"
    log_level: str = "INFO"

    # Feature flags
    rest_api_enabled: bool = True

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Per-agent provider routing (§4.4, §13 #4). Reviewer defaults to a different
    # model family from the other agents; falls back gracefully if its key/SDK is
    # absent (see studio/ai/registry.py). Override via env, e.g. REVIEWER_PROVIDER.
    default_provider: str = "anthropic"  # "anthropic" | "claude_cli" | "openai"
    default_model: str = "claude-sonnet-4-6"
    reviewer_provider: str = "openai"
    reviewer_model: str = "gpt-4o"

    # Budgets
    default_token_budget: int = 500_000
    default_cost_budget: float = 50.0

    # Worker
    worker_concurrency: int = 10

    @property
    def is_local(self) -> bool:
        return self.environment == "local"

    @property
    def sync_database_url(self) -> str:
        """Synchronous DB URL for Alembic migrations."""
        return self.database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"
        )


settings = Settings()
