"""Tests for app.log: JSON output and secret redaction."""

import json
import logging
from typing import Any

import pytest

from app.config import get_settings
from app.log import REDACTED, JsonFormatter, get_logger


def _format(message: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    record = logging.getLogger("test").makeRecord(
        "test", logging.INFO, __file__, 1, message, None, None, extra=extra
    )
    result: dict[str, Any] = json.loads(JsonFormatter().format(record))
    return result


def test_output_is_valid_json_with_core_fields() -> None:
    data = _format("hello")
    assert data["message"] == "hello"
    assert data["level"] == "INFO"
    assert data["logger"] == "test"
    assert data["timestamp"].endswith("+00:00")


def test_extra_fields_are_included() -> None:
    assert _format("run", {"job_id": "j1"})["job_id"] == "j1"


def test_api_key_field_is_redacted() -> None:
    data = _format("x", {"groq_api_key": "gsk-abc", "password": "pw", "authorization": "Bearer t"})
    assert data["groq_api_key"] == REDACTED
    assert data["password"] == REDACTED
    assert data["authorization"] == REDACTED


def test_nested_sensitive_field_is_redacted() -> None:
    data = _format("x", {"headers": {"Authorization": "Bearer t", "accept": "json"}})
    assert data["headers"] == {"Authorization": REDACTED, "accept": "json"}


def test_token_counts_are_kept() -> None:
    data = _format("x", {"prompt_tokens": 120, "token_usage": {"total_tokens": 150}})
    assert data["prompt_tokens"] == 120
    assert data["token_usage"] == {"total_tokens": 150}


def test_secret_value_in_message_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk-live-123")
    get_settings.cache_clear()
    data = _format("calling groq with gsk-live-123 now", {"detail": "key=gsk-live-123"})
    assert "gsk-live-123" not in json.dumps(data)


def test_url_api_key_query_is_scrubbed() -> None:
    data = _format(
        "GET https://mcp.tavily.com/mcp/?tavilyApiKey=abc&x=1 and https://e.com/?apiKey=xyz"
    )
    assert "abc" not in data["message"]
    assert "xyz" not in data["message"]
    assert "x=1" in data["message"]


def test_get_logger_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    get_logger("app.test").warning("visible", extra={"n": 1})
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(line)["n"] == 1


def test_token_and_secret_fields_are_redacted_but_counts_kept() -> None:
    data = _format(
        "x",
        {
            "hf_token": "hf_abc",
            "access_token": "tok",
            "token": "t",
            "langfuse_secret": "s",
            "total_tokens": 42,
            "max_tokens": 1024,
        },
    )
    for key in ("hf_token", "access_token", "token", "langfuse_secret"):
        assert data[key] == REDACTED
    assert (data["total_tokens"], data["max_tokens"]) == (42, 1024)
