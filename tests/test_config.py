"""Tests for app.config: env loading, defaults and require()."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import __version__
from app.config import ConfigError, Settings, get_settings, require, secret_values
from frontend.client import FrontendSettings


def test_defaults() -> None:
    settings = get_settings()
    assert settings.llm_model == "groq/openai/gpt-oss-120b"
    assert settings.groq_api_key is None
    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.qdrant_collection == "documents"
    assert settings.log_level == "INFO"
    assert settings.app_version == __version__


def test_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    settings = get_settings()
    assert settings.qdrant_url == "http://qdrant:6333"
    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == "gsk-test"


def test_dotenv_file_is_read(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("QDRANT_COLLECTION=from_dotenv\n")
    assert get_settings().qdrant_collection == "from_dotenv"


def test_secret_is_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk-very-secret")
    assert "gsk-very-secret" not in repr(get_settings())


def test_require_passes_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    require("GROQ_API_KEY", "QDRANT_URL")


def test_require_names_missing_variable() -> None:
    with pytest.raises(ConfigError, match="Missing required environment variable: GROQ_API_KEY"):
        require("GROQ_API_KEY")


def test_require_treats_empty_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "")
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        require("GROQ_API_KEY")


@pytest.mark.parametrize("value", ["your-groq-api-key-here", "  YOUR-Tavily-Key-HERE "])
def test_require_rejects_env_example_placeholder(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", value)
    with pytest.raises(ConfigError, match="GROQ_API_KEY still has the placeholder value"):
        require("GROQ_API_KEY")


def test_require_accepts_real_looking_values(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only the full `your-...-here` shape is a placeholder.
    monkeypatch.setenv("GROQ_API_KEY", "your-real-key")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-here")
    require("GROQ_API_KEY", "TAVILY_API_KEY")


def test_require_rejects_unknown_name() -> None:
    with pytest.raises(ConfigError, match="Unknown setting: NOPE"):
        require("NOPE")


def test_require_with_no_names_is_a_noop() -> None:
    require()


def test_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    assert secret_values() == []
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    get_settings.cache_clear()
    assert secret_values() == ["gsk-test"]


# --- docs-mcp settings (Phase 2) ---


def test_docs_mcp_defaults() -> None:
    settings = get_settings()
    assert settings.embedding_model == "BAAI/bge-m3"
    assert settings.embedding_dim == 1024
    assert (settings.chunk_tokens, settings.chunk_overlap) == (800, 100)
    assert settings.model_cache_dir is None
    assert settings.embedding_threads == 4
    assert (settings.docs_mcp_host, settings.docs_mcp_port) == ("127.0.0.1", 8001)


def test_empty_env_value_means_unset(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("MODEL_CACHE_DIR=\nCHUNK_TOKENS=\n")
    settings = get_settings()
    assert settings.model_cache_dir is None
    assert settings.chunk_tokens == 800


def test_overlap_must_be_smaller_than_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHUNK_TOKENS", "100")
    monkeypatch.setenv("CHUNK_OVERLAP", "100")
    with pytest.raises(ValidationError, match="CHUNK_OVERLAP must be smaller"):
        Settings()


@pytest.mark.parametrize(("name", "value"), [("DOCS_MCP_PORT", "70000"), ("EMBEDDING_DIM", "0")])
def test_invalid_numbers_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_mcp_client_defaults() -> None:
    settings = get_settings()
    assert settings.tavily_api_key is None
    assert settings.tavily_mcp_url == "https://mcp.tavily.com/mcp/"
    assert settings.docs_mcp_url == "http://127.0.0.1:8001/mcp"
    assert settings.notes_dir == "data/notes"
    assert settings.filesystem_mcp_package == "@modelcontextprotocol/server-filesystem@2.3.0"
    assert settings.filesystem_mcp_command == "npx"
    assert settings.mcp_connect_timeout == 30
    assert settings.mcp_search_top_k == 3
    assert settings.mcp_max_item_chars == 1200
    assert settings.mcp_max_result_chars == 6000


def test_run_defaults() -> None:
    settings = get_settings()
    assert settings.llm_temperature == 0.2
    assert settings.llm_tokens_per_minute == 8000
    assert settings.llm_timeout_s == 90
    assert settings.llm_num_retries == 1
    assert settings.llm_max_retry_wait_s == 60
    assert settings.run_timeout_s == 900
    assert settings.max_tool_calls == 25
    assert settings.outputs_dir == "outputs"


def test_tavily_key_is_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-very-secret")
    settings = get_settings()
    assert "tvly-very-secret" not in repr(settings)
    assert "tvly-very-secret" in secret_values()


def test_mcp_connect_timeout_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_CONNECT_TIMEOUT", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_embedding_threads_zero_means_all_cores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_THREADS", "0")
    assert Settings().embedding_threads == 0
    monkeypatch.setenv("EMBEDDING_THREADS", "-1")
    with pytest.raises(ValidationError):
        Settings()


def test_every_setting_is_documented_in_env_example() -> None:
    # CLAUDE.md: all variables go in .env.example (a Phase 5 setting was once forgotten).
    example = (Path(__file__).parents[1] / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^([A-Z_][A-Z0-9_]*)=", example, re.MULTILINE))
    fields = {*Settings.model_fields, *FrontendSettings.model_fields}
    assert {name.upper() for name in fields} - documented == set()
