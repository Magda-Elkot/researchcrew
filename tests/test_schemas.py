"""Tests for app.schemas: valid and invalid cases for every data contract."""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas import (
    Citation,
    EvidenceItem,
    EvidenceSet,
    Finding,
    FindingSet,
    JobCreated,
    JobResult,
    ProgressEvent,
    Report,
    ResearchPlan,
    ResearchRequest,
    ReviewResult,
    Section,
    SubQuestion,
    TokenUsage,
)


def _subs(n: int) -> list[dict[str, str]]:
    return [{"id": f"q{i}", "text": f"Sub-question {i}?", "rationale": "why"} for i in range(n)]


def _evidence(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "e1",
        "sub_question_id": "q1",
        "claim": "Water boils at 100 C at sea level.",
        "snippet": "boils at 100 °C",
        "source_type": "web",
        "source": "https://example.com",
    }
    data.update(overrides)
    return data


def _report(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "title": "Report",
        "language": "en",
        "executive_summary": "Summary [1].",
        "sections": [{"heading": "Intro", "body_markdown": "Claim [1]."}],
        "citations": [
            {"number": 1, "source": "https://example.com", "title": "Ex", "evidence_id": "e1"}
        ],
    }
    data.update(overrides)
    return data


# --- ResearchPlan / SubQuestion -----------------------------------------------


@pytest.mark.parametrize("n", [3, 6])
def test_plan_accepts_3_to_6_sub_questions(n: int) -> None:
    plan = ResearchPlan(question="What?", language="en", sub_questions=_subs(n))  # type: ignore[arg-type]
    assert len(plan.sub_questions) == n


@pytest.mark.parametrize("n", [2, 7])
def test_plan_rejects_too_few_or_many_sub_questions(n: int) -> None:
    with pytest.raises(ValidationError):
        ResearchPlan(question="What?", language="en", sub_questions=_subs(n))  # type: ignore[arg-type]


def test_plan_accepts_arabic() -> None:
    plan = ResearchPlan.model_validate(
        {"question": "ما هو؟", "language": "ar", "sub_questions": _subs(3)}
    )
    assert plan.language == "ar"


def test_plan_rejects_bad_language() -> None:
    with pytest.raises(ValidationError):
        ResearchPlan.model_validate(
            {"question": "What?", "language": "fr", "sub_questions": _subs(3)}
        )


def test_sub_question_rejects_blank_text() -> None:
    with pytest.raises(ValidationError):
        SubQuestion(id="q1", text="   ", rationale="r")


# --- Evidence -----------------------------------------------------------------


def test_evidence_valid_and_defaults_to_aware_utc_time() -> None:
    item = EvidenceItem.model_validate(_evidence())
    assert item.retrieved_at.tzinfo is not None
    assert EvidenceSet(items=[item]).items[0].id == "e1"


def test_evidence_accepts_doc_source() -> None:
    assert (
        EvidenceItem.model_validate(_evidence(source_type="doc", source="doc-42")).source
        == "doc-42"
    )


def test_evidence_rejects_bad_source_type() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem.model_validate(_evidence(source_type="book"))


def test_evidence_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem.model_validate(_evidence(retrieved_at=datetime(2026, 1, 1)))


# --- Findings -----------------------------------------------------------------


def test_finding_valid() -> None:
    finding = Finding(id="f1", statement="S", evidence_ids=["e1"], confidence="high")
    assert FindingSet(findings=[finding]).findings[0].confidence == "high"


def test_finding_rejects_bad_confidence() -> None:
    with pytest.raises(ValidationError):
        Finding.model_validate(
            {"id": "f1", "statement": "S", "evidence_ids": ["e1"], "confidence": "sure"}
        )


def test_finding_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        Finding(id="f1", statement="S", evidence_ids=[], confidence="low")


# --- Report / Section / Citation / Review ---------------------------------------


def test_report_valid_with_default_unanswered_list() -> None:
    report = Report.model_validate(_report())
    assert report.unanswered_sub_question_ids == []
    assert report.citations[0].number == 1


def test_report_rejects_bad_language() -> None:
    with pytest.raises(ValidationError):
        Report.model_validate(_report(language="de"))


def test_section_rejects_blank_heading() -> None:
    with pytest.raises(ValidationError):
        Section(heading="", body_markdown="x")


def test_citation_number_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Citation(number=0, source="s", title="t", evidence_id="e1")


def test_review_result_defaults_and_validation() -> None:
    assert ReviewResult(approved=True).issues == []
    with pytest.raises(ValidationError):
        ReviewResult.model_validate({"approved": "maybe"})


# --- SSE ------------------------------------------------------------------------


def test_progress_event_valid() -> None:
    event = ProgressEvent(job_id="j1", type="agent_started", agent="planner", message="go")
    assert event.timestamp.tzinfo is not None
    assert "agent_started" in event.model_dump_json()


def test_progress_event_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        ProgressEvent.model_validate({"job_id": "j1", "type": "exploded", "message": "x"})


# --- API models -------------------------------------------------------------------


def test_research_request_defaults_to_quick_and_strips() -> None:
    req = ResearchRequest(question="  What is MCP?  ")
    assert req.question == "What is MCP?"
    assert req.depth == "quick"


@pytest.mark.parametrize("question", ["", "    ", "x" * 2001])
def test_research_request_rejects_empty_or_too_long(question: str) -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(question=question)


def test_research_request_rejects_bad_depth() -> None:
    with pytest.raises(ValidationError):
        ResearchRequest.model_validate({"question": "Q?", "depth": "medium"})


def test_job_created_and_token_usage() -> None:
    assert JobCreated(job_id="j1").job_id == "j1"
    assert TokenUsage().total_tokens == 0
    with pytest.raises(ValidationError):
        TokenUsage(prompt_tokens=-1)
    with pytest.raises(ValidationError):
        JobCreated(job_id="")


def test_wrapper_sets_validate_their_items() -> None:
    with pytest.raises(ValidationError):
        EvidenceSet.model_validate({"items": [_evidence(source_type="book")]})
    with pytest.raises(ValidationError):
        FindingSet.model_validate({"findings": [{"id": "f1", "statement": "S"}]})


def test_job_result_minimal_and_full() -> None:
    queued = JobResult(job_id="j1", status="queued")
    assert queued.report is None
    assert queued.cost_usd == 0.0
    done = JobResult.model_validate(
        {
            "job_id": "j1",
            "status": "completed",
            "report": _report(),
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "cost_usd": 0.01,
            "latency_s": 12.5,
        }
    )
    assert done.report is not None
    assert done.token_usage.total_tokens == 15


def test_job_result_rejects_bad_status_and_negative_cost() -> None:
    with pytest.raises(ValidationError):
        JobResult.model_validate({"job_id": "j1", "status": "paused"})
    with pytest.raises(ValidationError):
        JobResult(job_id="j1", status="failed", cost_usd=-1)


def test_round_trip_json() -> None:
    event = ProgressEvent(
        job_id="j1", type="job_completed", message="done", timestamp=datetime.now(UTC)
    )
    assert ProgressEvent.model_validate_json(event.model_dump_json()) == event
