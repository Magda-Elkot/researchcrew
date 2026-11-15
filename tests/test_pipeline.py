"""Tests for app.agents.pipeline.run_research with fake crews (no LLM, no MCP)."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from crewai import Process

from app.agents.crew import MainOutput
from app.agents.limits import DepthLimits
from app.agents.pipeline import RunResult, Steps, normalize_plan, run_research
from app.config import Settings, get_settings
from app.schemas import (
    Citation,
    EvidenceItem,
    EvidenceSet,
    Finding,
    FindingSet,
    Language,
    ProgressEvent,
    Report,
    ResearchPlan,
    ReviewResult,
    Section,
    SubQuestion,
)
from app.tools.guarded import RunGuard

QUESTION = "How fast is solar growing in the GCC?"


def usage(tokens: int) -> SimpleNamespace:
    return SimpleNamespace(prompt_tokens=tokens, completion_tokens=tokens // 10, total_tokens=0)


def make_plan(n: int = 3, language: Language = "en", prefix: str = "q") -> ResearchPlan:
    return ResearchPlan(
        question=QUESTION,
        language=language,
        sub_questions=[
            SubQuestion(id=f"{prefix}{i}", text=f"sub {i}", rationale="r") for i in range(1, n + 1)
        ],
    )


def evidence(sq: str, n: int = 1) -> EvidenceSet:
    return EvidenceSet(
        items=[
            EvidenceItem(
                id=f"{sq}-e{i}",
                sub_question_id=sq,
                claim="c",
                snippet="s" * 30,
                source_type="doc",
                source="doc-1",
            )
            for i in range(1, n + 1)
        ]
    )


def report(cite: str = "sq1-e1", marker: str = "[1]") -> Report:
    return Report(
        title="Solar",
        language="en",
        executive_summary=f"Growing {marker}.",
        sections=[Section(heading="Growth", body_markdown=f"Fast {marker}.")],
        citations=[Citation(number=1, source="doc-1", title="Doc", evidence_id=cite)],
    )


class FakeSteps:
    """Scripted crew outputs; records what the pipeline asked for."""

    def __init__(
        self,
        plan: ResearchPlan | None = None,
        evidence_by_sq: dict[str, EvidenceSet] | None = None,
        first_report: Report | None = None,
        review: ReviewResult | None = None,
        revised_report: Report | None = None,
        fail_in: str | None = None,
        expire_after_research: bool = False,
    ) -> None:
        self.plan_out = plan or make_plan()
        self.evidence = evidence_by_sq
        self.first_report = first_report or report()
        self.review = review or ReviewResult(approved=True)
        self.revised_report = revised_report or report()
        self.fail_in = fail_in
        self.expire_after_research = expire_after_research
        self.guard: RunGuard | None = None
        self.plan_args: tuple[Any, ...] = ()
        self.research_plan: ResearchPlan | None = None
        self.revisions: list[list[str]] = []
        self.prompt_tokens = 0

    def usage(self) -> SimpleNamespace:
        """Running total, like the run's LLM counter."""
        return usage(self.prompt_tokens)

    def plan(self, question: str, language: Language, sub_questions: int) -> Any:
        self.plan_args = (question, language, sub_questions)
        if self.fail_in == "plan":
            raise RuntimeError("groq is down")
        self.prompt_tokens += 100
        return self.plan_out

    def research_and_write(self, question: str, plan: ResearchPlan) -> MainOutput:
        self.research_plan = plan
        self.prompt_tokens += 1000
        if self.expire_after_research and self.guard is not None:
            self.guard.timeout_s = 0
        evidence_by_sq = self.evidence or {sq.id: evidence(sq.id) for sq in plan.sub_questions}
        return MainOutput(
            evidence=evidence_by_sq,
            findings=FindingSet(
                findings=[
                    Finding(id="f1", statement="s", evidence_ids=["sq1-e1"], confidence="high")
                ]
            ),
            report=self.first_report,
            review=self.review,
            dropped=2,
        )

    def revise(
        self,
        question: str,
        plan: ResearchPlan,
        report: Report,
        issues: list[str],
        evidence: EvidenceSet,
        findings: FindingSet,
    ) -> Any:
        self.revisions.append(issues)
        self.prompt_tokens += 500
        return self.revised_report


def run(
    steps: FakeSteps, depth: str = "quick", question: str = QUESTION
) -> tuple[RunResult, list[ProgressEvent]]:
    events: list[ProgressEvent] = []

    @contextmanager
    def open_steps(
        settings: Settings, guard: RunGuard, limits: DepthLimits, process: Process
    ) -> Iterator[Steps]:
        steps.guard = guard
        yield steps

    result = run_research(
        question,
        depth,  # type: ignore[arg-type]  # tests pass plain strings
        get_settings(),
        emit=events.append,
        job_id="job-1",
        open_steps=open_steps,
    )
    return result, events


def test_approved_run_completes_without_revision() -> None:
    steps = FakeSteps()
    result, events = run(steps)
    assert result.status == "completed"
    assert result.report is not None
    assert result.report.title == "Solar"
    assert result.citations == result.report.citations
    assert result.revised is False
    assert steps.revisions == []
    assert result.review == ReviewResult(approved=True)
    assert result.remaining_issues == []
    assert [e.id for e in result.evidence] == ["sq1-e1", "sq2-e1", "sq3-e1"]
    assert result.evidence_dropped == 2
    assert result.token_usage.prompt_tokens == 1100
    assert result.token_usage.completion_tokens == 110
    assert result.cost_usd > 0
    assert result.latency_s is not None
    assert events[-1].type == "job_completed"
    assert steps.plan_args == (QUESTION, "en", 3)


def test_plan_is_trimmed_renumbered_and_uses_detected_language() -> None:
    steps = FakeSteps(plan=make_plan(n=6, language="en", prefix="x"))
    result, _ = run(steps, question="كيف تنمو الطاقة الشمسية في الخليج؟")
    assert steps.plan_args[1:] == ("ar", 3)
    assert result.plan is not None
    assert [sq.id for sq in result.plan.sub_questions] == ["sq1", "sq2", "sq3"]
    assert result.plan.language == "ar"
    assert result.report is not None
    assert result.report.language == "ar"  # the report follows the detected language


def test_deep_run_asks_for_more_sub_questions() -> None:
    steps = FakeSteps(plan=make_plan(n=5))
    run(steps, depth="deep")
    assert steps.plan_args[2] == 5


def test_rejected_review_triggers_exactly_one_revision() -> None:
    review = ReviewResult(approved=False, issues=["too vague"], uncited_claims=["Fast."])
    # The revised report is still flawed, but there is never a second revision (SPEC).
    steps = FakeSteps(review=review, revised_report=report(marker="[7]"))
    result, events = run(steps)
    assert result.status == "completed"
    assert result.revised is True
    assert len(steps.revisions) == 1
    assert steps.revisions[0] == ["too vague", "Uncited: Fast."]
    assert "revision_requested" in [e.type for e in events]
    assert "Marker [7] has no entry in the citation list." in result.remaining_issues
    assert result.token_usage.prompt_tokens == 1600


def test_citation_problem_overrides_an_approving_reviewer() -> None:
    steps = FakeSteps(first_report=report(cite="invented-id"))
    result, _ = run(steps)
    assert result.review is not None
    assert result.review.approved is False
    assert any("unknown evidence 'invented-id'" in issue for issue in result.review.issues)
    assert len(steps.revisions) == 1


def test_no_revision_when_time_is_up() -> None:
    steps = FakeSteps(review=ReviewResult(approved=False, issues=["x"]), expire_after_research=True)
    result, events = run(steps)
    assert result.status == "completed"
    assert result.revised is False
    assert steps.revisions == []
    assert "revision_requested" not in [e.type for e in events]


def test_sub_questions_without_evidence_are_marked_unanswered() -> None:
    empty = EvidenceSet(items=[])
    steps = FakeSteps(evidence_by_sq={"sq1": evidence("sq1"), "sq2": empty, "sq3": empty})
    result, _ = run(steps)
    assert result.report is not None
    assert result.report.unanswered_sub_question_ids == ["sq2", "sq3"]


def test_all_tools_failing_marks_every_sub_question_unanswered() -> None:
    empty = {f"sq{i}": EvidenceSet(items=[]) for i in range(1, 4)}
    steps = FakeSteps(evidence_by_sq=empty, first_report=report())
    result, _ = run(steps)
    assert result.status == "completed"
    assert result.report is not None
    assert result.report.unanswered_sub_question_ids == ["sq1", "sq2", "sq3"]
    assert result.evidence == []


def test_an_error_gives_a_failed_result_not_an_exception() -> None:
    steps = FakeSteps(fail_in="plan")
    result, events = run(steps)
    assert result.status == "failed"
    assert result.error == "RuntimeError: groq is down"
    assert result.report is None
    assert events[-1].type == "job_failed"
    assert result.token_usage.prompt_tokens == 0  # usage is still read after a failure


def test_normalize_plan_keeps_text_and_rationale() -> None:
    plan = normalize_plan(make_plan(n=4, prefix="z"), "ar", 3)
    assert [(sq.id, sq.text) for sq in plan.sub_questions] == [
        ("sq1", "sub 1"),
        ("sq2", "sub 2"),
        ("sq3", "sub 3"),
    ]
    assert plan.language == "ar"


@pytest.mark.parametrize("depth", ["quick", "deep"])
def test_run_tool_cap_follows_the_depth(depth: str) -> None:
    steps = FakeSteps(plan=make_plan(n=5))
    run(steps, depth=depth)
    assert steps.guard is not None
    assert steps.guard.max_tool_calls == (6 if depth == "quick" else 20)
