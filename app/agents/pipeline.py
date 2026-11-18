"""`run_research()`: one research run from question to checked report (DECISIONS #72).

Plain Python around the crews, so every decision is visible and testable:
detect the language → plan (trimmed to the depth's size) → research, analyse, write, review →
citation check merged into the review → at most one revision → mark sub-questions without
evidence → sum tokens and cost. Any error ends the run as `failed` with a readable message
(`errors.readable_error`).

The crews themselves are behind the `Steps` protocol: `CrewSteps` runs CrewAI, tests pass
a fake.
"""

import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Protocol

from crewai import Process
from pydantic import BaseModel, Field

from app.agents.agents import build_llm
from app.agents.crew import CrewSteps, MainOutput
from app.agents.errors import readable_error
from app.agents.limits import LIMITS, DepthLimits
from app.agents.pacing import capped_retry_waits, paced_llm_calls
from app.agents.report import check_citations
from app.config import Settings
from app.language import detect_language
from app.log import get_logger
from app.observability import traced_run
from app.schemas import (
    Depth,
    EvidenceItem,
    EvidenceSet,
    Finding,
    FindingSet,
    JobResult,
    Language,
    Report,
    ResearchPlan,
    ReviewResult,
    TokenUsage,
)
from app.tools.guarded import EmitFn, RunGuard
from app.tools.mcp import default_specs, open_mcp_tools
from app.usage import add_usage, cost_usd

logger = get_logger(__name__)


class Steps(Protocol):
    """What the pipeline needs from the crews."""

    def usage(self) -> Any:
        """Token usage of the whole run so far (prompt/completion/total counters)."""
        ...

    def plan(self, question: str, language: Language, sub_questions: int) -> ResearchPlan: ...

    def research_and_write(self, question: str, plan: ResearchPlan) -> MainOutput: ...

    def revise(
        self,
        question: str,
        plan: ResearchPlan,
        report: Report,
        issues: list[str],
        evidence: EvidenceSet,
        findings: FindingSet,
    ) -> Report: ...


OpenSteps = Callable[[Settings, RunGuard, DepthLimits, Process], AbstractContextManager[Steps]]


class ToolCall(BaseModel):
    """One executed tool call with its raw output (the evals check claims against it)."""

    tool: str
    scope: str  # the research task (sub-question id) that called it
    ok: bool
    output: str


class RunResult(JobResult):
    """Everything about one run: the API's JobResult plus what the evals and the CLI need."""

    question: str
    depth: Depth
    model: str
    plan: ResearchPlan | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    evidence_dropped: int = 0
    findings: list[Finding] = Field(default_factory=list)
    review: ReviewResult | None = None
    revised: bool = False
    # Citation problems left in the final report.
    remaining_issues: list[str] = Field(default_factory=list)
    tool_calls: int = 0
    # The run's Langfuse trace (None when tracing is off).
    trace_id: str | None = None
    # Executed tool calls with raw outputs (not returned by the API; used by the evals).
    tool_log: list[ToolCall] = Field(default_factory=list)


@contextmanager
def open_crew_steps(
    settings: Settings, guard: RunGuard, limits: DepthLimits, process: Process
) -> Iterator[Steps]:
    """The real steps: MCP connections are opened for this run and closed after (#62)."""
    with open_mcp_tools(default_specs(settings), settings) as tools:
        yield CrewSteps(
            llm=build_llm(settings),
            tools=tools,
            guard=guard,
            limits=limits,
            notes_dir=settings.notes_dir,
            process=process,
        )


def normalize_plan(plan: ResearchPlan, language: Language, max_sub_questions: int) -> ResearchPlan:
    """Our language detection wins; keep the depth's number of sub-questions; ids sq1, sq2, ..."""
    sub_questions = [
        sq.model_copy(update={"id": f"sq{i}"})
        for i, sq in enumerate(plan.sub_questions[:max_sub_questions], start=1)
    ]
    return plan.model_copy(update={"language": language, "sub_questions": sub_questions})


def run_research(
    question: str,
    depth: Depth,
    settings: Settings,
    emit: EmitFn | None = None,
    process: Process = Process.sequential,
    job_id: str | None = None,
    open_steps: OpenSteps = open_crew_steps,
) -> RunResult:
    """Run the whole crew for one question. Never raises: errors give a `failed` result.

    The run is one Langfuse trace when tracing is on (`app.observability`, Phase 5)."""
    job_id = job_id or uuid.uuid4().hex[:12]
    with traced_run(
        job_id=job_id,
        question=question,
        depth=depth,
        process=process.value,
        model=settings.llm_model,
        version=settings.app_version,
    ) as trace:
        result = _run(question, depth, settings, emit, process, job_id, open_steps)
        result.trace_id = trace.trace_id
        trace.finish(_trace_output(result), error=result.error)
    return result


def _trace_output(result: RunResult) -> dict[str, object]:
    """The run's summary shown as the trace's output in Langfuse."""
    return {
        "status": result.status,
        "title": result.report.title if result.report else None,
        "evidence": len(result.evidence),
        "evidence_dropped": result.evidence_dropped,
        "citations": len(result.citations),
        "revised": result.revised,
        "remaining_issues": len(result.remaining_issues),
        "tool_calls": result.tool_calls,
        "total_tokens": result.token_usage.total_tokens,
        "cost_usd": result.cost_usd,
        "latency_s": result.latency_s,
    }


def _run(
    question: str,
    depth: Depth,
    settings: Settings,
    emit: EmitFn | None,
    process: Process,
    job_id: str,
    open_steps: OpenSteps,
) -> RunResult:
    limits = LIMITS[depth]
    started = time.monotonic()
    guard = RunGuard(
        job_id=job_id,
        max_tool_calls=min(
            settings.max_tool_calls, limits.sub_questions * limits.tool_calls_per_sub_question
        ),
        timeout_s=settings.run_timeout_s,
        emit_fn=emit,
    )
    result = RunResult(
        job_id=job_id, status="running", question=question, depth=depth, model=settings.llm_model
    )
    usage = TokenUsage()
    used_steps: Steps | None = None  # kept to read token usage even after a failure
    start_info = {"job_id": job_id, "depth": depth, "crew_process": process.value}
    logger.info("run started", extra=start_info)

    try:
        language = detect_language(question)
        with (
            paced_llm_calls(settings.llm_tokens_per_minute),
            capped_retry_waits(settings.llm_max_retry_wait_s),
            open_steps(settings, guard, limits, process) as steps,
        ):
            used_steps = steps
            plan = steps.plan(question, language, limits.sub_questions)
            plan = normalize_plan(plan, language, limits.sub_questions)
            result.plan = plan

            main = steps.research_and_write(question, plan)
            evidence = [item for sq in plan.sub_questions for item in main.evidence[sq.id].items]
            evidence_ids = {item.id for item in evidence}
            result.evidence = evidence
            result.evidence_dropped = main.dropped
            result.findings = main.findings.findings

            citation_issues = check_citations(main.report, evidence_ids)
            review = main.review.model_copy(
                update={
                    "approved": main.review.approved and not citation_issues,
                    "issues": main.review.issues + citation_issues,
                }
            )
            result.review = review

            report = main.report
            if not review.approved:
                if guard.expired():
                    logger.warning("no time left for a revision", extra={"job_id": job_id})
                else:
                    guard.emit("revision_requested", "; ".join(review.issues)[:500], "Reviewer")
                    report = steps.revise(
                        question,
                        plan,
                        report,
                        review.issues + [f"Uncited: {c}" for c in review.uncited_claims],
                        EvidenceSet(items=evidence),
                        main.findings,
                    )
                    result.revised = True

        unanswered = [sq.id for sq in plan.sub_questions if not main.evidence[sq.id].items]
        report = report.model_copy(
            update={"language": plan.language, "unanswered_sub_question_ids": unanswered}
        )
        result.report = report
        result.citations = report.citations
        result.remaining_issues = check_citations(report, evidence_ids)
        result.status = "completed"
        guard.emit("job_completed", f"report ready: {report.title}")
    except Exception as exc:
        logger.exception("run failed", extra={"job_id": job_id})
        result.status = "failed"
        result.error = readable_error(exc)  # the full error is in the log above
        guard.emit("job_failed", result.error)

    if used_steps is not None:
        usage = add_usage(usage, used_steps.usage())
    result.token_usage = usage
    result.cost_usd = cost_usd(settings.llm_model, usage)
    result.latency_s = round(time.monotonic() - started, 1)
    result.tool_calls = guard.calls
    result.tool_log = [
        ToolCall(tool=r.tool, scope=r.scope, ok=r.ok, output=r.output) for r in guard.records
    ]
    logger.info(
        "run finished",
        extra={
            "job_id": job_id,
            "status": result.status,
            "latency_s": result.latency_s,
            "tool_calls": result.tool_calls,
            "total_tokens": usage.total_tokens,
            "cost_usd": result.cost_usd,
            "revised": result.revised,
        },
    )
    return result
