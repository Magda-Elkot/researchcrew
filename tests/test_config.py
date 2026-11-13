"""Tests for app.config: env loading, defaults and require()."""

from pathlib import Path

import pytest

from app import __version__
from app.config import ConfigError, get_settings, require, secret_values


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
