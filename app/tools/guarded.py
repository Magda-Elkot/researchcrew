"""Per-run guardrails around the MCP tools (DECISIONS #6, #69, #71).

Agents never call MCP tools directly. Each research task gets its own `GuardedTool` wrappers,
and every call goes through them:
- a per-task budget and a per-run cap on tool calls, and the run deadline: once used up, the
  tool answers "write your final answer now" instead of failing (in the 3a spike a hard stop made
  the model loop, then crash);
- a failing call is retried once, then reported as `tool_failed`; the run continues (SPEC);
- every call emits a progress event and is recorded verbatim, so the evidence check can verify
  that quoted snippets really came from a tool.

The shared state of one run (counter, deadline, records, event callback) lives in `RunGuard`.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from crewai.tools import BaseTool
from tenacity import Retrying, stop_after_attempt, wait_fixed

from app.log import get_logger
from app.schemas import EventType, ProgressEvent

logger = get_logger(__name__)

EmitFn = Callable[[ProgressEvent], None]

BUDGET_USED_UP = (
    "Tool budget used up. Do not call any more tools; write your final answer now "
    "from the results you already have."
)
DEADLINE_REACHED = (
    "The time limit for this run is reached. Do not call any more tools; write your final "
    "answer now from the results you already have."
)
# MCP servers report some errors as normal text results (mcpadapt doesn't raise for them).
_ERROR_PREFIXES = ("Error", "Input validation error")


@dataclass(frozen=True)
class ToolRecord:
    """One tool call as the agent saw it."""

    tool: str
    args: dict[str, Any]
    output: str
    ok: bool
    scope: str  # which research task called it (a sub-question id)


@dataclass
class TaskBudget:
    """Tool calls allowed for one task, shared by all of that task's tool wrappers."""

    limit: int
    used: int = 0


@dataclass
class RunGuard:
    """State shared by all tools of one run."""

    job_id: str
    max_tool_calls: int
    timeout_s: float
    emit_fn: EmitFn | None = None
    retry_wait_s: float = 1.0
    clock: Callable[[], float] = time.monotonic
    calls: int = 0
    records: list[ToolRecord] = field(default_factory=list)
    _started: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._started = self.clock()

    def expired(self) -> bool:
        return self.clock() - self._started >= self.timeout_s

    def seconds_left(self) -> float:
        return max(0.0, self.timeout_s - (self.clock() - self._started))

    def take_call(self) -> bool:
        """Count one tool call against the run cap; False when the cap is reached."""
        with self._lock:
            if self.calls >= self.max_tool_calls:
                return False
            self.calls += 1
            return True

    def record(self, record: ToolRecord) -> None:
        with self._lock:
            self.records.append(record)

    def emit(self, type_: EventType, message: str, agent: str | None = None) -> None:
        event = ProgressEvent(job_id=self.job_id, type=type_, agent=agent, message=message)
        logger.info("progress", extra={"event": event.model_dump(mode="json")})
        if self.emit_fn is not None:
            self.emit_fn(event)

    def outputs_for(self, scope: str) -> list[str]:
        """Verbatim outputs of the successful calls made by one research task."""
        return [r.output for r in self.records if r.scope == scope and r.ok]


def _short(value: Any, limit: int = 200) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


class GuardedTool(BaseTool):
    """An MCP tool with a budget, one retry, progress events and recording."""

    inner: BaseTool
    guard: RunGuard
    budget: TaskBudget
    scope: str
    agent_role: str

    def _run(self, **kwargs: Any) -> str:
        if self.guard.expired():
            return DEADLINE_REACHED
        if self.budget.used >= self.budget.limit or not self.guard.take_call():
            logger.info("tool budget used up", extra={"tool": self.name, "scope": self.scope})
            return BUDGET_USED_UP
        self.budget.used += 1
        self.guard.emit("tool_called", f"{self.name} {_short(kwargs)}", self.agent_role)

        try:
            output = self._call_with_retry(kwargs)
        except Exception as exc:
            return self._failed(kwargs, f"{type(exc).__name__}: {_short(exc)}")
        if output.startswith(_ERROR_PREFIXES):
            return self._failed(kwargs, _short(output), output=output)

        self.guard.record(ToolRecord(self.name, kwargs, output, ok=True, scope=self.scope))
        return output

    def _call_with_retry(self, kwargs: dict[str, Any]) -> str:
        """Call the inner tool; retry once if it raises (SPEC: retried once, then skipped)."""
        for attempt in Retrying(
            stop=stop_after_attempt(2), wait=wait_fixed(self.guard.retry_wait_s), reraise=True
        ):
            with attempt:
                return str(self.inner.run(**kwargs))
        raise AssertionError("unreachable")  # Retrying either returns or re-raises

    def _failed(self, kwargs: dict[str, Any], reason: str, output: str = "") -> str:
        self.guard.record(ToolRecord(self.name, kwargs, output, ok=False, scope=self.scope))
        self.guard.emit("tool_failed", f"{self.name}: {reason}", self.agent_role)
        logger.warning("tool failed", extra={"tool": self.name, "reason": reason})
        return (
            f"Tool {self.name} failed ({reason}). Try another tool, or write your final "
            "answer from the results you have. Never invent sources."
        )


def guarded_tools(
    tools: list[BaseTool], guard: RunGuard, budget: int, scope: str, agent_role: str
) -> list[BaseTool]:
    """Fresh wrappers for one task; together they may make `budget` calls."""
    task_budget = TaskBudget(limit=budget)
    return [
        GuardedTool(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            inner=tool,
            guard=guard,
            budget=task_budget,
            scope=scope,
            agent_role=agent_role,
        )
        for tool in tools
    ]
