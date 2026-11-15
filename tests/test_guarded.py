"""Tests for app.tools.guarded: budgets, deadline, retry once, events and recording."""

from typing import Any

import pytest
from crewai.tools import BaseTool
from pydantic import BaseModel

from app.schemas import ProgressEvent
from app.tools.guarded import (
    BUDGET_USED_UP,
    DEADLINE_REACHED,
    GuardedTool,
    RunGuard,
    guarded_tools,
)


class QueryArgs(BaseModel):
    query: str


class ScriptedTool(BaseTool):
    """Returns (or raises) the next item of `script` on every call."""

    name: str = "search"
    description: str = "scripted"
    args_schema: type[BaseModel] = QueryArgs
    script: list[Any]
    calls: int = 0

    def _run(self, **kwargs: Any) -> str:
        self.calls += 1
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return str(item)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def events() -> list[ProgressEvent]:
    return []


def make_guard(events: list[ProgressEvent], **kwargs: Any) -> RunGuard:
    defaults: dict[str, Any] = {
        "job_id": "job-1",
        "max_tool_calls": 25,
        "timeout_s": 900,
        "emit_fn": events.append,
        "retry_wait_s": 0,
    }
    return RunGuard(**{**defaults, **kwargs})


def wrap(tool: BaseTool, guard: RunGuard, budget: int = 2, scope: str = "sq1") -> GuardedTool:
    (wrapped,) = guarded_tools([tool], guard, budget=budget, scope=scope, agent_role="Researcher")
    assert isinstance(wrapped, GuardedTool)
    return wrapped


def test_successful_call_is_recorded_and_emitted(events: list[ProgressEvent]) -> None:
    guard = make_guard(events)
    tool = wrap(ScriptedTool(script=["solar result"]), guard)
    assert tool.name == "search"
    assert tool.run(query="solar") == "solar result"
    assert [(e.type, e.agent) for e in events] == [("tool_called", "Researcher")]
    assert "solar" in events[0].message
    (record,) = guard.records
    assert (record.tool, record.args, record.output, record.ok, record.scope) == (
        "search",
        {"query": "solar"},
        "solar result",
        True,
        "sq1",
    )
    assert guard.outputs_for("sq1") == ["solar result"]
    assert guard.outputs_for("sq2") == []


def test_task_budget_is_shared_by_all_tools_of_the_task(events: list[ProgressEvent]) -> None:
    guard = make_guard(events)
    a, b = guarded_tools(
        [ScriptedTool(name="a", script=["A"]), ScriptedTool(name="b", script=["B"])],
        guard,
        budget=2,
        scope="sq1",
        agent_role="Researcher",
    )
    assert a.run(query="1") == "A"
    assert b.run(query="2") == "B"
    assert a.run(query="3") == BUDGET_USED_UP
    assert b.run(query="4") == BUDGET_USED_UP
    assert guard.calls == 2


def test_each_task_gets_its_own_budget(events: list[ProgressEvent]) -> None:
    guard = make_guard(events)
    first = wrap(ScriptedTool(script=["x"]), guard, budget=1, scope="sq1")
    second = wrap(ScriptedTool(script=["y"]), guard, budget=1, scope="sq2")
    assert first.run(query="q") == "x"
    assert first.run(query="q2") == BUDGET_USED_UP
    assert second.run(query="q") == "y"


def test_run_cap_applies_across_tasks(events: list[ProgressEvent]) -> None:
    guard = make_guard(events, max_tool_calls=1)
    first = wrap(ScriptedTool(script=["x"]), guard, scope="sq1")
    second = wrap(ScriptedTool(script=["y"]), guard, scope="sq2")
    assert first.run(query="q") == "x"
    assert second.run(query="q") == BUDGET_USED_UP


def test_deadline_stops_tool_calls(events: list[ProgressEvent]) -> None:
    clock = FakeClock()
    guard = make_guard(events, timeout_s=60, clock=clock)
    inner = ScriptedTool(script=["x"])
    tool = wrap(inner, guard)
    assert guard.seconds_left() == 60
    clock.now += 61
    assert guard.expired()
    assert guard.seconds_left() == 0
    assert tool.run(query="q") == DEADLINE_REACHED
    assert inner.calls == 0


def test_failure_is_retried_once_then_succeeds(events: list[ProgressEvent]) -> None:
    guard = make_guard(events)
    inner = ScriptedTool(script=[ConnectionError("reset"), "ok after retry"])
    assert wrap(inner, guard).run(query="q") == "ok after retry"
    assert inner.calls == 2
    assert [e.type for e in events] == ["tool_called"]


def test_failure_twice_is_reported_and_the_run_continues(events: list[ProgressEvent]) -> None:
    guard = make_guard(events)
    inner = ScriptedTool(script=[ConnectionError("server down")])
    result = wrap(inner, guard).run(query="q")
    assert inner.calls == 2  # one try + one retry, then skipped
    assert "failed" in result
    assert "Never invent sources" in result
    assert [e.type for e in events] == ["tool_called", "tool_failed"]
    assert "ConnectionError: server down" in events[1].message
    assert guard.records[0].ok is False
    assert guard.outputs_for("sq1") == []


def test_error_text_from_an_mcp_server_counts_as_failure(events: list[ProgressEvent]) -> None:
    guard = make_guard(events)
    error = "Input validation error: Invalid arguments for tool read_text_file"
    inner = ScriptedTool(script=[error])
    result = wrap(inner, guard).run(query="q")
    assert inner.calls == 1  # a returned error is not retried; only exceptions are
    assert "failed" in result
    assert [e.type for e in events] == ["tool_called", "tool_failed"]
    assert guard.records[0].output == error
    assert guard.records[0].ok is False


def test_long_arguments_are_shortened_in_events(events: list[ProgressEvent]) -> None:
    guard = make_guard(events)
    wrap(ScriptedTool(script=["x"]), guard).run(query="q" * 500)
    assert len(events[0].message) < 260


def test_events_without_a_callback_are_only_logged() -> None:
    guard = RunGuard(job_id="j", max_tool_calls=5, timeout_s=60, emit_fn=None, retry_wait_s=0)
    tool = wrap(ScriptedTool(script=["x"]), guard)
    assert tool.run(query="q") == "x"
