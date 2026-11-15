"""The real pipeline steps: each one builds and runs a CrewAI crew.

- `plan`: a one-task crew (the number of research tasks is only known after the plan).
- `research_and_write`: the main crew. One research task per sub-question (each with its own
  guarded tools and evidence-check guardrail), then Analyst, Writer and Reviewer. Its `process`
  comes from one factory, so Phase 6 can run the same tasks hierarchically.
- `revise`: a one-task crew for the single allowed rewrite.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from crewai import LLM, Crew, CrewOutput, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.tools import BaseTool
from pydantic import BaseModel, ValidationError

from app.agents import agents as roles
from app.agents import tasks as jobs
from app.agents.evidence import EvidenceCheck, make_evidence_guardrail
from app.agents.limits import DepthLimits
from app.schemas import (
    EvidenceSet,
    FindingSet,
    Language,
    Report,
    ResearchPlan,
    ReviewResult,
)
from app.tools.guarded import RunGuard, guarded_tools


class StepError(RuntimeError):
    """An agent's output could not be read as the expected model."""


@dataclass
class MainOutput:
    evidence: dict[str, EvidenceSet]  # per sub-question id, after the evidence check
    findings: FindingSet
    report: Report
    review: ReviewResult
    dropped: int = 0  # evidence items removed by the check


def build_crew(
    agents: list[BaseAgent],
    tasks: list[Task],
    process: Process,
    llm: LLM,
    task_callback: Callable[[Any], None] | None = None,
) -> Crew:
    """One factory for every crew; hierarchical mode adds a manager on the same LLM."""
    manager: dict[str, Any] = {"manager_llm": llm} if process == Process.hierarchical else {}
    return Crew(
        agents=agents,
        tasks=tasks,
        process=process,
        task_callback=task_callback,
        verbose=False,
        **manager,
    )


def kickoff(crew: Crew) -> None:
    """Run a crew (results are read from its tasks; we never ask for streaming output).

    Not `CrewOutput.token_usage`: CrewAI adds up each agent's *cumulative* LLM usage, so one
    LLM shared by several agents and crews is counted many times (198K reported for a ~40K
    run). Usage is read once per run from the LLM itself (`CrewSteps.usage`, DECISIONS #77).
    """
    output = crew.kickoff()
    if not isinstance(output, CrewOutput):
        raise StepError(f"unexpected crew output type {type(output).__name__}")


def task_result[ModelT: BaseModel](task: Task, model: type[ModelT]) -> ModelT:
    """The task's output as `model`, from CrewAI's parsed output or its raw JSON."""
    output = task.output
    if output is None:
        raise StepError(f"{model.__name__}: the task produced no output")
    if isinstance(output.pydantic, model):
        return output.pydantic
    try:
        return model.model_validate_json(output.raw)
    except (ValidationError, ValueError) as exc:
        raise StepError(f"{model.__name__}: the agent's answer is not valid ({exc})") from exc


@dataclass
class CrewSteps:
    """Pipeline steps backed by CrewAI (see `app.agents.pipeline.Steps`)."""

    llm: LLM
    tools: list[BaseTool]
    guard: RunGuard
    limits: DepthLimits
    notes_dir: str
    process: Process = Process.sequential
    _checks: dict[str, EvidenceCheck] = field(default_factory=dict)

    def _announce(self, roles_in_order: list[str]) -> Callable[[Any], None]:
        """Emit agent_started/agent_finished as the crew's tasks complete, in order."""
        done = 0
        self.guard.emit("agent_started", "started", roles_in_order[0])

        def on_task_done(_output: Any) -> None:
            nonlocal done
            self.guard.emit("agent_finished", "finished", roles_in_order[done])
            done += 1
            if done < len(roles_in_order):
                self.guard.emit("agent_started", "started", roles_in_order[done])

        return on_task_done

    def _guardrail(self, sub_question_id: str) -> Callable[[Any], tuple[bool, Any]]:
        """The evidence check for one research task; its result is kept for the pipeline."""

        def outputs() -> list[str]:
            return self.guard.outputs_for(sub_question_id)

        def keep(check: EvidenceCheck) -> None:
            self._checks[sub_question_id] = check

        return make_evidence_guardrail(
            outputs_for=outputs,
            sub_question_id=sub_question_id,
            max_items=self.limits.evidence_per_sub_question,
            snippet_max_chars=self.limits.snippet_max_chars,
            on_checked=keep,
        )

    def usage(self) -> Any:
        """Token usage of every LLM call in this run (one LLM instance per run)."""
        return self.llm.get_token_usage_summary()

    def plan(self, question: str, language: Language, sub_questions: int) -> ResearchPlan:
        agent = roles.planner(self.llm)
        task = jobs.plan_task(agent, question, language, sub_questions)
        crew = build_crew(
            [agent], [task], Process.sequential, self.llm, self._announce([agent.role])
        )
        kickoff(crew)
        return task_result(task, ResearchPlan)

    def research_and_write(self, question: str, plan: ResearchPlan) -> MainOutput:
        researcher = roles.researcher(self.llm)
        analyst = roles.analyst(self.llm)
        writer = roles.writer(self.llm)
        reviewer = roles.reviewer(self.llm)

        research: list[Task] = []
        for sq in plan.sub_questions:
            tools = guarded_tools(
                self.tools,
                self.guard,
                budget=self.limits.tool_calls_per_sub_question,
                scope=sq.id,
                agent_role=researcher.role,
            )
            research.append(
                jobs.research_task(
                    researcher,
                    question,
                    sq,
                    plan.language,
                    tools,
                    self.limits.tool_calls_per_sub_question,
                    self.limits.evidence_per_sub_question,
                    self.notes_dir,
                    self._guardrail(sq.id),
                )
            )
        analysis = jobs.analyst_task(analyst, research, plan.language)
        writing = jobs.writer_task(writer, question, plan, research, analysis)
        review = jobs.reviewer_task(reviewer, question, plan, writing)

        order = [researcher.role] * len(research) + [analyst.role, writer.role, reviewer.role]
        crew = build_crew(
            [researcher, analyst, writer, reviewer],
            [*research, analysis, writing, review],
            self.process,
            self.llm,
            self._announce(order),
        )
        kickoff(crew)

        evidence = {
            sq.id: EvidenceSet(items=self._checks[sq.id].kept if sq.id in self._checks else [])
            for sq in plan.sub_questions
        }
        return MainOutput(
            evidence=evidence,
            findings=task_result(analysis, FindingSet),
            report=task_result(writing, Report),
            review=task_result(review, ReviewResult),
            dropped=sum(len(c.dropped) for c in self._checks.values()),
        )

    def revise(
        self,
        question: str,
        plan: ResearchPlan,
        report: Report,
        issues: list[str],
        evidence: EvidenceSet,
        findings: FindingSet,
    ) -> Report:
        agent = roles.writer(self.llm)
        task = jobs.revision_task(agent, question, plan, report, issues, evidence, findings)
        crew = build_crew(
            [agent], [task], Process.sequential, self.llm, self._announce([agent.role])
        )
        kickoff(crew)
        return task_result(task, Report)
