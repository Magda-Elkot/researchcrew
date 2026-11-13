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
- Install: `uv sync --all-groups` (or `make install`)
- Run tests: `uv run pytest` (or `make test`)
- Lint/format: `uv run ruff check . --fix && uv run ruff format .` (or `make format`; `make lint` only checks)
- Type check: `uv run mypy app mcp_servers` (or `make typecheck`)
- Everything CI runs except Docker: `make check`
- Start everything: `docker compose up --build` (or `make up` detached; `make down` stops)
- CLI stub: `uv run researchcrew`
- Evals: `make eval` (placeholder until Phase 6)
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

## Learning mode (important)
- I run the commands myself. Don't run shell commands for me unless I ask.
  This includes uv, docker, pytest, ruff, make and git.
- When a command is needed, show it in a code block and explain:
  1. what it does, 2. what each part/flag means, 3. what output I should expect.
- After I run it, I'll paste the output. Then help me read it and decide the next step.
- You may create and edit files, but only one small group of related files at a
  time, and explain each file before writing it.
- Git: never run git add, git commit or git push. At the end of each phase, suggest
  the exact git commands and a commit message, and I'll run them.
- At the end of each phase, give me 3–5 questions an interviewer might ask
  about what we built, so I can check my understanding.

  