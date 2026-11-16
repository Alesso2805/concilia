from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONCILIA_", extra="ignore")

    database_url: str


class WorkerSettings(DatabaseSettings):
    worker_concurrency: int = 2
    worker_poll_interval_seconds: float = 1.0
