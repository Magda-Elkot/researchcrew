"""Phase 3a spike: CrewAI + our three MCP servers. Measures tool latency and tokens; not app code.

Modes:
    bench  (no LLM, no keys) calls tools directly: option A (MCPServerAdapter, one open session)
           vs option B (Agent(mcps=...), a new connection per call), plus filesystem start-up.
    agent  (needs GROQ_API_KEY and TAVILY_API_KEY) runs one agent that must use all three
           servers, and records every tool call and the token usage of every LLM call.

Run:  uv run python scripts/spike_mcp.py bench
      uv run python scripts/spike_mcp.py agent
Needs Qdrant and docs-mcp running (`docker compose up -d qdrant`, `make docs-mcp`).
"""

import os

# CrewAI reads these at import time: no anonymous telemetry, no CrewAI cloud tracing.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

import argparse
import statistics
from pathlib import Path
from time import perf_counter
from typing import Any

from crewai import LLM, Agent, Crew, Process, Task
from crewai.events import (
    LLMCallCompletedEvent,
    ToolUsageErrorEvent,
    ToolUsageFinishedEvent,
    crewai_event_bus,
)
from crewai.mcp import MCPServerHTTP, MCPServerStdio
from crewai.mcp.filters import create_static_tool_filter
from crewai.tools import BaseTool

from app.config import Settings, get_settings, require
from app.log import get_logger
from app.tools.mcp import (
    FILESYSTEM_TOOLS,
    default_specs,
    docs_mcp_spec,
    filesystem_spec,
    open_mcp_tools,
)

logger = get_logger("spike_mcp")

REPEATS = 5
SEARCH_ARGS = {"query": "renewable energy jobs in the GCC", "top_k": 3}


def _timed_calls(tool: BaseTool, args: dict[str, Any], repeats: int) -> list[float]:
    """Call `tool` `repeats` times; return each duration in ms."""
    durations = []
    for _ in range(repeats):
        started = perf_counter()
        tool.run(**args)
        durations.append((perf_counter() - started) * 1000)
    return durations


def _summary(durations: list[float]) -> dict[str, float]:
    return {
        "first_ms": round(durations[0]),
        "median_ms": round(statistics.median(durations)),
        "max_ms": round(max(durations)),
    }


def _by_name(tools: list[BaseTool], name: str) -> BaseTool:
    return next(t for t in tools if t.name == name)


def bench(settings: Settings) -> None:
    """Option A vs option B on docs-mcp and the filesystem server, without an LLM."""
    notes = str(Path(settings.notes_dir).resolve())

    # Option A: one session per server, kept open.
    specs = [docs_mcp_spec(settings), filesystem_spec(settings)]
    with open_mcp_tools(specs, settings) as tools:
        a_search = _timed_calls(_by_name(tools, "search_documents"), SEARCH_ARGS, REPEATS)
        a_fs = _timed_calls(_by_name(tools, "list_directory"), {"path": notes}, REPEATS)

    # Option B: CrewAI's native MCP support; every call opens a new connection.
    agent = Agent(
        role="bench",
        goal="bench",
        backstory="bench",
        llm=LLM(model=settings.llm_model, api_key="unused"),  # never called in bench mode
    )
    native = agent.get_mcp_tools(
        [
            MCPServerHTTP(
                url=settings.docs_mcp_url,
                tool_filter=create_static_tool_filter(allowed_tool_names=["search_documents"]),
            ),
            MCPServerStdio(
                command="npx",
                args=["-y", settings.filesystem_mcp_package, "--read-only", notes],
                tool_filter=create_static_tool_filter(allowed_tool_names=list(FILESYSTEM_TOOLS)),
            ),
        ]
    )
    native_names = [t.name for t in native]
    b_search_tool = next(t for t in native if t.name.endswith("search_documents"))
    b_fs_tool = next(t for t in native if t.name.endswith("list_directory"))
    b_search = _timed_calls(b_search_tool, SEARCH_ARGS, REPEATS)
    b_fs = _timed_calls(b_fs_tool, {"path": notes}, REPEATS)

    logger.info(
        "bench summary",
        extra={
            "repeats": REPEATS,
            "native_tool_names": native_names,
            "A_adapter_docs_search": _summary(a_search),
            "B_native_docs_search": _summary(b_search),
            "A_adapter_fs_list_directory": _summary(a_fs),
            "B_native_fs_list_directory": _summary(b_fs),
        },
    )


def run_agent(settings: Settings) -> None:
    """One agent, all three servers, one question; records tool calls and tokens."""
    require("GROQ_API_KEY", "TAVILY_API_KEY")
    assert settings.groq_api_key is not None  # guaranteed by require()
    notes = str(Path(settings.notes_dir).resolve())

    tool_calls: list[dict[str, Any]] = []
    llm_calls: list[dict[str, Any]] = []

    @crewai_event_bus.on(ToolUsageFinishedEvent)
    def _tool_done(source: Any, event: ToolUsageFinishedEvent) -> None:
        ms = (event.finished_at - event.started_at).total_seconds() * 1000
        tool_calls.append(
            {
                "tool": event.tool_name,
                "ms": round(ms),
                "output_chars": len(str(event.output)),
                "cached": event.from_cache,
            }
        )
        logger.info("tool call", extra={**tool_calls[-1], "tool_args": str(event.tool_args)[:300]})

    @crewai_event_bus.on(ToolUsageErrorEvent)
    def _tool_error(source: Any, event: ToolUsageErrorEvent) -> None:
        tool_calls.append({"tool": event.tool_name, "error": str(event.error)[:200]})
        tool_args = str(event.tool_args)[:300]
        logger.warning("tool error", extra={**tool_calls[-1], "tool_args": tool_args})

    @crewai_event_bus.on(LLMCallCompletedEvent)
    def _llm_done(source: Any, event: LLMCallCompletedEvent) -> None:
        llm_calls.append(dict(event.usage or {}))
        logger.info("llm call", extra={"usage": llm_calls[-1]})

    llm = LLM(
        model=settings.llm_model,
        api_key=settings.groq_api_key.get_secret_value(),
        temperature=0.2,
    )
    with open_mcp_tools(default_specs(settings), settings) as tools:
        researcher = Agent(
            role="Researcher",
            goal="Answer research questions using only the tools, citing every source.",
            backstory="A careful analyst who checks the local library before the web.",
            tools=tools,
            llm=llm,
            max_iter=8,
            verbose=False,
        )
        task = Task(
            description=(
                "Question: what does IRENA say about renewable energy jobs in the GCC countries?\n"
                f"1. Read the topic notes in {notes} (renewable-energy.md) to find the "
                "relevant doc_id.\n"
                "2. Search our document library for the answer.\n"
                "3. Search the web for one recent news item on the same topic.\n"
                "Use each of the three steps exactly once if possible."
            ),
            expected_output=(
                "Up to 5 bullet points. Each ends with its source in brackets: "
                "a doc_id, a file path or a URL."
            ),
            agent=researcher,
        )
        crew = Crew(agents=[researcher], tasks=[task], process=Process.sequential)
        started = perf_counter()
        result = crew.kickoff()
        seconds = round(perf_counter() - started, 1)

    prompt_tokens = [c.get("prompt_tokens", 0) for c in llm_calls]
    logger.info(
        "agent summary",
        extra={
            "model": settings.llm_model,
            "seconds": seconds,
            "tools_available": [t.name for t in tools],
            "tool_calls": tool_calls,
            "llm_calls": len(llm_calls),
            "prompt_tokens_per_call": prompt_tokens,
            "max_prompt_tokens": max(prompt_tokens, default=0),
            "crew_token_usage": result.token_usage.model_dump(),
        },
    )
    logger.info("agent answer", extra={"answer": result.raw})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["bench", "agent"])
    args = parser.parse_args()
    settings = get_settings()
    if args.mode == "bench":
        bench(settings)
    else:
        run_agent(settings)


if __name__ == "__main__":
    main()
