# Phase 5 — Langfuse tracing

**Status:** high-level. This gets a detailed plan when the phase starts. [Back to master plan](PLAN.md)

## Goal
Every run is fully observable in Langfuse Cloud (free Hobby plan).

## Scope
- OpenTelemetry/OpenInference instrumentation for CrewAI and LiteLLM, exported to Langfuse. I'll check current Langfuse docs before writing any code.
- **One trace per request**, with spans per agent, per tool call and per LLM call. Each span carries tokens, cost and latency.
- **Trace tags:** depth, model, app version. The trace id is stored on the job.
- **Token usage and cost** are added up per run and returned by `GET /research/{id}`.
- **Cost:** if Langfuse lacks Groq Llama 3.3 pricing, add a custom model price definition.
- **Structured logs** include the trace_id.
- **Toggle:** tracing turns off cleanly when Langfuse keys are missing.

## Key files
- `app/observability.py`
- small hooks in the flow and api

## Tests
- Tracing setup with Langfuse mocked.
- Tracing is a no-op when keys are absent.

## Definition of done
Each run produces one Langfuse trace with agent, tool and LLM spans, tokens and cost.

## Open items
- Whether to self-host Langfuse in compose as an option (supported by SPEC, off by default).
