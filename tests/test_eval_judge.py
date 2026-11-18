"""Tests for evals.judge (the model is always a fake)."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.pipeline import ToolCall
from app.config import Settings
from app.schemas import Citation, EvidenceItem, Report, Section
from evals import judge
from evals.judge import (
    ClaimToJudge,
    JudgeError,
    claims_to_judge,
    judge_completeness,
    judge_faithfulness,
    litellm_complete,
    source_window,
)

RAW = (
    "Intro text about the region. Solar PV capacity in the GCC reached 9.8 GW by the end of "
    "2022, led by the United Arab Emirates and Saudi Arabia. Other text follows here."
)


def evidence(
    snippet: str = "Solar PV capacity in the GCC reached 9.8 GW", sq: str = "sq1"
) -> EvidenceItem:
    return EvidenceItem(
        id=f"{sq}-e1", sub_question_id=sq, claim="c", snippet=snippet, source_type="doc", source="d"
    )


def log(output: str = RAW, scope: str = "sq1", ok: bool = True) -> list[ToolCall]:
    return [ToolCall(tool="search_documents", scope=scope, ok=ok, output=output)]


def test_source_window_comes_from_the_raw_output_not_the_snippet() -> None:
    window = source_window(evidence(), log(), chars=80)
    assert "solar pv capacity in the gcc reached 9.8 gw" in window
    assert len(window) <= 80


@pytest.mark.parametrize(
    "tool_log",
    [log(scope="sq2"), log(ok=False), log(output="something else entirely")],
)
def test_without_a_matching_output_the_snippet_is_marked(tool_log: list[ToolCall]) -> None:
    assert source_window(evidence(), tool_log, 200).startswith("(snippet only) ")


def report() -> Report:
    return Report(
        title="T",
        language="en",
        executive_summary="Capacity reached 9.8 GW by 2022 [1]. Growth will continue strongly.",
        sections=[Section(heading="S", body_markdown="Prices fell in many auctions [2].")],
        citations=[
            Citation(number=1, source="d", title="", evidence_id="sq1-e1"),
            Citation(number=2, source="d", title="", evidence_id="gone"),
        ],
    )


def test_only_claims_with_resolving_citations_are_judged() -> None:
    claims = claims_to_judge(report(), [evidence()], log(), chars=200)
    assert [c.text for c in claims] == ["Capacity reached 9.8 GW by 2022 [1]."]
    assert "9.8 gw" in claims[0].sources[0]


def fake(*answers: str) -> Any:
    calls: list[tuple[str, str]] = []

    def complete(system: str, user: str) -> str:
        calls.append((system, user))
        return answers[min(len(calls), len(answers)) - 1]

    complete.calls = calls  # type: ignore[attr-defined]
    return complete


def test_faithfulness_is_the_mean_of_the_claim_scores() -> None:
    complete = fake(
        '```json\n{"scores": [{"claim": 1, "score": 5}, {"claim": 2, "score": 2}, '
        '{"claim": 9, "score": 1}]}\n```'
    )
    claims = [ClaimToJudge("a", ["src a"]), ClaimToJudge("b", ["src b"])]
    result = judge_faithfulness(complete, "q?", claims)
    assert (result.score, result.claims) == (3.5, 2)  # claim 9 doesn't exist: ignored
    _, user = complete.calls[0]
    assert "CLAIM 1: a\n  SOURCE: src a" in user and "Question: q?" in user


def test_nothing_to_judge_gives_no_score_and_no_call() -> None:
    complete = fake("{}")
    assert judge_faithfulness(complete, "q", []).score is None
    assert complete.calls == []


def test_an_unreadable_answer_is_asked_again_once() -> None:
    complete = fake("not json", '{"aspects": [{"aspect": 1, "covered": "partly"}], "score": 3}')
    result = judge_completeness(complete, "q", "# report", ["aspect one"])
    assert (result.score, result.aspects[0].covered) == (3, "partly")
    assert len(complete.calls) == 2
    assert "1. aspect one" in complete.calls[0][1]


def test_two_unreadable_answers_raise() -> None:
    with pytest.raises(JudgeError, match="CompletenessAnswer"):
        judge_completeness(fake('{"score": 9}'), "q", "r", ["a"])


def test_the_litellm_judge_paces_retries_and_uses_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import litellm

    class ServiceUnavailableError(Exception):
        pass

    seen: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        seen.append(kwargs)
        if len(seen) == 1:
            raise ServiceUnavailableError("503 high demand")
        content = json.dumps({"scores": [{"claim": 1, "score": 4}]})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(litellm, "completion", completion)
    sleeps: list[float] = []
    settings = Settings(gemini_api_key="test-gemini", judge_requests_per_minute=30)  # type: ignore[arg-type]
    complete = litellm_complete(settings, sleep=sleeps.append)

    assert json.loads(complete("sys", "user"))["scores"][0]["score"] == 4
    assert len(seen) == 2  # the 503 was retried
    assert sleeps and sleeps[0] >= 5  # with a backoff wait
    assert seen[0]["model"] == "gemini/gemini-3.5-flash-lite"
    assert seen[0]["api_key"] == "test-gemini"
    assert "temperature" not in seen[0]  # Gemini 3.5 rejects it
    complete("sys", "again")
    assert any(0 < s <= 2.0 for s in sleeps[1:])  # paced: 30 per minute = 2 s apart


def test_a_non_retryable_error_is_raised_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import litellm

    calls: list[int] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(1)
        raise ValueError("bad request")

    monkeypatch.setattr(litellm, "completion", completion)
    complete = litellm_complete(Settings(gemini_api_key="k"), sleep=lambda s: None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        complete("s", "u")
    assert calls == [1]
    assert judge._retryable(ValueError()) is False


def test_completeness_score_is_computed_from_the_aspect_verdicts() -> None:
    answer = (
        '{"aspects": [{"aspect": 1, "covered": "yes"}, {"aspect": 2, "covered": "yes"}, '
        '{"aspect": 3, "covered": "no"}], "score": 2, "reason": "r"}'
    )
    result = judge_completeness(fake(answer), "q", "r", ["a", "b", "c"])
    assert result.score == 3.67  # 1 + 4 * 2/3, not the judge's own 2
    assert result.judge_score == 2


def test_missing_and_partial_verdicts() -> None:
    from evals.judge import AspectVerdict, aspect_score

    verdicts = [AspectVerdict(aspect=1, covered="partly")]
    assert aspect_score(verdicts, 2) == 2.0  # aspect 2 has no verdict: "no"
    assert aspect_score([], 0) == 1.0
