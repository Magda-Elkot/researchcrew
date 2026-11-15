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

    llm_model: str = "groq/openai/gpt-oss-120b"  # DECISIONS #67
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

    # --- MCP clients used by the agents (Phase 3) ---
    tavily_api_key: SecretStr | None = None
    # Tavily's hosted MCP server; the key is sent in a header, never in this URL.
    tavily_mcp_url: str = "https://mcp.tavily.com/mcp/"
    # Where the agents reach docs-mcp (compose overrides this for the api container).
    docs_mcp_url: str = "http://127.0.0.1:8001/mcp"
    # The only folder the filesystem MCP server may read.
    notes_dir: str = "data/notes"
    # Pinned npm package for the filesystem MCP server (run with npx, read-only).
    filesystem_mcp_package: str = "@modelcontextprotocol/server-filesystem@2.3.0"
    # How to start it: "npx" downloads the pinned package on first use (local runs); any other
    # value is an installed command (the api image installs `mcp-server-filesystem`).
    filesystem_mcp_command: str = "npx"
    # Seconds to wait for an MCP server to connect.
    mcp_connect_timeout: int = Field(default=30, gt=0)
    # Size limits on what MCP tools hand back to the LLM (Groq free tier: 8K tokens/min,
    # and one request may not exceed that). DECISIONS #68.
    mcp_search_top_k: int = Field(default=3, ge=1, le=20)  # hits per search_documents call
    mcp_max_item_chars: int = Field(default=1200, ge=200)  # text per hit when a result has many
    mcp_max_result_chars: int = Field(default=6000, ge=2000)  # whole tool result

    # --- Crew runs (Phase 3b) ---
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    # Provider tokens-per-minute limit; LLM calls are paced to stay below it (0 = no pacing).
    llm_tokens_per_minute: int = Field(default=8000, ge=0)
    # Seconds before one LLM request is abandoned, and how often LiteLLM retries a request at
    # once (for dropped connections and timeouts; its default wait is 600 s, which froze a run).
    # Keep it low: LiteLLM also retries rate-limit errors immediately, which can't succeed.
    llm_timeout_s: int = Field(default=90, gt=0)
    llm_num_retries: int = Field(default=1, ge=0)
    # Longest wait on a provider's retry-after before retrying (a daily limit asks for minutes;
    # better to fail with a clear message than to look frozen).
    llm_max_retry_wait_s: int = Field(default=60, gt=0)
    # SPEC per-run limits: 15 minutes, 25 tool calls (quick runs use fewer, DECISIONS #73).
    run_timeout_s: int = Field(default=900, gt=0)
    max_tool_calls: int = Field(default=25, gt=0)
    # Where the CLI writes <id>.json and <id>.md.
    outputs_dir: str = "outputs"

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> Self:
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_TOKENS")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (cached; tests call `get_settings.cache_clear()`)."""
    return Settings()


def _is_placeholder(value: str) -> bool:
    """True for the `your-...-here` values used in .env.example."""
    lowered = value.strip().lower()
    return lowered.startswith("your-") and lowered.endswith("-here")


def require(*names: str) -> None:
    """Raise ConfigError naming the first env var in `names` that is unset, empty or placeholder."""
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
        if isinstance(value, str) and _is_placeholder(value):
            raise ConfigError(
                f"Environment variable {name} still has the placeholder value from "
                ".env.example; set a real value in .env"
            )


def secret_values() -> list[str]:
    """Return the non-empty secret values currently loaded, so logs can scrub them."""
    settings = get_settings()
    values: list[str] = []
    for field in Settings.model_fields:
        value = getattr(settings, field)
        if isinstance(value, SecretStr) and value.get_secret_value():
            values.append(value.get_secret_value())
    return values
