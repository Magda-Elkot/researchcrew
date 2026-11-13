"""Typed application settings loaded from environment variables (and an optional .env file).

Keys are optional at import time so `/health`, tests and CI work without secrets.
Entry points (API lifespan, CLI) call `require()` to fail fast with a clear message.
"""

from functools import lru_cache
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


class Settings(BaseSettings):
    """All configuration used so far. Later phases add their own fields."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,  # `VAR=` in .env means "unset", not ""
    )

    llm_model: str = "groq/llama-3.3-70b-versatile"
    groq_api_key: SecretStr | None = None
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "documents"
    log_level: str = "INFO"
    app_version: str = __version__

    # --- docs-mcp (Phase 2) ---
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = Field(default=1024, gt=0)
    chunk_tokens: int = Field(default=800, gt=0)
    chunk_overlap: int = Field(default=100, ge=0)
    model_cache_dir: str | None = None  # None = Hugging Face default (~/.cache/huggingface)
    # CPU threads for embedding. Fewer = slower ingest but a responsive machine; 0 = all cores.
    embedding_threads: int = Field(default=4, ge=0)
    docs_mcp_host: str = "127.0.0.1"
    docs_mcp_port: int = Field(default=8001, gt=0, le=65535)

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> Self:
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_TOKENS")
        return self


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
