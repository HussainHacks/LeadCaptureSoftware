from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Root directory of the repository (contains .env and infrastructure/)
def _find_root_dir() -> Path:
    current = Path(__file__).resolve().parent
    for _ in range(6):
        if (current / ".env").exists() or (current / "infrastructure").exists():
            return current
        current = current.parent
    return Path.cwd().parent if Path.cwd().name == "backend" else Path.cwd()


ROOT_DIR = _find_root_dir()


class Settings(BaseSettings):
    """Application settings loaded from environment and root .env."""

    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General Settings
    PROJECT_NAME: str = "HVAC Lead Conversion Platform"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "dev-insecure-secret-key-replace-in-env"
    API_V1_PREFIX: str = "/api"
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_URL: str = "http://localhost:8000"

    # Database Settings
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "leadgen"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/leadgen"
    )
    DATABASE_URL_SYNC: str | None = None

    # Redis Settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # n8n Automation Engine
    N8N_PORT: int = 5678
    N8N_HOST: str = "localhost"
    N8N_PROTOCOL: str = "http"
    N8N_ENCRYPTION_KEY: str = "default-dev-n8n-key"
    N8N_WEBHOOK_URL: str = "http://localhost:5678/"

    # AI Configuration
    AI_PROVIDER: str = "openai"
    OPENAI_API_KEY: str = "sk-placeholder"
    AI_MODEL_NAME: str = "gpt-4o-mini"
    AI_QUALIFICATION_TIMEOUT_SECONDS: int = 15

    # Messaging Configuration
    MESSAGING_MODE: str = "simulated"
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_PHONE_NUMBER: str | None = None

    # Calendar Configuration
    CALENDAR_MODE: str = "simulated"

    # Internal Security
    INTERNAL_API_KEY: str = "dev-internal-key"
    LOG_LEVEL: str = "INFO"

    # Demo Mode (strictly disabled by default; never enable in production)
    DEMO_ENABLED: bool = False
    DEMO_PASSWORD: str | None = None

    @model_validator(mode="after")
    def _validate_demo_mode(self) -> "Settings":
        if self.DEMO_ENABLED:
            if self.ENVIRONMENT.lower() == "production":
                raise ValueError("DEMO_ENABLED must never be true in production.")
            if not self.DEMO_PASSWORD or not self.DEMO_PASSWORD.strip():
                raise ValueError("DEMO_PASSWORD must be set when DEMO_ENABLED is true.")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
