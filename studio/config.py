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
