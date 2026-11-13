# Phase 3 — CrewAI agents and tasks with MCP tools, CLI run

**Status:** high-level. This gets a detailed plan when the phase starts. [Back to master plan](PLAN.md)

## Goal
Five agents produce a validated `Report` from a question, using MCP tools only. The crew runs from the CLI.

## Scope
- **Agents:**
  - Planner → `ResearchPlan`
  - Researcher → `list[EvidenceItem]`
  - Analyst → `list[Finding]`
  - Writer → `Report`
  - Reviewer → `ReviewResult`
- **Process:** sequential.
- **Flow:** a CrewAI Flow orchestrates plan → research → analyse → write → review. If the review isn't approved, the Writer rewrites once (`revision_requested`).
- **MCP tools**, connected with the crewai-tools MCP adapter (I'll check its current API in the docs first):
  - docs-mcp over streamable HTTP
  - Tavily's hosted MCP over streamable HTTP
  - filesystem over `npx` stdio, read-only and limited to `data/notes`. Node is added to the api image here.
- **LLM:** through LiteLLM, model from config (default Groq Llama 3.3 70B).
- **Language:** detect the question's language and write the report in that language.
- **Guardrails:**
  - max_iter per agent
  - ≤25 tool calls per run (quick ≤12)
  - 15-minute timeout
  - a failed tool call is retried once (tenacity), then logged and skipped
  - if every tool fails for a sub-question, the report says so instead of inventing an answer
- **Startup:** clear error naming any missing API key.
- **Progress events:** an internal event callback emits `ProgressEvent`. It gets wired to SSE in Phase 4.
- **CLI:** `uv run researchcrew "question" [--depth quick|deep]` writes `outputs/<id>.json` and `outputs/<id>.md`.

## Key files
- `app/agents/{agents.py, tasks.py, flow.py}`
- `app/tools/mcp.py`
- `app/language.py`
- `app/cli.py`

## Tests
- Mocked LLM and mocked MCP tools.
- Flow paths: approved, one revision, tool failure, and all tools failing.
- Output validates against the schemas.

## Definition of done
`uv run researchcrew "question"` produces a valid Report JSON + Markdown file.

## Open items
- Language detection: use a simple heuristic (share of Arabic script) or ask the LLM? Adding a new library would need your approval.
- Whether Groq's free-tier TPM is enough for deep runs.
