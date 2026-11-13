"""Shared fixtures: every test runs with a clean environment and fresh settings."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Isolate tests from the developer's real .env and environment variables."""
    monkeypatch.chdir(tmp_path)  # .env is resolved relative to the working directory
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
