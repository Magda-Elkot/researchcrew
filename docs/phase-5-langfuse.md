# Phase 5 — Langfuse tracing

**Status:** done (2026-11-18), waiting for review. Exit check: DECISIONS #97. [Back to master plan](PLAN.md)

## Goal
Every research run (CLI or API) becomes **one trace** in a **self-hosted Langfuse**, with a span
per agent task, per tool call and per LLM call, carrying tokens, cost and latency, and tagged
with depth, model and app version (DECISIONS #60, #90–95).

## What the docs and the installed code say (checked 2026-11-18)
- Langfuse docs (CrewAI integration): `get_client()`, `CrewAIInstrumentor().instrument()` before
  the crew runs, the run inside `start_as_current_observation(as_type="span")` with
  `propagate_attributes(tags=..., metadata=..., version=...)`, then `flush()`.
- Installed SDK 5.2.0: without keys the client disables itself (no-op tracer); otherwise it
  becomes the **global** OpenTelemetry tracer provider, and its default span filter keeps
  `openinference` and `litellm` spans.
- `openinference-instrumentation-crewai` 1.1.27 wraps `Crew.kickoff`, `Task._execute_core`
  (one span per agent task) and `BaseTool.run` (our `GuardedTool` is a `BaseTool`, so one span
  per tool call). `openinference-instrumentation-litellm` 0.1.58 adds one span per LLM call
  with token counts. All three packages are already locked: **no new library**.
- Official self-hosting compose (langfuse/langfuse `docker-compose.yml`): web, worker, Postgres,
  ClickHouse, Redis, MinIO (+ a beta AI gateway); default passwords marked `CHANGEME`; host
  ports 3000, 3030, 5432, 6379, 8123, 9000, 9090, 9091. Headless init (`LANGFUSE_INIT_*`)
  creates the org, project, API keys and first user at startup.

## Design
- **Compose profile `observability`** in our `docker-compose.yml`: the six services, images
  pinned, no AI gateway, **only the web UI published** (127.0.0.1:3000; the rest stay on the
  compose network), Langfuse telemetry off. Secrets come from `.env` under `LANGFUSE_*` names.
- **`scripts/langfuse_env.py`** (`make langfuse-env`): appends random secrets and the headless
  init values to `.env` for the ones that are missing; never prints a value. The app's
  `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are the init project's keys.
- **`app/observability.py`**:
  - `setup_tracing(settings)`: once per process; off (and nothing instrumented) when the keys
    are missing; else creates the Langfuse client and instruments CrewAI + LiteLLM.
  - `traced_run(...)`: the root span of one run, with `propagate_attributes` (trace name
    `research`, tags `depth:`, `model:`, `process:`, `version:`, metadata `job_id`); yields the
    trace id; records the run's summary as the root span's output.
  - A logging filter adds `trace_id` to every log line written inside a run.
- **Hooks:** `run_research` runs inside `traced_run`; `RunResult` gets `trace_id`; the API's
  `GET /research/{id}` returns `trace_id` and `trace_url`; the CLI and the API flush on exit.
- **Cost:** if Langfuse has no price for Groq gpt-oss-120b, a custom model price is created
  (same $0.15/$0.60 per 1M as our LiteLLM table). Our own token/cost numbers stay the source
  of truth; Langfuse must match them.
- **uvicorn access logs as JSON** (moved here from Phase 4): `--log-config` using our
  `JsonFormatter`.

## Steps
1. Compose profile + secrets script + `.env.example` + Makefile; start Langfuse, log in, check
   the API keys with `auth_check()`.
2. `app/observability.py` + settings + hooks (pipeline, CLI, API) + tests (Langfuse mocked,
   no-op without keys, trace id on the job, log filter).
3. One real run: read the trace back through Langfuse's public API, check agent, tool and LLM
   spans, tokens and cost against our numbers; add the model price if needed.
4. uvicorn JSON logs, docs, a trace screenshot for the README (you take it).

## Tests
- Tracing off without keys: nothing instrumented, `traced_run` yields `None`.
- With a fake client: root span, attributes and tags, trace id returned, output recorded.
- Trace id stored on the result and returned by `GET /research/{id}`.
- Log lines inside a run carry `trace_id`.
- Secrets script: fills only missing keys, keeps existing ones, key formats.

## Definition of done
Each run produces one Langfuse trace with agent, tool and LLM spans, tokens and cost.
