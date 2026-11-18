"""Tests for scripts/langfuse_env.py (secrets for self-hosted Langfuse)."""

import re
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import langfuse_env


def test_fills_every_missing_value_with_the_right_format(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=keep-me\nLANGFUSE_SALT=\n", encoding="utf-8")
    assert langfuse_env.main([str(env)]) == 0

    values = langfuse_env.read_env(env)
    assert values["GROQ_API_KEY"] == "keep-me"
    assert set(langfuse_env.DEFAULTS) <= set(values)
    assert re.fullmatch(r"[0-9a-f]{64}", values["LANGFUSE_ENCRYPTION_KEY"])
    assert re.fullmatch(r"pk-lf-[0-9a-f]{32}", values["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"])
    assert re.fullmatch(r"sk-lf-[0-9a-f]{32}", values["LANGFUSE_INIT_PROJECT_SECRET_KEY"])
    assert values["LANGFUSE_PUBLIC_KEY"] == values["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"]
    assert values["LANGFUSE_SECRET_KEY"] == values["LANGFUSE_INIT_PROJECT_SECRET_KEY"]
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_existing_values_are_kept_and_a_second_run_adds_nothing(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("LANGFUSE_SALT=mine\nLANGFUSE_PUBLIC_KEY=pk-lf-own\n", encoding="utf-8")
    langfuse_env.main([str(env)])
    first = env.read_text(encoding="utf-8")
    values = langfuse_env.read_env(env)
    assert values["LANGFUSE_SALT"] == "mine"
    assert values["LANGFUSE_PUBLIC_KEY"] == "pk-lf-own"
    langfuse_env.main([str(env)])
    assert env.read_text(encoding="utf-8") == first


def test_secrets_are_random_and_never_logged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = tmp_path / "a.env", tmp_path / "b.env"
    langfuse_env.main([str(a)])
    langfuse_env.main([str(b)])
    va, vb = langfuse_env.read_env(a), langfuse_env.read_env(b)
    assert va["LANGFUSE_SALT"] != vb["LANGFUSE_SALT"]
    output = capsys.readouterr().out
    assert "LANGFUSE_SALT" in output  # the names are reported...
    assert va["LANGFUSE_SALT"] not in output  # ...the values are not
    assert va["LANGFUSE_INIT_USER_PASSWORD"] not in output
