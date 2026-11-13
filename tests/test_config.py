"""Tests for app.config: env loading, defaults and require()."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app import __version__
from app.config import ConfigError, Settings, get_settings, require, secret_values


def test_defaults() -> None:
    settings = get_settings()
    assert settings.llm_model == "groq/llama-3.3-70b-versatile"
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


def test_embedding_threads_zero_means_all_cores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_THREADS", "0")
    assert Settings().embedding_threads == 0
    monkeypatch.setenv("EMBEDDING_THREADS", "-1")
    with pytest.raises(ValidationError):
        Settings()
