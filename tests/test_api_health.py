"""Tests for the API basics: /health, /metrics and the startup key check."""

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.api import main
from app.config import ConfigError


@pytest.fixture(autouse=True)
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")


def test_health_returns_ok_and_version() -> None:
    with TestClient(main.app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_metrics_exposes_request_counter() -> None:
    with TestClient(main.app) as client:
        client.get("/health")
        response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'http_requests_total{route="/health",status="200"}' in response.text
    assert "http_request_duration_seconds_bucket" in response.text


def test_unknown_route_uses_bounded_label() -> None:
    with TestClient(main.app) as client:
        assert client.get("/no/such/path").status_code == 404
        text = client.get("/metrics").text
    assert 'route="unmatched",status="404"' in text


@pytest.mark.parametrize("missing", ["GROQ_API_KEY", "TAVILY_API_KEY"])
def test_startup_fails_fast_when_key_missing(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.delenv(missing)
    with pytest.raises(ConfigError, match=missing), TestClient(main.app):
        pass
