"""Command-line entry point: `researchcrew "question" [--depth quick|deep]`.

Checks the API keys first (a missing key fails in a second, naming the variable), runs the crew,
and writes `<outputs_dir>/<job_id>.json` (the full RunResult) and `<job_id>.md` (the report).
Progress is logged as JSON lines. Exit codes: 0 completed, 1 run failed, 2 configuration error.
"""

import argparse
from pathlib import Path

from crewai import Process

from app.agents.pipeline import RunResult, run_research
from app.agents.report import to_markdown
from app.config import ConfigError, get_settings, require
from app.log import get_logger

logger = get_logger(__name__)

REQUIRED_KEYS: tuple[str, ...] = ("GROQ_API_KEY", "TAVILY_API_KEY")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="researchcrew", description="Research a question with a crew of AI agents."
    )
    parser.add_argument("question", help="The research question (English or Arabic).")
    parser.add_argument("--depth", choices=["quick", "deep"], default="quick")
    parser.add_argument(
        "--process",
        choices=[p.value for p in (Process.sequential, Process.hierarchical)],
        default=Process.sequential.value,
        help="CrewAI process for the main crew (hierarchical is the Phase 6 comparison).",
    )
    return parser.parse_args(argv)


def write_outputs(result: RunResult, outputs_dir: Path) -> list[Path]:
    """Save the run as JSON, and the report as Markdown when there is one."""
    outputs_dir.mkdir(parents=True, exist_ok=True)
    json_path = outputs_dir / f"{result.job_id}.json"
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    paths = [json_path]
    if result.report is not None:
        md_path = outputs_dir / f"{result.job_id}.md"
        md_path.write_text(to_markdown(result.report), encoding="utf-8")
        paths.append(md_path)
    return paths


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    args = parse_args(argv)
    try:
        require(*REQUIRED_KEYS)
    except ConfigError as exc:
        logger.error("configuration error", extra={"error": str(exc)})
        return 2
    settings = get_settings()
    result = run_research(args.question, args.depth, settings, process=Process(args.process))
    paths = write_outputs(result, Path(settings.outputs_dir))
    logger.info(
        "outputs written",
        extra={"status": result.status, "files": [str(p) for p in paths], "error": result.error},
    )
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
