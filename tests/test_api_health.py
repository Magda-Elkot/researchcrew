"""Tests for the placeholder API (/health, /metrics, startup key check) and the CLI stub."""

import pytest
from fastapi.testclient import TestClient

from app import __version__, cli
from app.api import main
from app.config import ConfigError


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


def test_startup_fails_fast_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "REQUIRED_KEYS", ("GROQ_API_KEY",))
    with pytest.raises(ConfigError, match="GROQ_API_KEY"), TestClient(main.app):
        pass


def test_cli_stub_exits_zero() -> None:
    assert cli.main() == 0


def test_cli_fails_fast_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "REQUIRED_KEYS", ("GROQ_API_KEY",))
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        cli.main()
