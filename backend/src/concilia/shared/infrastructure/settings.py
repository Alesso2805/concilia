from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONCILIA_", extra="ignore")

    database_url: str


class ApiSettings(DatabaseSettings):
    public_origin: str = "https://localhost"
    csrf_secret: SecretStr
    rate_limit_secret: SecretStr
    registration_enabled: bool = False
    login_window_minutes: int = 15
    login_max_per_email: int = 10
    login_max_per_ip: int = 30
    demo_ttl_hours: int = Field(default=0, ge=0)
    demo_max_per_ip_per_day: int = 5
    demo_max_per_day: int = 300


class WorkerSettings(DatabaseSettings):
    worker_concurrency: int = 2
    worker_poll_interval_seconds: float = 1.0
