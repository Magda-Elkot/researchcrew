"""Typed application settings loaded from environment variables (and an optional .env file).

Keys are optional at import time so `/health`, tests and CI work without secrets.
Entry points (API lifespan, CLI) call `require()` to fail fast with a clear message.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


class Settings(BaseSettings):
    """All configuration used so far. Later phases add their own fields."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_model: str = "groq/llama-3.3-70b-versatile"
    groq_api_key: SecretStr | None = None
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "documents"
    log_level: str = "INFO"
    app_version: str = __version__


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (cached; tests call `get_settings.cache_clear()`)."""
    return Settings()


def require(*names: str) -> None:
    """Raise ConfigError naming the first env var in `names` that is unset or empty."""
    settings = get_settings()
    for name in names:
        field = name.lower()
        if field not in Settings.model_fields:
            raise ConfigError(f"Unknown setting: {name}")
        value = getattr(settings, field)
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if value is None or value == "":
            raise ConfigError(f"Missing required environment variable: {name}")


def secret_values() -> list[str]:
    """Return the non-empty secret values currently loaded, so logs can scrub them."""
    settings = get_settings()
    values: list[str] = []
    for field in Settings.model_fields:
        value = getattr(settings, field)
        if isinstance(value, SecretStr) and value.get_secret_value():
            values.append(value.get_secret_value())
    return values
