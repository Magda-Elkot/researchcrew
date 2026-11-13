# Phase 5 — Langfuse tracing (complete)

**Status:** high-level. This gets a detailed plan when the phase starts. [Back to master plan](PLAN.md)

## Goal
Every run is fully observable in Langfuse Cloud (free Hobby plan). Basic instrumentation already exists from Phase 3b; this phase completes it.

## Scope
- Check that the OpenTelemetry/OpenInference instrumentation for CrewAI and LiteLLM (set up in 3b) gives:
  - **one trace per request**, including API-started runs, with spans per agent, per tool call and per LLM call
  - tokens, cost and latency on each span

  I'll check current Langfuse docs before changing anything.
- **Trace tags:** depth, model, app version. The trace id is stored on the job and returned by `GET /research/{id}`.
- **Cost:** if Langfuse lacks Groq Llama 3.3 pricing, add a custom model price definition. The Langfuse totals must match the Phase 3b token/cost numbers, which stay the source of truth.
- **Structured logs** include the trace_id.
- **Toggle:** tracing turns off cleanly when Langfuse keys are missing.

## Key files
- `app/observability.py`
- small hooks in the flow and api

## Tests
- Tracing setup with Langfuse mocked.
- Tracing is a no-op when keys are absent.
- The trace id is saved on the job.

## Definition of done
Each run produces one Langfuse trace with agent, tool and LLM spans, tokens and cost.

## Open items
- Whether to self-host Langfuse in compose as an option (supported by SPEC, off by default).
