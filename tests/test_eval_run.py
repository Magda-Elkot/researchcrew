"""Tests for evals.run and evals.report (fake crew, fake judge: no LLM, no network)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app import observability
from app.agents.pipeline import RunResult, ToolCall
from app.config import Settings
from app.schemas import Citation, EvidenceItem, Report, Section
from evals import run as eval_run
from evals.report import render, write_results
from evals.run import EvalQuestion, EvalRecord, load_dataset, record_path, run_eval

SNIPPET = "Solar PV capacity in the GCC reached 9.8 GW"
DAILY = (
    "The LLM provider's daily token limit is reached (Groq free tier). Try again in about "
    "4 min, or set LLM_MODEL to a model with its own quota."
)


def question(qid: str = "q01", language: str = "en") -> EvalQuestion:
    return EvalQuestion(
        id=qid,
        question=f"question {qid}?",
        language=language,  # type: ignore[arg-type]
        topic="energy",
        expected_aspects=["a", "b", "c"],
    )


class FakeCrew:
    def __init__(self, fail_with: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_with = fail_with or {}

    def __call__(self, q: str, depth: str, settings: Settings, **kwargs: Any) -> RunResult:
        config = kwargs["process"].value
        self.calls.append((q, config))
        job_id = kwargs["job_id"]
        if q in self.fail_with:
            return RunResult(
                job_id=job_id, status="failed", question=q, depth="quick", model="m",
                error=self.fail_with[q],
            )  # fmt: skip
        item = EvidenceItem(
            id="sq1-e1", sub_question_id="sq1", claim="c", snippet=SNIPPET, source_type="doc",
            source="d",
        )  # fmt: skip
        report = Report(
            title="T",
            language="en",
            executive_summary="Capacity reached 9.8 GW by 2022 [1]. Demand keeps growing fast.",
            sections=[Section(heading="S", body_markdown="Solar leads the growth [1].")],
            citations=[Citation(number=1, source="d", title="", evidence_id="sq1-e1")],
        )
        return RunResult(
            job_id=job_id, status="completed", question=q, depth="quick", model="m",
            report=report, citations=report.citations, evidence=[item], cost_usd=0.01,
            latency_s=300.0 if config == "sequential" else 500.0, trace_id="t" * 32,
            tool_log=[
                ToolCall(tool="search_documents", scope="sq1", ok=True, output=SNIPPET + "."),
                ToolCall(tool="tavily_search", scope="sq1", ok=False, output=""),
            ],
        )  # fmt: skip


def judge(system: str, user: str) -> str:
    if "scores" in system:
        return json.dumps({"scores": [{"claim": 1, "score": 5}, {"claim": 2, "score": 3}]})
    return json.dumps(
        {
            "aspects": [{"aspect": 1, "covered": "yes"}, {"aspect": 2, "covered": "partly"}],
            "score": 3,
        }
    )


def test_every_pair_is_run_judged_and_saved(tmp_path: Path) -> None:
    crew = FakeCrew()
    done, stopped = run_eval(
        [question("q01"), question("q02", "ar")],
        ["sequential", "hierarchical"],
        tmp_path,
        Settings(),
        judge,
        run_fn=crew,
    )
    assert (done, stopped) == (4, False)
    # pairs: q01 in both configs, then q02
    assert [c for _, c in crew.calls] == ["sequential", "hierarchical"] * 2
    record = EvalRecord.model_validate_json(
        record_path(tmp_path, "hierarchical", "q02").read_text(encoding="utf-8")
    )
    assert record.status == "completed"
    assert (record.claims, record.claims_covered, record.citation_coverage) == (3, 2, 2 / 3)
    assert record.faithfulness == 4.0
    assert record.completeness == 3.0  # 1 + 4 * (1 + 0.5) / 3
    assert record.aspects_covered == ["yes", "partly", "no"]
    assert (record.tool_calls, record.tool_calls_ok) == (2, 1)
    assert record.run.tool_log[0].output.startswith("Solar")


def test_finished_runs_are_skipped_and_failed_ones_only_on_request(tmp_path: Path) -> None:
    run_eval([question()], ["sequential"], tmp_path, Settings(), judge, run_fn=FakeCrew())
    crew = FakeCrew()
    assert run_eval([question()], ["sequential"], tmp_path, Settings(), judge, run_fn=crew) == (
        0,
        False,
    )
    assert crew.calls == []

    failing = FakeCrew(fail_with={"question q02?": "RuntimeError: boom"})
    run_eval([question("q02")], ["sequential"], tmp_path, Settings(), judge, run_fn=failing)
    saved = EvalRecord.model_validate_json(
        record_path(tmp_path, "sequential", "q02").read_text(encoding="utf-8")
    )
    assert (saved.status, saved.error, saved.faithfulness) == ("failed", "RuntimeError: boom", None)
    again = FakeCrew()
    run_eval([question("q02")], ["sequential"], tmp_path, Settings(), judge, run_fn=again)
    assert again.calls == []  # not retried by default
    run_eval(
        [question("q02")], ["sequential"], tmp_path, Settings(), judge, run_fn=again,
        retry_failed=True,
    )  # fmt: skip
    assert len(again.calls) == 1


def test_the_daily_limit_stops_the_eval_without_saving(tmp_path: Path) -> None:
    crew = FakeCrew(fail_with={"question q02?": DAILY})
    done, stopped = run_eval(
        [question("q01"), question("q02"), question("q03")],
        ["sequential"],
        tmp_path,
        Settings(),
        judge,
        run_fn=crew,
    )
    assert (done, stopped) == (1, True)
    assert not record_path(tmp_path, "sequential", "q02").exists()
    assert len(crew.calls) == 2  # q03 was not started


def test_limit_caps_new_runs(tmp_path: Path) -> None:
    done, _ = run_eval(
        [question("q01"), question("q02")], ["sequential", "hierarchical"], tmp_path, Settings(),
        judge, run_fn=FakeCrew(), limit=3,
    )  # fmt: skip
    assert done == 3


def test_scores_go_to_the_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str | None, str, float]] = []
    monkeypatch.setattr(
        eval_run,
        "score_trace",
        lambda tid, name, value, comment="": sent.append((tid, name, value)),
    )
    run_eval([question()], ["sequential"], tmp_path, Settings(), judge, run_fn=FakeCrew())
    assert {name for _, name, _ in sent} == {
        "citation_coverage", "faithfulness", "completeness", "tool_success_rate",
    }  # fmt: skip
    assert all(tid == "t" * 32 for tid, _, _ in sent)


def test_score_trace_is_a_no_op_without_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(observability, "_state", {"done": True, "client": None})
    observability.score_trace("t", "x", 1.0)  # nothing to call, no error
    assert observability.upload_dataset("d", "", [{"id": "q", "input": {}}]) is False


def test_dataset_loading_rejects_duplicates_and_bad_aspects(tmp_path: Path) -> None:
    path = tmp_path / "dataset.jsonl"
    path.write_text(question().model_dump_json() + "\n\n" + question("q02").model_dump_json())
    assert [q.id for q in load_dataset(path)] == ["q01", "q02"]
    path.write_text(question().model_dump_json() + "\n" + question().model_dump_json())
    with pytest.raises(ValueError, match="duplicate"):
        load_dataset(path)
    with pytest.raises(ValueError):
        EvalQuestion(id="x", question="q", language="en", topic="t", expected_aspects=["a"])


def test_results_table(tmp_path: Path) -> None:
    (tmp_path / "dataset.jsonl").write_text(
        "\n".join(question(f"q0{i}").model_dump_json() for i in (1, 2))
    )
    crew = FakeCrew(fail_with={"question q02?": "RuntimeError: boom"})
    run_eval(
        [question("q01"), question("q02")], ["sequential", "hierarchical"], tmp_path / "runs",
        Settings(), judge, run_fn=crew,
    )  # fmt: skip
    text = write_results(tmp_path).read_text(encoding="utf-8")
    assert "in progress" not in text  # 4 of 4 planned runs exist
    seq = next(line for line in text.splitlines() if line.startswith("| sequential |"))
    assert seq.split(" | ")[1:6] == ["1 (+1 failed)", "67 %", "4.00", "3.00", "50 %"]
    assert "300 / 300" in seq and "$0.0100" in seq
    assert "| q02 | en | failed | failed |" in text
    assert "in progress: 1 of 4" in render(
        [
            EvalRecord.model_validate_json(
                record_path(tmp_path / "runs", "sequential", "q01").read_text()
            )
        ],
        4,
        "judge",
    )


def test_the_real_dataset_is_valid() -> None:
    from app.language import detect_language

    questions = load_dataset(Path(__file__).parents[1] / "evals" / "dataset.jsonl")
    assert 25 <= len(questions) <= 30  # SPEC
    assert {q.language for q in questions} == {"en", "ar"}
    assert all(detect_language(q.question) == q.language for q in questions)


def test_only_one_eval_can_run_at_a_time(tmp_path: Path) -> None:
    from evals.run import single_run

    with single_run(tmp_path) as first:
        assert first is True
        with single_run(tmp_path) as second:
            assert second is False  # a second eval would share the per-minute quota
    with single_run(tmp_path) as again:
        assert again is True  # released when the first one ended


def test_a_second_eval_exits_before_touching_langfuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evals.run import EXIT_BUSY, main, single_run

    for key in ("GROQ_API_KEY", "TAVILY_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    monkeypatch.setenv("EVAL_DIR", str(tmp_path))

    def must_not_run(*args: object) -> None:
        raise AssertionError("the second eval touched Langfuse")

    monkeypatch.setattr(eval_run, "setup_tracing", must_not_run)
    monkeypatch.setattr(eval_run, "upload_dataset", must_not_run)
    with single_run(tmp_path / "runs"):
        assert main([]) == EXIT_BUSY
