# ResearchCrew — instructions for Claude

## Source of truth
- @SPEC.md is the specification. Don't change scope, stack or decisions without
  asking me first. If something in the spec is unclear or wrong, ask.
- Record every non-trivial decision (and why) in DECISIONS.md.
- Keep PROGRESS.md updated: current phase, what's done, what's next, known issues.

## Working style
- One phase at a time. At the end of a phase: stop, summarise, list changed files,
  give the exact commands to run and test it, then wait for me.
- I'm learning: before writing a new component, explain the concept in 3–5
  sentences (e.g. what an MCP resource is, why SSE instead of WebSockets).
- Prefer simple, readable code over clever code. No unnecessary abstractions.
- Don't add libraries not in the spec without asking.
- If you're not sure about a library's current API (CrewAI, MCP SDK, Langfuse,
  crewai-tools), check its official docs instead of guessing.

## Commands
- Install: `uv sync`
- Run tests: `uv run pytest`
- Lint/format: `uv run ruff check . --fix && uv run ruff format .`
- Type check: `uv run mypy app mcp_servers`
- Start everything: `docker compose up --build`
- Evals: `make eval`
(Update this list whenever you add a new command.)

## Code conventions
- Python 3.11+, full type hints, Pydantic v2 models for all data crossing boundaries.
- Config only via pydantic-settings reading env vars; no hard-coded keys, URLs or models.
- Structured JSON logging via one shared logger; never use print() in app code.
- Every module gets a short docstring explaining its role.

## Testing rules
- Never call real LLMs or paid APIs in tests: mock them.
- Every MCP tool, API endpoint and Pydantic schema gets tests.
- Run lint + tests before saying a phase is complete; report the results.

## Safety
- Never print, log or commit secrets. All variables go in .env.example with
  placeholder values and a comment.
- Don't run git commit, git push or destructive commands (rm -rf, docker system prune).
  I review and commit myself.
- Don't modify files outside this project folder.
