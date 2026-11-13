# Phase 4 — FastAPI + SSE + Streamlit frontend

**Status:** high-level. This gets a detailed plan when the phase starts. [Back to master plan](PLAN.md)

## Goal
Expose the crew through an async job API with live progress, and add a single-page Streamlit UI.

## Scope
- **SQLite job store** (stdlib `sqlite3`): job id, question, depth, status, report, citations, token usage, cost, latency, error.
- **`POST /research {question, depth}`** → `{job_id}`. The crew runs as a background task.
- **`GET /research/{id}`** → status, report, citations, token usage, cost, latency.
- **`GET /research/{id}/events`:** a Server-Sent Events stream of `ProgressEvent` JSON. The types are agent_started, tool_called, tool_failed, agent_finished, revision_requested, job_completed and job_failed.
- **Graceful errors:** a failed job gets the `failed` status and a readable message.
- **Streamlit page:**
  - question box and depth selector
  - live progress feed via SSE
  - rendered report
  - Arabic is shown right-to-left (`dir="rtl"`) while `[n]` citations are kept
- **Containers:** `docker/frontend.Dockerfile` and its compose service.

## Key files
- `app/api/{main.py, routes.py, jobs.py, events.py}`
- `frontend/app.py`

## Tests
- Endpoint tests: POST/GET, unknown id → 404, SSE stream format.
- The crew is mocked in all of them.

## Definition of done
POST/GET endpoints work, and the frontend shows live SSE progress and the report.

## Open items
- How to pass events from the background task to the SSE stream: an in-process asyncio queue per job is the proposal.
- Whether to also save events to SQLite so a client can reconnect.
