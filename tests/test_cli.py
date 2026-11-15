"""Tests for app.cli (the crew is replaced by a stub; no LLM, no MCP)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app import cli
from app.agents.pipeline import RunResult
from app.schemas import Citation, Report, Section

REPORT = Report(
    title="Solar",
    language="en",
    executive_summary="Growing [1].",
    sections=[Section(heading="Growth", body_markdown="Fast [1].")],
    citations=[Citation(number=1, source="doc-1", title="Doc", evidence_id="sq1-e1")],
)


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace run_research; record its arguments; return a completed run."""
    recorded: list[dict[str, Any]] = []

    def fake_run(question: str, depth: str, settings: Any, **kwargs: Any) -> RunResult:
        recorded.append({"question": question, "depth": depth, **kwargs})
        failed = question == "fail"
        return RunResult(
            job_id="job-9",
            status="failed" if failed else "completed",
            question=question,
            depth="quick",
            model="m",
            report=None if failed else REPORT,
            error="RuntimeError: boom" if failed else None,
        )

    monkeypatch.setattr(cli, "run_research", fake_run)
    return recorded


@pytest.mark.parametrize("missing", ["GROQ_API_KEY", "TAVILY_API_KEY"])
def test_missing_key_fails_fast_with_exit_code_2(
    missing: str,
    monkeypatch: pytest.MonkeyPatch,
    calls: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    other = "TAVILY_API_KEY" if missing == "GROQ_API_KEY" else "GROQ_API_KEY"
    monkeypatch.setenv(other, "set")
    assert cli.main(["question"]) == 2
    assert calls == []  # the crew never starts
    assert missing in capsys.readouterr().out


def test_placeholder_key_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "your-groq-api-key-here")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    assert cli.main(["question"]) == 2


def test_completed_run_writes_json_and_markdown(
    keys: None, calls: list[dict[str, Any]], tmp_path: Path
) -> None:
    assert cli.main(["What about solar?", "--depth", "deep"]) == 0
    assert calls[0]["question"] == "What about solar?"
    assert calls[0]["depth"] == "deep"
    assert calls[0]["process"].value == "sequential"

    saved = json.loads((tmp_path / "outputs" / "job-9.json").read_text(encoding="utf-8"))
    assert Report.model_validate(saved["report"]) == REPORT  # valid Report JSON
    markdown = (tmp_path / "outputs" / "job-9.md").read_text(encoding="utf-8")
    assert markdown.startswith("# Solar")


def test_failed_run_writes_json_only_and_exits_1(
    keys: None, calls: list[dict[str, Any]], tmp_path: Path
) -> None:
    assert cli.main(["fail"]) == 1
    saved = json.loads((tmp_path / "outputs" / "job-9.json").read_text(encoding="utf-8"))
    assert saved["status"] == "failed"
    assert saved["error"] == "RuntimeError: boom"
    assert not (tmp_path / "outputs" / "job-9.md").exists()


def test_hierarchical_process_is_passed_through(keys: None, calls: list[dict[str, Any]]) -> None:
    cli.main(["q", "--process", "hierarchical"])
    assert calls[0]["process"].value == "hierarchical"


def test_outputs_dir_comes_from_settings(
    keys: None, calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OUTPUTS_DIR", "reports")
    cli.main(["q"])
    assert (tmp_path / "reports" / "job-9.json").exists()


def test_invalid_depth_is_rejected_by_argparse() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["q", "--depth", "huge"])
    assert exc.value.code == 2
