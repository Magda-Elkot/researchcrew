"""Write `evals/results.md` from the saved eval runs (`evals/runs/<config>/<question>.json`).

One summary row per configuration (the SPEC's table: citation coverage, faithfulness,
completeness, tool-call success and calls per run, latency p50/p95, cost and tokens per
report), the same split by language, and one row per question. Means are over completed runs;
failed runs are counted separately. While the eval is still running, the header says how many
of the planned runs are done.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from evals.metrics import percentile
from evals.run import CONFIGS, EvalRecord

RESULTS_FILE = "results.md"


def load_records(runs_dir: Path) -> list[EvalRecord]:
    return [
        EvalRecord.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(runs_dir.glob("*/*.json"))
    ]


def _mean(values: Iterable[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _fmt(value: float | None, digits: int = 2, suffix: str = "") -> str:
    return "-" if value is None else f"{value:.{digits}f}{suffix}"


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f} %"


def summary_row(label: str, records: list[EvalRecord]) -> str:
    ok = [r for r in records if r.status == "completed"]
    failed = len(records) - len(ok)
    calls = sum(r.tool_calls for r in ok)
    latencies = [r.latency_s for r in ok if r.latency_s is not None]
    cells = [
        label,
        f"{len(ok)}" + (f" (+{failed} failed)" if failed else ""),
        _pct(_mean(r.citation_coverage for r in ok)),
        _fmt(_mean(r.faithfulness for r in ok)),
        _fmt(_mean(r.completeness for r in ok)),
        _pct(sum(r.tool_calls_ok for r in ok) / calls if calls else None),
        _fmt(calls / len(ok) if ok else None, 1),
        f"{_fmt(percentile(latencies, 50), 0)} / {_fmt(percentile(latencies, 95), 0)}",
        "-" if not ok else f"${sum(r.cost_usd for r in ok) / len(ok):.4f}",
        "-" if not ok else f"{sum(r.total_tokens for r in ok) / len(ok):,.0f}",
    ]
    return "| " + " | ".join(cells) + " |"


SUMMARY_HEADER = (
    "| Config | Runs | Citation coverage | Faithfulness (1-5) | Completeness (1-5) "
    "| Tool success | Tool calls / run | Latency p50 / p95 (s) | Cost / report "
    "| Tokens / report |\n"
    "|---|---|---|---|---|---|---|---|---|---|"
)


def render(records: list[EvalRecord], planned: int, judge_model: str) -> str:
    by_config: dict[str, list[EvalRecord]] = defaultdict(list)
    for record in records:
        by_config[record.config].append(record)
    configs = [c for c in CONFIGS if c in by_config] + sorted(set(by_config) - set(CONFIGS))
    status = "complete" if len(records) >= planned else f"in progress: {len(records)} of {planned}"

    lines = [
        "# Evaluation results",
        "",
        f"Status: **{status}** runs · updated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC · "
        f"generator: Groq gpt-oss-120b, quick depth · judge: `{judge_model}`",
        "",
        "Metrics (DECISIONS #98-103): citation coverage = share of report claims whose [n] "
        "markers all resolve to grounded evidence; faithfulness = judge's 1-5 per cited claim "
        "against the raw tool output, averaged; completeness = 1-5 computed from the judge's "
        "yes/partly/no per expected aspect; tool success = executed tool calls without error.",
        "",
        "## By configuration",
        "",
        SUMMARY_HEADER,
        *(summary_row(c, by_config[c]) for c in configs),
        "",
        "## By configuration and language",
        "",
        SUMMARY_HEADER,
    ]
    for config in configs:
        for language in ("en", "ar"):
            subset = [r for r in by_config[config] if r.language == language]
            if subset:
                lines.append(summary_row(f"{config} · {language}", subset))
    lines += [
        "",
        "## Per question",
        "",
        "| Question | Lang | " + " | ".join(f"{c} (cov / faith / compl)" for c in configs) + " |",
        "|---|---|" + "---|" * len(configs),
    ]
    by_question: dict[str, dict[str, EvalRecord]] = defaultdict(dict)
    for record in records:
        by_question[record.question_id][record.config] = record
    for question_id in sorted(by_question):
        row = by_question[question_id]
        language = next(iter(row.values())).language
        cells = []
        for config in configs:
            r = row.get(config)
            if r is None:
                cells.append("-")
            elif r.status != "completed":
                cells.append("failed")
            else:
                cells.append(
                    f"{_pct(r.citation_coverage)} / {_fmt(r.faithfulness, 1)} / "
                    f"{_fmt(r.completeness, 1)}"
                )
        lines.append(f"| {question_id} | {language} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def write_results(eval_dir: Path, judge_model: str | None = None) -> Path:
    records = load_records(eval_dir / "runs")
    dataset = eval_dir / "dataset.jsonl"
    n_questions = sum(
        1 for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    model = judge_model or (records[-1].judge_model if records else "-")
    path = eval_dir / RESULTS_FILE
    path.write_text(render(records, n_questions * len(CONFIGS), model), encoding="utf-8")
    return path


if __name__ == "__main__":
    from app.config import get_settings
    from app.log import get_logger

    path = write_results(Path(get_settings().eval_dir))
    get_logger(__name__).info("results written", extra={"results": str(path)})
