# Phase 3 — CrewAI agents and tasks with MCP tools, CLI run

**Status:** high-level. This gets a detailed plan when the phase starts. [Back to master plan](PLAN.md)

Phase 3 is split in two. 3a is a short spike on the riskiest integration (the MCP adapter). 3b builds the full crew on top of it.

---

## Phase 3a — MCP connectivity spike

### Goal
Prove that CrewAI can use all three MCP servers before building five agents on top of them.

### Scope
- Check the current crewai-tools MCP adapter API (and CrewAI's newer `Agent(mcps=[...])` option) in the official docs.
- **One agent**, run from a CLI script, calls:
  - docs-mcp over streamable HTTP
  - Tavily's hosted MCP over streamable HTTP (URL built in code from `TAVILY_API_KEY`)
  - filesystem over stdio (pinned version, installed with `npm i -g` at build time; read tools only; limited to `data/notes`). Node is added to the api image here.
- Decide and record in DECISIONS.md:
  - the adapter lifecycle (it's a context manager): connections per job vs long-lived connections opened in the API lifespan
  - how long the stdio server takes to start
  - tokens per LLM call with the tool schemas attached

### Definition of done
The agent gets a real result from each of the three servers, and the decisions and numbers above are recorded.

---

## Phase 3b — Full crew

### Goal
Five agents produce a validated `Report` from a question, using MCP tools only. The crew runs from the CLI.

### Scope
- **Agents** (one Crew, 5 tasks):
  - Planner → `ResearchPlan`
  - Researcher → `EvidenceSet`
  - Analyst → `FindingSet`
  - Writer → `Report`
  - Reviewer → `ReviewResult`
- **Process:** sequential. The Crew is built by one factory with a `process` parameter, so Phase 6 can build the hierarchical variant (`Process.hierarchical` + `manager_llm`) without changing the agents or tasks.
- **Flow:** a thin CrewAI Flow runs the crew, then the review. If the review isn't approved, the Writer rewrites once (`revision_requested`). The Flow doesn't drive the individual steps.
- **Tool guardrails, in `app/tools/guarded.py`:** one wrapper around every MCP tool:
  - per-run tool-call counter (≤25; quick ≤12)
  - deadline check (15-minute run limit, cooperative)
  - retry once (tenacity), then log and skip
  - emits `tool_called` / `tool_failed` events
  - records each raw tool result for evidence checks and evals
- **Evidence integrity:** each `EvidenceItem.snippet` must be a verbatim substring of a recorded raw tool result (after normalisation). Items that fail are dropped and logged.
- **All tools failing:** if every tool fails for a sub-question, its id goes in `Report.unanswered_sub_question_ids` and the report says so instead of inventing an answer.
- **Context cap:** evidence passed to the Analyst and Writer is capped (max snippet length, top-N items per sub-question), so a single prompt stays within Groq's free-tier tokens-per-minute limit.
- **LLM:** through LiteLLM, model from config (default Groq Llama 3.3 70B).
- **Language:** detect the question's language and write the report in that language.
- **Other guardrails:** `max_iter` per agent; 15-minute timeout.
- **Token usage and cost:** collected per run from CrewAI/LiteLLM usage. Cost is computed with LiteLLM's price table at list price, logged, and saved in the run output.
- **Basic tracing:** Langfuse/OpenInference instrumentation is set up before crewai is imported, with one parent span per run so the Flow and crew show up as one trace. It's off when Langfuse keys are missing. Phase 5 completes it.
- **Startup:** the CLI fails fast with an error naming any missing API key.
- **Progress events:** an internal event callback emits `ProgressEvent`. It gets wired to SSE in Phase 4.
- **CLI:** `uv run researchcrew "question" [--depth quick|deep]` writes `outputs/<id>.json` and `outputs/<id>.md`.

### Key files
- `app/agents/{agents.py, tasks.py, crew.py, flow.py}`
- `app/tools/{mcp.py, guarded.py}`
- `app/language.py`
- `app/usage.py`
- `app/observability.py` (basic)
- `app/cli.py`

### Tests
- Mocked LLM and mocked MCP tools.
- Flow paths: approved, one revision, tool failure, and all tools failing.
- Guardrail wrapper: retry-once, the call cap, the deadline, and the events it emits.
- Evidence check: a verbatim snippet is kept; an invented snippet is dropped.
- Output validates against the schemas.

### Exit checks (measured on real runs, recorded in DECISIONS.md)
- Tokens per quick and deep run, and whether a single prompt stays under Groq's TPM limit.
- Cost per quick report at list price, against SPEC's < $0.05 target.

### Definition of done
`uv run researchcrew "question"` produces a valid Report JSON + Markdown file.

### Open items
- Language detection: use a simple heuristic (share of Arabic script) or ask the LLM? Adding a new library would need your approval.
