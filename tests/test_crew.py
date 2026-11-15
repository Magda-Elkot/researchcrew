"""Tests for app.agents.{agents, tasks, crew}: wiring only (no LLM is called)."""

from types import SimpleNamespace
from typing import Any

import pytest
from crewai import LLM, Process, Task

from app.agents import agents as roles
from app.agents import tasks as jobs
from app.agents.crew import CrewSteps, StepError, build_crew, task_result
from app.agents.limits import LIMITS
from app.config import get_settings
from app.schemas import ProgressEvent, ResearchPlan, ReviewResult, SubQuestion
from app.tools.guarded import RunGuard


@pytest.fixture
def llm() -> LLM:
    return LLM(model="groq/openai/gpt-oss-120b", api_key="test-key")  # never called


def plan() -> ResearchPlan:
    return ResearchPlan(
        question="q",
        language="ar",
        sub_questions=[SubQuestion(id=f"sq{i}", text=f"t{i}", rationale="r") for i in (1, 2, 3)],
    )


def test_llm_gets_timeout_and_retries_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TIMEOUT_S", "45")
    monkeypatch.setenv("LLM_NUM_RETRIES", "3")
    built = roles.build_llm(get_settings())
    assert built.timeout == 45
    assert built.additional_params["num_retries"] == 3


def test_agents_have_limits_and_no_delegation(llm: LLM) -> None:
    for build in (roles.planner, roles.researcher, roles.analyst, roles.writer, roles.reviewer):
        agent = build(llm)
        assert agent.allow_delegation is False
        assert agent.max_iter == (
            roles.RESEARCHER_MAX_ITER if build is roles.researcher else roles.DEFAULT_MAX_ITER
        )


def test_tasks_pass_only_the_context_they_need(llm: LLM) -> None:
    p = plan()
    research = [
        jobs.research_task(
            roles.researcher(llm), "q", sq, "ar", [], 2, 3, "data/notes", lambda o: (True, o)
        )
        for sq in p.sub_questions
    ]
    analysis = jobs.analyst_task(roles.analyst(llm), research, "ar")
    writing = jobs.writer_task(roles.writer(llm), "q", p, research, analysis)
    review = jobs.reviewer_task(roles.reviewer(llm), "q", p, writing)

    assert all(task.context == [] for task in research)  # no earlier outputs
    assert analysis.context == research
    assert writing.context == [*research, analysis]
    assert review.context == [writing]  # the reviewer sees only the report
    assert "Arabic" in writing.description
    assert "(sq2): t2" in research[1].description
    assert "at most 2 tool calls" in research[0].description
    assert research[0].guardrail_max_retries == 0


def test_build_crew_adds_a_manager_only_in_hierarchical_mode(llm: LLM) -> None:
    agent = roles.writer(llm)
    task = Task(description="d", expected_output="e", agent=agent)
    sequential = build_crew([agent], [task], Process.sequential, llm)
    assert sequential.process == Process.sequential
    assert sequential.manager_llm is None
    hierarchical = build_crew([agent], [task], Process.hierarchical, llm)
    assert hierarchical.manager_llm is not None


def test_task_result_reads_pydantic_then_raw_json() -> None:
    review = ReviewResult(approved=True)
    as_model = SimpleNamespace(output=SimpleNamespace(pydantic=review, raw=""))
    assert task_result(as_model, ReviewResult) == review  # type: ignore[arg-type]
    as_raw = SimpleNamespace(output=SimpleNamespace(pydantic=None, raw=review.model_dump_json()))
    assert task_result(as_raw, ReviewResult) == review  # type: ignore[arg-type]


@pytest.mark.parametrize("output", [None, SimpleNamespace(pydantic=None, raw="not json")])
def test_task_result_raises_a_readable_error(output: Any) -> None:
    with pytest.raises(StepError, match="ReviewResult"):
        task_result(SimpleNamespace(output=output), ReviewResult)  # type: ignore[arg-type]


def test_progress_events_follow_the_task_order(llm: LLM) -> None:
    events: list[ProgressEvent] = []
    guard = RunGuard(job_id="j", max_tool_calls=6, timeout_s=60, emit_fn=events.append)
    steps = CrewSteps(llm=llm, tools=[], guard=guard, limits=LIMITS["quick"], notes_dir="n")
    on_done = steps._announce(["Researcher", "Analyst"])
    on_done(None)
    on_done(None)
    assert [(e.type, e.agent) for e in events] == [
        ("agent_started", "Researcher"),
        ("agent_finished", "Researcher"),
        ("agent_started", "Analyst"),
        ("agent_finished", "Analyst"),
    ]
