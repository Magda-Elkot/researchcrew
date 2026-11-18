"""`make eval`: run the dataset through both crew configurations, score, save, report.

Resumable (DECISIONS #99): each (config, question) result is one JSON file in
`evals/runs/<config>/<question_id>.json`; finished ones are skipped. When Groq's daily token
limit is reached, the run that hit it is *not* saved and the eval stops: run `make eval` again
the next day. Questions run in pairs (question 1 in both configs, then question 2, ...), so both
configs see the same conditions on any given day.

Per run: `run_research` (traced, tag `process:<config>`) → citation coverage and tool stats
(`evals.metrics`) → faithfulness and completeness (`evals.judge`) → scores on the Langfuse
trace → the result file. At the end `evals/report.py` writes `evals/results.md`.

Run: `uv run python -m evals.run [--config sequential] [--questions q01,q02] [--limit N]
[--retry-failed]`.
"""

import argparse
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from crewai import Process
from pydantic import AwareDatetime, BaseModel, Field

from app.agents.errors import DAILY_LIMIT_MARKER
from app.agents.pipeline import RunResult, run_research
from app.agents.report import to_markdown
from app.config import ConfigError, Settings, get_settings, require
from app.log import get_logger
from app.observability import flush_tracing, score_trace, setup_tracing, upload_dataset
from app.schemas import Language, utc_now
from evals.judge import (
    CompleteFn,
    JudgeError,
    claims_to_judge,
    judge_completeness,
    judge_faithfulness,
    litellm_complete,
)
from evals.metrics import citation_coverage, tool_stats

logger = get_logger(__name__)

CONFIGS: dict[str, Process] = {
    "sequential": Process.sequential,
    "hierarchical": Process.hierarchical,
}
DATASET_NAME = "researchcrew-eval"
EXIT_BUDGET = 3  # `make eval` stopped at the provider's daily limit; resume tomorrow


class EvalQuestion(BaseModel):
    id: str
    question: str
    language: Language
    topic: str
    expected_aspects: list[str] = Field(min_length=3, max_length=5)


class EvalRecord(BaseModel):
    """One (config, question) result: the metrics, the judge's scores and the full run."""

    question_id: str
    config: str
    language: Language
    judge_model: str
    finished_at: AwareDatetime = Field(default_factory=utc_now)
    status: str
    error: str | None = None
    trace_id: str | None = None
    latency_s: float | None = None
    cost_usd: float = 0.0
    total_tokens: int = 0
    tool_calls: int = 0
    tool_calls_ok: int = 0
    claims: int = 0
    claims_covered: int = 0
    citation_coverage: float | None = None
    faithfulness: float | None = None
    faithfulness_claims: int = 0
    completeness: float | None = None
    aspects_covered: list[str] = Field(default_factory=list)  # "yes"/"partly"/"no" per aspect
    judge_error: str | None = None
    revised: bool = False
    run: RunResult


class BudgetExhausted(RuntimeError):
    """The generator's daily token limit is reached: stop and resume another day."""


RunFn = Callable[..., RunResult]


def load_dataset(path: Path) -> list[EvalQuestion]:
    lines = path.read_text(encoding="utf-8").splitlines()
    questions = [EvalQuestion.model_validate_json(line) for line in lines if line.strip()]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate question ids in {path}")
    return questions


def record_path(runs_dir: Path, config: str, question_id: str) -> Path:
    return runs_dir / config / f"{question_id}.json"


def evaluate(
    question: EvalQuestion,
    config: str,
    settings: Settings,
    complete: CompleteFn,
    run_fn: RunFn = run_research,
) -> EvalRecord:
    """Run, measure and judge one question in one configuration."""
    result = run_fn(
        question.question,
        "quick",
        settings,
        process=CONFIGS[config],
        job_id=f"eval-{config}-{question.id}",
    )
    if result.status == "failed" and DAILY_LIMIT_MARKER in (result.error or ""):
        raise BudgetExhausted(result.error)

    stats = tool_stats(result.tool_log)
    record = EvalRecord(
        question_id=question.id,
        config=config,
        language=question.language,
        judge_model=settings.judge_model,
        status=result.status,
        error=result.error,
        trace_id=result.trace_id,
        latency_s=result.latency_s,
        cost_usd=result.cost_usd,
        total_tokens=result.token_usage.total_tokens,
        tool_calls=stats.calls,
        tool_calls_ok=stats.ok,
        revised=result.revised,
        run=result,
    )
    if result.status != "completed" or result.report is None:
        return record

    evidence_ids = {item.id for item in result.evidence}
    coverage = citation_coverage(result.report, evidence_ids)
    record.claims, record.claims_covered = coverage.claims, coverage.covered
    record.citation_coverage = coverage.rate
    try:
        claims = claims_to_judge(
            result.report, result.evidence, result.tool_log, settings.judge_context_chars
        )
        faithfulness = judge_faithfulness(complete, question.question, claims)
        record.faithfulness, record.faithfulness_claims = faithfulness.score, faithfulness.claims
        completeness = judge_completeness(
            complete,
            question.question,
            to_markdown(result.report, rtl_wrapper=False),
            question.expected_aspects,
        )
        record.completeness = completeness.score
        verdicts = {v.aspect: v.covered for v in completeness.aspects}
        record.aspects_covered = [
            verdicts.get(n, "no") for n in range(1, len(question.expected_aspects) + 1)
        ]
    except JudgeError as exc:
        record.judge_error = str(exc)
        logger.warning("judge failed", extra={"question": question.id, "config": config})
    return record


def push_scores(record: EvalRecord) -> None:
    """The record's scores on its Langfuse trace (no-op when tracing is off)."""
    for name, value in (
        ("citation_coverage", record.citation_coverage),
        ("faithfulness", record.faithfulness),
        ("completeness", record.completeness),
        (
            "tool_success_rate",
            record.tool_calls_ok / record.tool_calls if record.tool_calls else None,
        ),
    ):
        if value is not None:
            score_trace(record.trace_id, name, float(value), comment=f"judge: {record.judge_model}")


def run_eval(
    questions: list[EvalQuestion],
    configs: list[str],
    runs_dir: Path,
    settings: Settings,
    complete: CompleteFn,
    run_fn: RunFn = run_research,
    retry_failed: bool = False,
    limit: int | None = None,
) -> tuple[int, bool]:
    """Run every missing (question, config) pair; returns (runs done, stopped at the budget)."""
    done = 0
    for question in questions:
        for config in configs:
            path = record_path(runs_dir, config, question.id)
            if path.exists():
                previous = EvalRecord.model_validate_json(path.read_text(encoding="utf-8"))
                if previous.status == "completed" or not retry_failed:
                    continue
            if limit is not None and done >= limit:
                return done, False
            logger.info("eval run", extra={"question": question.id, "config": config})
            try:
                record = evaluate(question, config, settings, complete, run_fn)
            except BudgetExhausted as exc:
                logger.warning(
                    "daily token limit reached: run `make eval` again tomorrow "
                    "(finished runs are kept)",
                    extra={"error": str(exc)[:200]},
                )
                return done, True
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
            push_scores(record)
            done += 1
            logger.info(
                "eval run saved",
                extra={
                    "question": question.id,
                    "config": config,
                    "status": record.status,
                    "coverage": record.citation_coverage,
                    "faithfulness": record.faithfulness,
                    "completeness": record.completeness,
                },
            )
    return done, False


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="evals.run", description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", action="append", choices=list(CONFIGS), dest="configs")
    parser.add_argument("--questions", help="comma-separated question ids (default: all)")
    parser.add_argument("--limit", type=int, help="stop after this many new runs")
    parser.add_argument("--retry-failed", action="store_true", help="run failed ones again")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from evals.report import write_results

    args = parse_args(argv)
    try:
        require("GROQ_API_KEY", "TAVILY_API_KEY", "GEMINI_API_KEY")
    except ConfigError as exc:
        logger.error("configuration error", extra={"error": str(exc)})
        return 2
    settings = get_settings()
    eval_dir = Path(settings.eval_dir)
    questions = load_dataset(eval_dir / "dataset.jsonl")
    if args.questions:
        wanted = set(args.questions.split(","))
        questions = [q for q in questions if q.id in wanted]
    configs = args.configs or list(CONFIGS)

    setup_tracing(settings)
    upload_dataset(
        DATASET_NAME,
        "ResearchCrew eval questions (EN/AR) with expected aspects",
        [
            {
                "id": f"{DATASET_NAME}-{q.id}",  # item ids are unique per Langfuse project
                "input": {"question": q.question, "language": q.language},
                "expected_output": {"expected_aspects": q.expected_aspects},
                "metadata": {"topic": q.topic},
            }
            for q in questions
        ],
    )
    started = datetime.now()
    try:
        done, stopped = run_eval(
            questions,
            configs,
            eval_dir / "runs",
            settings,
            litellm_complete(settings),
            retry_failed=args.retry_failed,
            limit=args.limit,
        )
    finally:
        flush_tracing()
    results = write_results(eval_dir)
    logger.info(
        "eval finished",
        extra={
            "new_runs": done,
            "stopped_at_daily_limit": stopped,
            "minutes": round((datetime.now() - started).total_seconds() / 60, 1),
            "results": str(results),
        },
    )
    return EXIT_BUDGET if stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
