# Phase 3 — CrewAI agents and tasks with MCP tools, CLI run

**Status:** high-level. This gets a detailed plan when the phase starts. [Back to master plan](PLAN.md)

Phase 3 is split in two. 3a is a short spike on the riskiest integration (the MCP adapter). 3b builds the full crew on top of it.

---

## Phase 3a — MCP connectivity spike

**Status:** done, 2026-11-15. `bench` and `agent` measured (DECISIONS #61–71). The loop works end to end with gpt-oss-120b once tools are wrapped (`CompactTool`) and a tool budget is applied; findings feed 3b.

### Goal
Prove that CrewAI can use all three MCP servers before building five agents on top of them, and measure what it costs (latency, tokens).

### What the docs and the installed code (crewai 1.15.41) show
CrewAI offers two ways to connect to MCP servers:

| | A. `MCPServerAdapter` (crewai-tools) | B. `Agent(mcps=[MCPServerHTTP/MCPServerStdio])` (native) |
|---|---|---|
| Connection | One session per server, open for the whole `with` block | A **new connection per tool call** (`MCPNativeTool` connects, calls, disconnects) |
| What we get | A list of normal CrewAI `BaseTool` objects | Tools are resolved inside the agent |
| Our guard wrapper (DECISIONS #6) | Easy: wrap each tool before giving it to the agent | Hard: the tools never pass through our code |
| stdio servers | Process started once | Process started on **every** call (slow for Node) |
| Tool filtering | By name: `MCPServerAdapter(params, "tool_a", "tool_b")` | `tool_filter=create_static_tool_filter(...)` |

**Proposal:** use **A** for the project. The spike still measures B's per-call cost on docs-mcp, so the choice is backed by numbers.
Both support only MCP **tools**, not resources: agents won't read `docs://list`; that stays for the Inspector and the frontend.

### Server settings
- **docs-mcp:** `{"url": DOCS_MCP_URL, "transport": "streamable-http"}`. Tools: `search_documents`, `get_document`.
- **Tavily (hosted):** `https://mcp.tavily.com/mcp/` over streamable HTTP. The key goes in an **`Authorization: Bearer` header**, not in the URL (better than DECISIONS #10: URLs end up in logs and error messages). A `DEFAULT_PARAMETERS` header sets `{"max_results": 5, "search_depth": "basic"}` (1 credit per search). Only `tavily_search` is exposed; extract/crawl/research cost more credits.
- **Filesystem:** `@modelcontextprotocol/server-filesystem@2.3.0` (latest on npm today, pinned) over stdio, started with `--read-only` and the single allowed directory `data/notes`. Only `read_text_file`, `list_directory` and `search_files` are exposed. For the spike it runs on your machine with `npx`; installing Node + the server in the api image (`npm i -g`) moves to Phase 3b, when the crew first runs in a container.

### Steps (one small group of files at a time; each explained before writing)
1. **Config** — `app/config.py`, `.env.example`, `tests/test_config.py`:
   - new settings: `TAVILY_API_KEY` (secret), `TAVILY_MCP_URL`, `DOCS_MCP_URL`, `NOTES_DIR`, `FILESYSTEM_MCP_PACKAGE` (pinned), `MCP_CONNECT_TIMEOUT`
   - fix `require()` so placeholder values from `.env.example` (e.g. `your-groq-api-key-here`) count as missing
2. **MCP connections** — `app/tools/mcp.py`, `tests/test_mcp_tools.py`:
   - one function per server that builds its connection settings (pure, easy to test: the key is in the header and never in the URL, the filesystem server is read-only and limited to `data/notes`)
   - `open_mcp_tools()`: a context manager that opens the three adapters together (`contextlib.ExitStack`) and returns the allowed tools; one failing server is logged and skipped, not fatal (SPEC error handling)
   - tests mock `MCPServerAdapter`; no network, no real keys
3. **Spike script** — `scripts/spike_mcp.py` (not part of the app; no tests):
   - one agent (Groq via LiteLLM; gpt-oss-120b after Llama 3.3 70B was retired, #67), with a question that needs all three servers
   - logs (JSON logger) the time to connect to each server, the duration of each tool call, and tokens per LLM call
   - a `--native` flag runs the docs-mcp part with option B for comparison
4. **Record** in DECISIONS.md: adapter choice, connection lifecycle for the API (per job vs long-lived), stdio start-up time, per-call latency A vs B, tokens per LLM call with tool schemas (and whether it fits Groq's ~12K tokens/min).

### Before we start (you)
- `.env` has real `GROQ_API_KEY` and `TAVILY_API_KEY` (never paste them in chat).
- Node is installed: `node -v` prints v20 or newer (the Inspector already uses `npx`, so it probably is).
- For step 3: Qdrant and docs-mcp are running (`make up`, `make docs-mcp`).

### Definition of done
The agent gets a real result from each of the three servers, and the decisions and numbers above are recorded.

---

## Phase 3b — Full crew

**Status:** done, 2026-11-15, except the Arabic exit-check run (Groq's daily token limit was used up; run it tomorrow). Plan: DECISIONS #72–73; findings and fixes from real runs: #74–82.

### Goal
Five agents produce a validated `Report` from a question, using MCP tools only. The crew runs from the CLI:
`uv run researchcrew "question" [--depth quick|deep]` writes `outputs/<id>.json` and `outputs/<id>.md`.

### The constraint that shapes everything
Groq's free tier for gpt-oss-120b: **8K tokens/min, 200K tokens/day, 1,000 requests/day**, and no single request above 8K tokens. An agent resends its whole history on every LLM call, so prompts grow with every tool result. Target: **≤ 6K tokens per prompt, ≤ ~50K tokens per quick run** (≈ 4 quick reports/day; cost ≈ $0.01 at list price, SPEC target < $0.05).

| | quick | deep |
|---|---|---|
| Sub-questions | 3 | up to 5 |
| Tool calls per sub-question | 2 | 4 |
| Tool calls per run (SPEC max 25) | ≤ 8 | ≤ 25 |
| Evidence items kept per sub-question | 3 | 4 |
| Snippet length passed on | ≤ 300 chars | ≤ 300 chars |

### How a run works
```
question
  → detect language (Python)
  → Planner crew            → ResearchPlan (3–5 sub-questions; trimmed to the depth's limit)
  → Main crew (process = sequential | hierarchical, one factory):
       Research task × N     one task per sub-question, each with its OWN tool set + budget,
                             no context from other tasks (small prompts)
         guardrail (Python): evidence check → keep verbatim, sourced items only
       Analyst task          context = research tasks        → FindingSet
       Writer task           context = analyst + evidence index → Report
       Reviewer task         context = writer                → ReviewResult
  → citation check (Python) adds its issues to the review
  → not approved? Writer runs once more with the issues (revision_requested)
  → Python sets unanswered_sub_question_ids, usage, cost → save JSON + Markdown
```
The Planner runs as its own small crew because the number of research tasks is only known after the plan. Phase 6's hierarchical variant swaps only the main crew's `process`.

### Components (one small group of files at a time, each explained first)
1. **`app/language.py`**: `detect_language(text)`. Arabic if ≥ 30 % of the letters are Arabic script. No new library.
2. **`app/tools/guarded.py`**: `RunGuard` holds per-run state: the tool-call counter, the deadline (15 min), recorded tool results and the event callback. `guarded_tools(tools, guard, budget)` gives each research task its own wrappers around the `CompactTool`s:
   - budget or deadline used up → returns "Tool budget used up. Write your final answer now." (no failure; fixes the 3a loop, #69)
   - an exception → one retry (tenacity), then `tool_failed` + a short error text; the run continues
   - every call → `tool_called` event, result recorded for the evidence check (#71: our events, not CrewAI's)
3. **`app/agents/evidence.py`**: the evidence check, used as the research task guardrail. An item is kept only if its snippet (after normalisation: NFKC, whitespace, case) is a verbatim substring of a recorded tool result **and** its source (URL or doc_id) appears in that same result. Dropped items are logged. Then each sub-question is capped at N items. This is what stops the invented Reuters URL from 3a (#70).
4. **`app/agents/citations.py`**: Python checks on the Report. Every `[n]` marker has a citation; every citation points to a kept evidence item; no unused citations. The issues go to the Reviewer's result.
5. **`app/agents/{agents.py, tasks.py, crew.py}`**: the 5 agents (`max_iter`, `max_execution_time`) and their tasks (`output_pydantic`, explicit `context=` so no task sees everything before it), plus the crew factory with a `process` parameter. mypy fix for #66: a per-module override for `app.agents.*` only.
6. **`app/agents/pipeline.py`**: `run_research(question, depth, emit) -> RunResult`, the flow above, written as plain Python (see question 1).
7. **`app/usage.py`**: tokens summed from LiteLLM usage across all crews; cost from LiteLLM's price table (`groq/openai/gpt-oss-120b`: $0.15 / $0.60 per million tokens).
8. **`app/cli.py`**: argument parsing, a startup key check (`GROQ_API_KEY`, `TAVILY_API_KEY`), writes `outputs/<id>.json` + `.md`, prints progress events to the log.
9. **Docker**: Node + the pinned filesystem server in the api image (`npm i -g`), so the crew can run in a container (needed in Phase 4).

### Tests (no real LLM or network)
- language detection: EN, AR, mixed, digits only
- guard: budget message, deadline, retry once then fail, events, recording
- evidence check: verbatim kept; invented snippet dropped; real snippet with a fake URL dropped; Arabic normalisation; per-sub-question cap; a sub-question left with nothing is reported
- citation check: missing, dangling and unused citations
- pipeline paths with stubbed crews: approved, one revision (and never a second), a tool failure, all tools failing → `unanswered_sub_question_ids`, deadline reached
- usage/cost sums; CLI writes valid JSON that re-validates as `Report`, plus Markdown

### Exit checks (real runs, recorded in DECISIONS.md)
- one quick EN and one quick AR run: valid Report, largest prompt, total tokens, time, cost
- one deep run (if the daily budget allows)

### Definition of done
`uv run researchcrew "question"` produces a valid Report JSON + Markdown file.
